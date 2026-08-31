"""LLM proposal → evidence grounding → suggestion policy의 orchestration 진입점."""

from collections.abc import Callable

from app.discovery.place_intent.contract import (
    IntentEvidenceError,
    IntentProposer,
    materialize_llm_output,
)
from app.discovery.place_intent.suggestions import (
    IntentSuggestionOutcome,
    compile_intent_suggestions,
)
from app.place.planning.contract import PlaceSearchConditions, PlaceSpatialConstraint
from app.place.planning.intents import PlannerIssue, PlannerStatus


class PlaceIntentSuggestionService:
    def __init__(
        self,
        proposer: IntentProposer,
        *,
        observation_id_factory: Callable[[], str] | None = None,
    ):
        self._proposer = proposer
        self._observation_id_factory = observation_id_factory

    async def suggest(
        self,
        utterance: str,
        *,
        spatial: PlaceSpatialConstraint,
        limit_per_kind: int,
        conditions: PlaceSearchConditions | None = None,
    ) -> IntentSuggestionOutcome:
        raw = await self._proposer.propose(utterance)
        try:
            if self._observation_id_factory is None:
                grounded = materialize_llm_output(utterance, raw)
            else:
                grounded = materialize_llm_output(
                    utterance,
                    raw,
                    id_factory=self._observation_id_factory,
                )
        except IntentEvidenceError:
            return IntentSuggestionOutcome(
                status=PlannerStatus.NEEDS_CLARIFICATION,
                source_disposition=raw.disposition,
                issues=(
                    PlannerIssue(
                        code="intent_evidence_invalid",
                        detail="intent proposal evidence could not be grounded in the utterance",
                    ),
                ),
            )
        return compile_intent_suggestions(
            grounded,
            spatial=spatial,
            limit_per_kind=limit_per_kind,
            conditions=conditions,
        )
