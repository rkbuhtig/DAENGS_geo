"""LLM 출력과 서버가 검증한 planner observation 사이의 계약."""

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol, Self
from uuid import uuid4

from pydantic import Field, model_validator

from app.place.planning.contract import PlanningModel
from app.place.planning.intents import (
    IntentConcept,
    IntentObservation,
    IntentProposal,
    IntentRole,
    IntentSource,
    observe_intent,
)


class ProposalDisposition(StrEnum):
    """해석 후보의 형태일 뿐, 실행·질문 여부를 결정하는 정책 결과가 아니다."""

    PROPOSED = "proposed"
    AMBIGUOUS = "ambiguous"
    ABSTAINED = "abstained"


class ProposalReason(StrEnum):
    INSUFFICIENT_TARGET = "insufficient_target"
    MULTIPLE_PLAUSIBLE_READINGS = "multiple_plausible_readings"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    UNSAFE_TO_GUESS = "unsafe_to_guess"


def _validate_disposition_shape(
    disposition: ProposalDisposition,
    interpretation_count: int,
    reason: ProposalReason | None,
) -> None:
    if disposition is ProposalDisposition.PROPOSED and interpretation_count != 1:
        raise ValueError("proposed output requires exactly one interpretation")
    if disposition is ProposalDisposition.AMBIGUOUS and interpretation_count < 2:
        raise ValueError("ambiguous output requires at least two interpretations")
    if disposition is ProposalDisposition.ABSTAINED and interpretation_count:
        raise ValueError("abstained output cannot carry interpretations")
    if disposition is ProposalDisposition.AMBIGUOUS:
        if reason is not ProposalReason.MULTIPLE_PLAUSIBLE_READINGS:
            raise ValueError("ambiguous output requires multiple_plausible_readings reason")
    elif disposition is ProposalDisposition.PROPOSED and reason is not None:
        raise ValueError("proposed output cannot carry an abstention reason")
    elif disposition is ProposalDisposition.ABSTAINED and reason is None:
        raise ValueError("abstained output requires a reason")


class EvidenceQuote(PlanningModel):
    """LLM이 복사한 원문과 선택적 Python code-point offset."""

    quote: str = Field(min_length=1, max_length=500)
    start: int | None = Field(ge=0)
    end: int | None = Field(ge=0)

    @model_validator(mode="after")
    def offsets_are_a_pair(self) -> Self:
        if (self.start is None) != (self.end is None):
            raise ValueError("evidence start and end must be supplied together")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("evidence end must be greater than start")
        return self


class LLMIntentProposal(PlanningModel):
    """모델이 제안할 수 있는 전부. audit id와 authority 필드는 존재하지 않는다."""

    role: IntentRole
    intent: IntentConcept
    evidence: EvidenceQuote


class IntentInterpretation(PlanningModel):
    """한 문장에 대한 하나의 일관된 해석. 대안은 별도 interpretation으로 둔다."""

    proposals: tuple[LLMIntentProposal, ...] = Field(min_length=1, max_length=20)


class LLMIntentOutput(PlanningModel):
    disposition: ProposalDisposition
    interpretations: tuple[IntentInterpretation, ...] = Field(max_length=3)
    reason: ProposalReason | None

    @model_validator(mode="after")
    def disposition_matches_interpretations(self) -> Self:
        _validate_disposition_shape(
            self.disposition,
            len(self.interpretations),
            self.reason,
        )
        return self


class EvidenceSpan(PlanningModel):
    """서버가 원문에서 다시 계산한 반열림 구간 `[start, end)`."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=500)


class GroundedIntentObservation(PlanningModel):
    observation: IntentObservation
    evidence_span: EvidenceSpan


class MaterializedInterpretation(PlanningModel):
    items: tuple[GroundedIntentObservation, ...] = Field(min_length=1, max_length=20)

    @property
    def observations(self) -> tuple[IntentObservation, ...]:
        return tuple(item.observation for item in self.items)


class MaterializedIntentOutput(PlanningModel):
    disposition: ProposalDisposition
    interpretations: tuple[MaterializedInterpretation, ...] = Field(max_length=3)
    reason: ProposalReason | None

    @model_validator(mode="after")
    def disposition_matches_interpretations(self) -> Self:
        _validate_disposition_shape(
            self.disposition,
            len(self.interpretations),
            self.reason,
        )
        return self


class IntentEvidenceError(ValueError):
    """근거가 원문에 고정되지 않아 interpretation 전체를 신뢰할 수 없음."""


class IntentProposerInvalidOutputError(RuntimeError):
    """제공사 호출은 성공했지만 출력이 authority-free intent 계약을 만족하지 못함."""


class IntentProposer(Protocol):
    async def propose(self, utterance: str) -> LLMIntentOutput: ...


def _server_observation_id() -> str:
    return f"llm-{uuid4().hex}"


def _ground_quote(utterance: str, evidence: EvidenceQuote) -> EvidenceSpan:
    if evidence.start is not None and evidence.end is not None:
        if evidence.end > len(utterance):
            raise IntentEvidenceError("evidence offset exceeds the utterance")
        if utterance[evidence.start : evidence.end] != evidence.quote:
            raise IntentEvidenceError("evidence offsets do not select the quoted utterance text")
        return EvidenceSpan(start=evidence.start, end=evidence.end, text=evidence.quote)

    starts: list[int] = []
    offset = 0
    while True:
        found = utterance.find(evidence.quote, offset)
        if found < 0:
            break
        starts.append(found)
        offset = found + 1
    if not starts:
        raise IntentEvidenceError("evidence quote is not present in the utterance")
    if len(starts) > 1:
        raise IntentEvidenceError("repeated evidence quote requires explicit offsets")
    start = starts[0]
    return EvidenceSpan(start=start, end=start + len(evidence.quote), text=evidence.quote)


def materialize_llm_output(
    utterance: str,
    output: LLMIntentOutput,
    *,
    id_factory: Callable[[], str] = _server_observation_id,
) -> MaterializedIntentOutput:
    """원문 근거를 검증한 뒤에만 server-owned id/source를 부여한다.

    interpretation 일부만 살리면 필수 조건을 조용히 버릴 수 있으므로 하나라도 실패하면
    전체 출력을 거절한다.
    """

    used_ids: set[str] = set()
    interpretations: list[MaterializedInterpretation] = []
    for interpretation in output.interpretations:
        items: list[GroundedIntentObservation] = []
        for raw in interpretation.proposals:
            span = _ground_quote(utterance, raw.evidence)
            observation_id = id_factory()
            if observation_id in used_ids:
                raise IntentEvidenceError("server observation ids must be unique")
            used_ids.add(observation_id)
            proposal = IntentProposal(
                role=raw.role,
                intent=raw.intent,
                evidence=span.text,
            )
            items.append(
                GroundedIntentObservation(
                    observation=observe_intent(
                        proposal,
                        IntentSource.LLM_PROPOSAL,
                        observation_id=observation_id,
                    ),
                    evidence_span=span,
                )
            )
        interpretations.append(MaterializedInterpretation(items=tuple(items)))
    return MaterializedIntentOutput(
        disposition=output.disposition,
        interpretations=tuple(interpretations),
        reason=output.reason,
    )
