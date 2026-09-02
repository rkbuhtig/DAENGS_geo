"""Gemini Interactions API 기반 Place intent proposer.

서버는 stateless structured output만 요청하고 API key나 provider 메타데이터를 Place Search
계약에 싣지 않는다. 모델 출력은 OpenAI 경로와 같은 authority-free 계약으로 검증한다.
"""

import json

import httpx

from app.core.config import settings
from app.discovery.place_intent.contract import (
    IntentProposer,
    IntentProposerInvalidOutputError,
    LLMIntentOutput,
    ProposalDisposition,
    ProposalReason,
)
from app.discovery.place_intent.metering import MeteredIntentProposer
from app.discovery.place_intent.prompt import gemini_output_schema, proposer_instructions
from app.usage.registry import usage_gate

GEMINI_GENERATION_CONFIG = {
    "max_output_tokens": 1800,
    "temperature": 0.0,
}


class GeminiIntentProposerResponseError(RuntimeError):
    pass


class GeminiIntentProposer:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("Gemini API key is required")
        if not model:
            raise ValueError("Gemini model is required")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport

    async def propose(self, utterance: str) -> LLMIntentOutput:
        if not utterance.strip():
            raise ValueError("utterance must not be blank")
        payload = {
            "model": self._model,
            "input": utterance,
            "system_instruction": proposer_instructions()
            + "\nGemini adapter 출력에서는 intent를 평면 필드로 쓴다. intent_type에 맞는 "
            "kind, purpose_id, capability_id와 value, concept_id, activity_id, object_id 중 하나만 채워라. "
            "evidence는 quote와 확신할 때만 start/end로 출력하라. 각 interpretation에 search_mode를 출력하고, "
            "open_discovery일 때만 search_mode_quote와 선택적인 search_mode_start/end를 출력하라. "
            "proposed이면 reason은 none, abstained이면 실제 abstention reason을 출력하라. "
            "세부 사유를 고를 수 없으면 abstained와 unspecified를 출력하라.",
            "store": False,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": gemini_output_schema(),
            },
            "generation_config": GEMINI_GENERATION_CONFIG,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout_s,
            transport=self._transport,
        ) as client:
            response = await client.post(
                f"{self._base_url}/interactions",
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        try:
            body = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise GeminiIntentProposerResponseError(
                "Gemini response body is not valid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise GeminiIntentProposerResponseError("Gemini response must be an object")
        if body.get("status") != "completed":
            raise GeminiIntentProposerResponseError(
                f"Gemini interaction did not complete: {body.get('status')}"
            )
        output_text = _interaction_output_text(body)
        try:
            return _adapter_output(output_text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IntentProposerInvalidOutputError(
                "Gemini returned an invalid intent payload"
            ) from exc


def configured_gemini_intent_proposer() -> IntentProposer:
    """명시적으로 켠 Gemini 3.1 Flash-Lite 실험 경로만 조립한다."""

    if settings.llm_provider != "gemini" or not settings.gemini_api_key:
        raise RuntimeError("Gemini intent proposer is not configured")
    return MeteredIntentProposer(
        GeminiIntentProposer(settings.gemini_api_key, settings.gemini_model),
        usage_gate(),
    )


def _interaction_output_text(body: object) -> str:
    if not isinstance(body, dict):
        raise GeminiIntentProposerResponseError("Gemini response must be an object")
    chunks: list[str] = []
    steps = body.get("steps")
    if not isinstance(steps, list):
        raise GeminiIntentProposerResponseError("Gemini response has no steps")
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ):
                chunks.append(part["text"])
    if not chunks:
        raise GeminiIntentProposerResponseError("Gemini response has no output text")
    return "".join(chunks)


def _adapter_output(output_text: str) -> LLMIntentOutput:
    raw = json.loads(output_text)
    if not isinstance(raw, dict):
        raise TypeError("Gemini adapter output must be an object")
    _reject_unknown_fields(raw, {"disposition", "interpretations", "reason"})
    if "reason" not in raw:
        raise ValueError("Gemini adapter output requires a reason sentinel")
    reason = raw.get("reason")
    if reason == "none":
        reason = (
            ProposalReason.UNSPECIFIED.value
            if raw.get("disposition") == ProposalDisposition.ABSTAINED.value
            else None
        )
    if raw.get("disposition") == ProposalDisposition.ABSTAINED.value:
        # Flash-Lite의 평면 schema는 disposition에 따라 interpretations를 비우는 조건부
        # 제약을 표현하지 못한다. abstained는 어떤 proposal도 실행하지 않는 선언이므로,
        # 딸려온 불완전 proposal을 해석하거나 부분 salvage하지 않고 통째로 버린다.
        return LLMIntentOutput.model_validate(
            {
                "disposition": raw.get("disposition"),
                "interpretations": [],
                "reason": reason,
            }
        )
    interpretations = []
    for interpretation in raw.get("interpretations", []):
        if not isinstance(interpretation, dict):
            raise TypeError("Gemini interpretation must be an object")
        _reject_unknown_fields(
            interpretation,
            {
                "search_mode",
                "search_mode_quote",
                "search_mode_start",
                "search_mode_end",
                "proposals",
            },
        )
        directive_start = interpretation.get("search_mode_start")
        directive_end = interpretation.get("search_mode_end")
        if (directive_start is None) != (directive_end is None):
            directive_start = None
            directive_end = None
        directive_quote = interpretation.get("search_mode_quote")
        directive_evidence = (
            {
                "quote": directive_quote,
                "start": directive_start,
                "end": directive_end,
            }
            if directive_quote is not None
            else None
        )
        proposals = []
        for proposal in interpretation.get("proposals", []):
            if not isinstance(proposal, dict):
                raise TypeError("Gemini proposal must be an object")
            _reject_unknown_fields(
                proposal,
                {
                    "role",
                    "intent_type",
                    "kind",
                    "purpose_id",
                    "capability_id",
                    "value",
                    "concept_id",
                    "activity_id",
                    "object_id",
                    "quote",
                    "start",
                    "end",
                },
            )
            intent_type = proposal.get("intent_type")
            if intent_type == "kind":
                intent = {"intent_type": intent_type, "kind": proposal.get("kind")}
            elif intent_type == "purpose":
                intent = {
                    "intent_type": intent_type,
                    "purpose_id": proposal.get("purpose_id"),
                }
            elif intent_type == "boolean_capability":
                intent = {
                    "intent_type": intent_type,
                    "capability_id": proposal.get("capability_id"),
                    "value": proposal.get("value"),
                }
            elif intent_type == "semantic":
                intent = {
                    "intent_type": intent_type,
                    "concept_id": proposal.get("concept_id"),
                }
            elif intent_type == "activity":
                intent = {
                    "intent_type": intent_type,
                    "activity_id": proposal.get("activity_id"),
                }
            elif intent_type == "object":
                intent = {
                    "intent_type": intent_type,
                    "object_id": proposal.get("object_id"),
                }
            else:
                raise ValueError(f"unknown Gemini intent type: {intent_type}")
            start = proposal.get("start")
            end = proposal.get("end")
            if (start is None) != (end is None):
                # Flash-Lite의 선택 필드는 서로 의존하지 않는다. 반쪽 offset을 추측해
                # 완성하지 않고 둘 다 버리면 이후 quote grounding이 원문에서 다시 찾는다.
                start = None
                end = None
            proposals.append(
                {
                    "role": proposal.get("role"),
                    "intent": intent,
                    "evidence": {
                        "quote": proposal.get("quote"),
                        "start": start,
                        "end": end,
                    },
                }
            )
        interpretations.append(
            {
                "search_directive": {
                    "mode": interpretation.get("search_mode"),
                    "evidence": directive_evidence,
                },
                "proposals": proposals,
            }
        )
    return LLMIntentOutput.model_validate(
        {
            "disposition": raw.get("disposition"),
            "interpretations": interpretations,
            "reason": reason,
        }
    )


def _reject_unknown_fields(value: dict, allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("unknown Gemini adapter fields: " + ", ".join(unknown))
