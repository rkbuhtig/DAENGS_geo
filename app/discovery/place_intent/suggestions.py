"""검증된 LLM interpretation을 독립적인 Place plan 제안으로 컴파일한다."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from app.discovery.place_intent.contract import (
    MaterializedIntentOutput,
    ProposalDisposition,
    ProposalReason,
)
from app.place.planning.contract import (
    PlaceKind,
    PlaceSearchConditions,
    PlaceSpatialConstraint,
    PlanningModel,
)
from app.place.planning.intents import (
    ActivityIntent,
    BooleanCapabilityIntent,
    IntentConcept,
    IntentObservation,
    IntentProposal,
    IntentRole,
    IntentSource,
    KindIntent,
    ObjectIntent,
    PlannerIssue,
    PlannerRequest,
    PlannerResult,
    PlannerStatus,
    PurposeIntent,
    SemanticIntent,
    observe_intent,
)
from app.place.planning.planner import compile_intent_plan
from app.place.planning.purpose import PurposeId


class SuggestionResolution(StrEnum):
    INFERRED = "inferred"
    EXPLORATORY = "exploratory"


class SuggestionBasis(StrEnum):
    INTERPRETATION = "interpretation"
    PRODUCT_FALLBACK = "product_fallback"
    HYPOTHESIS = "hypothesis"


class IntentPlanCandidate(PlanningModel):
    candidate_key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9_.:-]+$",
    )
    basis: SuggestionBasis
    basis_observation_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    result: PlannerResult


class IntentSuggestionOutcome(PlanningModel):
    status: PlannerStatus
    resolution: SuggestionResolution | None = None
    # 제공사 출력 자체가 유효하지 않으면 신뢰할 disposition도 없다.
    source_disposition: ProposalDisposition | None
    suggestions: tuple[IntentPlanCandidate, ...] = ()
    rejected: tuple[IntentPlanCandidate, ...] = ()
    issues: tuple[PlannerIssue, ...] = ()

    @model_validator(mode="after")
    def status_matches_candidates(self) -> Self:
        keys = [item.candidate_key for item in (*self.suggestions, *self.rejected)]
        if len(keys) != len(set(keys)):
            raise ValueError("suggestion candidate keys must be unique")
        if any(item.result.status is not PlannerStatus.READY for item in self.suggestions):
            raise ValueError("suggestions must carry ready planner results")
        if any(item.result.status is PlannerStatus.READY for item in self.rejected):
            raise ValueError("rejected candidates cannot carry ready planner results")
        if self.source_disposition is None:
            valid_invalid_output = (
                self.status is PlannerStatus.NEEDS_CLARIFICATION
                and self.resolution is None
                and not self.suggestions
                and not self.rejected
                and len(self.issues) == 1
                and self.issues[0].code == "intent_proposer_invalid_output"
            )
            if not valid_invalid_output:
                raise ValueError(
                    "missing source disposition requires an empty invalid-output clarification"
                )
        if self.status is PlannerStatus.READY:
            if not self.suggestions or self.resolution is None or self.source_disposition is None:
                raise ValueError("ready suggestion outcome requires suggestions and resolution")
            if self.issues:
                raise ValueError("ready suggestion outcome cannot carry global issues")
            if self.resolution is SuggestionResolution.INFERRED and (
                self.source_disposition is not ProposalDisposition.PROPOSED
                or len(self.suggestions) != 1
                or self.suggestions[0].basis is not SuggestionBasis.INTERPRETATION
            ):
                raise ValueError("inferred resolution requires one direct proposed interpretation")
            return self
        if self.suggestions or self.resolution is not None:
            raise ValueError("non-ready suggestion outcome cannot carry executable suggestions")
        if not self.rejected and not self.issues:
            raise ValueError("non-ready suggestion outcome requires a rejected candidate or issue")
        return self


_SOFT_PLACE_ROLES = {
    IntentRole.PREFERENCE,
    IntentRole.ANALOGY,
    IntentRole.HYPOTHETICAL,
}
_SOFT_SEMANTIC_ROLES = {
    IntentRole.GOAL,
    IntentRole.REQUIRED_TARGET,
    IntentRole.REQUIRED_CONDITION,
    IntentRole.PREFERENCE,
    IntentRole.ANALOGY,
}
_LEISURE_SEMANTIC_FALLBACKS = {
    "semantic.atmosphere",
    "semantic.comfort",
    "semantic.cozy",
    "semantic.quiet",
    # 비용 축을 먼저 고르게 하므로 이 fallback 자체는 실행되지 않는다. 선택 뒤에도 목적이
    # 비어 있을 때 사용자가 좁힐 제품 관리 방향만 보존한다.
    "semantic.cheap",
}
_DEFAULT_LEISURE_TARGETS: tuple[PurposeIntent, ...] = (
    PurposeIntent(purpose_id=PurposeId.DINING),
    PurposeIntent(purpose_id=PurposeId.OUTING),
    PurposeIntent(purpose_id=PurposeId.CULTURE),
)


def _compile(
    observations: tuple[IntentObservation, ...],
    *,
    spatial: PlaceSpatialConstraint,
    limit_per_kind: int,
    conditions: PlaceSearchConditions | None,
) -> PlannerResult:
    return compile_intent_plan(
        PlannerRequest(
            spatial=spatial,
            observations=observations,
            limit_per_kind=limit_per_kind,
            conditions=conditions,
        )
    )


def _is_healthcare(intent: KindIntent | PurposeIntent) -> bool:
    if isinstance(intent, PurposeIntent):
        return intent.purpose_id is PurposeId.HEALTHCARE
    return intent.kind in {PlaceKind.HOSPITAL, PlaceKind.PHARMACY}


def _fallback_targets(
    observations: tuple[IntentObservation, ...],
) -> tuple[IntentConcept, ...]:
    """명시 allowlist의 여가 soft cue에만 제품 fallback을 연다."""

    mentioned: dict[str, KindIntent | PurposeIntent] = {}
    has_supported_semantic = False
    for observation in observations:
        intent = observation.intent
        if isinstance(intent, BooleanCapabilityIntent):
            if observation.role is not IntentRole.PREFERENCE:
                return ()
            continue
        if isinstance(intent, SemanticIntent):
            if (
                observation.role not in _SOFT_SEMANTIC_ROLES
                or intent.concept_id not in _LEISURE_SEMANTIC_FALLBACKS
            ):
                return ()
            has_supported_semantic = True
            continue
        if isinstance(intent, (ActivityIntent, ObjectIntent)):
            return ()
        if observation.role not in _SOFT_PLACE_ROLES or _is_healthcare(intent):
            return ()
        mentioned[intent.model_dump_json()] = intent

    if mentioned:
        return tuple(mentioned.values())
    if has_supported_semantic:
        return _DEFAULT_LEISURE_TARGETS
    return ()


def _fallback_observation_id(
    interpretation_index: int,
    intent: KindIntent | PurposeIntent,
) -> str:
    if isinstance(intent, KindIntent):
        suffix = f"kind-{intent.kind.value}"
    else:
        suffix = f"purpose-{intent.purpose_id.value}"
    return f"product-fallback-interpretation-{interpretation_index}-{suffix}"


def _fallback_candidate_key(
    interpretation_index: int,
    intent: KindIntent | PurposeIntent,
) -> str:
    if isinstance(intent, KindIntent):
        suffix = f"kind:{intent.kind.value}"
    else:
        suffix = f"purpose:{intent.purpose_id.value}"
    return f"interpretation:{interpretation_index}:fallback:{suffix}"


def _product_fallbacks(
    observations: tuple[IntentObservation, ...],
    *,
    interpretation_index: int,
    spatial: PlaceSpatialConstraint,
    limit_per_kind: int,
    conditions: PlaceSearchConditions | None,
) -> tuple[IntentPlanCandidate, ...]:
    targets = _fallback_targets(observations)
    if not targets:
        return ()
    preferences = tuple(
        observation
        for observation in observations
        if isinstance(observation.intent, BooleanCapabilityIntent)
        and observation.role is IntentRole.PREFERENCE
    )
    basis_ids = tuple(observation.observation_id for observation in observations)
    candidates = []
    for target in targets:
        assert isinstance(target, (KindIntent, PurposeIntent))
        fallback_id = _fallback_observation_id(interpretation_index, target)
        target_observation = observe_intent(
            IntentProposal(role=IntentRole.REQUIRED_TARGET, intent=target),
            IntentSource.RULE_INFERENCE,
            observation_id=fallback_id,
        )
        result = _compile(
            (target_observation, *preferences),
            spatial=spatial,
            limit_per_kind=limit_per_kind,
            conditions=conditions,
        )
        candidates.append(
            IntentPlanCandidate(
                candidate_key=_fallback_candidate_key(interpretation_index, target),
                basis=SuggestionBasis.PRODUCT_FALLBACK,
                basis_observation_ids=basis_ids,
                result=result,
            )
        )
    return tuple(candidates)


def _abstention_outcome(output: MaterializedIntentOutput) -> IntentSuggestionOutcome:
    assert output.reason is not None
    unsupported = output.reason is ProposalReason.UNSUPPORTED_LANGUAGE
    return IntentSuggestionOutcome(
        status=PlannerStatus.UNSUPPORTED if unsupported else PlannerStatus.NEEDS_CLARIFICATION,
        source_disposition=output.disposition,
        issues=(
            PlannerIssue(
                code="intent_proposer_abstained",
                detail=f"intent proposer abstained: {output.reason.value}",
                blocking=unsupported,
            ),
        ),
    )


def compile_intent_suggestions(
    output: MaterializedIntentOutput,
    *,
    spatial: PlaceSpatialConstraint,
    limit_per_kind: int,
    conditions: PlaceSearchConditions | None = None,
) -> IntentSuggestionOutcome:
    """대안 해석을 합치지 않고 plan 후보로 만들며, 실패한 해석도 숨기지 않는다."""

    if output.disposition is ProposalDisposition.ABSTAINED:
        return _abstention_outcome(output)

    candidates: list[IntentPlanCandidate] = []
    for index, interpretation in enumerate(output.interpretations, start=1):
        observations = interpretation.observations
        candidates.append(
            IntentPlanCandidate(
                candidate_key=f"interpretation:{index}",
                basis=SuggestionBasis.INTERPRETATION,
                basis_observation_ids=tuple(item.observation_id for item in observations),
                result=_compile(
                    observations,
                    spatial=spatial,
                    limit_per_kind=limit_per_kind,
                    conditions=conditions,
                ),
            )
        )

    ready = tuple(item for item in candidates if item.result.status is PlannerStatus.READY)
    rejected = tuple(item for item in candidates if item.result.status is not PlannerStatus.READY)
    if ready:
        resolution = (
            SuggestionResolution.EXPLORATORY
            if output.disposition is ProposalDisposition.AMBIGUOUS or len(ready) > 1
            else SuggestionResolution.INFERRED
        )
        return IntentSuggestionOutcome(
            status=PlannerStatus.READY,
            resolution=resolution,
            source_disposition=output.disposition,
            suggestions=ready,
            rejected=rejected,
        )

    fallback_candidates = tuple(
        fallback
        for index, interpretation in enumerate(output.interpretations, start=1)
        for fallback in _product_fallbacks(
            interpretation.observations,
            interpretation_index=index,
            spatial=spatial,
            limit_per_kind=limit_per_kind,
            conditions=conditions,
        )
    )
    fallback_ready = tuple(
        item for item in fallback_candidates if item.result.status is PlannerStatus.READY
    )
    fallback_rejected = tuple(
        item for item in fallback_candidates if item.result.status is not PlannerStatus.READY
    )
    all_rejected = (*rejected, *fallback_rejected)
    if fallback_ready:
        return IntentSuggestionOutcome(
            status=PlannerStatus.READY,
            resolution=SuggestionResolution.EXPLORATORY,
            source_disposition=output.disposition,
            suggestions=fallback_ready,
            rejected=all_rejected,
        )

    status = (
        PlannerStatus.NEEDS_CLARIFICATION
        if any(item.result.status is PlannerStatus.NEEDS_CLARIFICATION for item in all_rejected)
        else PlannerStatus.UNSUPPORTED
    )
    return IntentSuggestionOutcome(
        status=status,
        source_disposition=output.disposition,
        rejected=all_rejected,
    )
