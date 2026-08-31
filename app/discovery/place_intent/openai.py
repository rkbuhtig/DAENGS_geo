"""OpenAI Responses API 기반 Place intent proposer.

Place 검색 전용 entrypoint는 이 모듈을 import하지 않는다. 모델 호출은 orchestration 경계에서
UsageGate를 통과하고, 반환값은 authority 없는 LLMIntentOutput뿐이다.
"""

import json

import httpx

from app.core.config import settings
from app.discovery.place_intent.contract import IntentProposer, LLMIntentOutput
from app.discovery.place_intent.prompt import proposer_instructions, strict_output_schema
from app.usage.gate import UsageGate
from app.usage.models import LanguageParseIntent
from app.usage.registry import usage_gate


class IntentProposerResponseError(RuntimeError):
    pass


class OpenAIIntentProposer:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("OpenAI API key is required")
        if not model:
            raise ValueError("OpenAI model is required")
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
            "instructions": proposer_instructions(),
            "input": utterance,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "place_intent_proposal",
                    "description": "Authority-free interpretations grounded in the user utterance.",
                    "strict": True,
                    "schema": strict_output_schema(),
                }
            },
            "store": False,
            "max_output_tokens": 1800,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout_s,
            transport=self._transport,
        ) as client:
            response = await client.post(
                f"{self._base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise IntentProposerResponseError("OpenAI response must be an object")
        if body.get("status") not in {None, "completed"}:
            raise IntentProposerResponseError(
                f"OpenAI response did not complete: {body.get('status')}"
            )
        output_text = _response_output_text(body)
        try:
            return LLMIntentOutput.model_validate_json(output_text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise IntentProposerResponseError("OpenAI returned an invalid intent payload") from exc


class MeteredIntentProposer:
    """실제 모델 호출 직전에 기존 language.parse 사용량 정책을 집행한다."""

    def __init__(self, inner: IntentProposer, gate: UsageGate):
        self._inner = inner
        self._gate = gate

    async def propose(self, utterance: str) -> LLMIntentOutput:
        intent = LanguageParseIntent(input_chars=len(utterance))
        permit = await self._gate.check(intent)
        await self._gate.consume(intent, permit)
        return await self._inner.propose(utterance)


def configured_intent_proposer() -> IntentProposer:
    """룰 fallback 없이 명시적으로 설정된 실제 proposer만 조립한다."""

    if settings.llm_provider != "openai" or not settings.openai_api_key:
        raise RuntimeError("OpenAI intent proposer is not configured")
    return MeteredIntentProposer(
        OpenAIIntentProposer(settings.openai_api_key, settings.openai_model),
        usage_gate(),
    )


def _response_output_text(body: object) -> str:
    if not isinstance(body, dict):
        raise IntentProposerResponseError("OpenAI response must be an object")
    direct = body.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    chunks: list[str] = []
    output = body.get("output")
    if not isinstance(output, list):
        raise IntentProposerResponseError("OpenAI response has no output")
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                raise IntentProposerResponseError("OpenAI refused the intent proposal")
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    if not chunks:
        raise IntentProposerResponseError("OpenAI response has no output text")
    return "".join(chunks)
