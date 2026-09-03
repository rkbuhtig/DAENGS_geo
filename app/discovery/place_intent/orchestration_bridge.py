"""운영 오케스트레이션에 넣을 Place 소유 데이터만 검증하는 호환 bridge.

공통 RoutePlan이나 CapabilityResult를 복제하지 않는다. 이 모듈은 신뢰된 구조화 입력을
기존 Place intent 서비스에 전달하고, provider 원출력을 제외한 planning 결과만 투영한다.
"""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.discovery.place_intent.contract import ProposalDisposition
from app.discovery.place_intent.lenses import SearchLensOutcome
from app.discovery.place_intent.service import (
    PlaceIntentSuggestionService,
    PlaceIntentSuggestionTrace,
)
from app.discovery.place_intent.suggestions import SuggestionResolution
from app.place.planning.contract import (
    MAX_RESULTS_PER_KIND,
    PlaceSearchConditions,
    PlaceSpatialConstraint,
    PlanningModel,
)
from app.place.planning.intents import PlannerIssue, PlannerStatus


class PlaceCapabilityInput(PlanningModel):
    """전역 planner/adapter가 Place 도메인에 넘길 수 있는 최소 입력.

    ``query``는 공백 검증만 하고 원문을 보존한다. 위치와 반려견 조건은 LLM 출력이 아니라
    호출자가 검증한 구조화 값으로만 받는다.
    """

    query: str = Field(min_length=1, max_length=1_000)
    spatial: PlaceSpatialConstraint
    limit_per_kind: int = Field(ge=1, le=MAX_RESULTS_PER_KIND)
    conditions: PlaceSearchConditions | None = None

    @field_validator("query")
    @classmethod
    def query_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class PlaceDiscoveryPlanningData(PlanningModel):
    """공통 capability 봉투의 ``data``가 될 수 있는 Place planning 조각.

    검증된 lens와 사용자 refinement 신호까지만 공개한다. 검색과 presentation은 별도
    assembly 서비스가 이 값을 입력으로 받아 실행하므로 planning 자체와 섞지 않는다.
    """

    contract_version: Literal["place-discovery-planning-v1"] = "place-discovery-planning-v1"
    status: PlannerStatus
    source_disposition: ProposalDisposition | None
    resolution: SuggestionResolution | None = None
    lenses: SearchLensOutcome = Field(
        default_factory=lambda: SearchLensOutcome(target_lenses=(), signal_lenses=())
    )
    issues: tuple[PlannerIssue, ...] = ()
    rejected_candidate_count: int = Field(ge=0)

    @model_validator(mode="after")
    def status_matches_public_shape(self) -> Self:
        if self.status is PlannerStatus.READY:
            if (
                self.resolution is None
                or self.source_disposition is None
                or not self.lenses.target_lenses
            ):
                raise ValueError(
                    "ready discovery planning data requires a resolution, disposition, and target"
                )
        elif self.resolution is not None:
            raise ValueError("non-ready discovery planning data cannot carry a resolution")

        if self.source_disposition is None:
            valid_invalid_output = (
                self.status is PlannerStatus.NEEDS_CLARIFICATION
                and not self.lenses.target_lenses
                and not self.lenses.signal_lenses
                and self.rejected_candidate_count == 0
                and len(self.issues) == 1
                and self.issues[0].code == "intent_proposer_invalid_output"
            )
            if not valid_invalid_output:
                raise ValueError(
                    "missing source disposition requires an empty invalid-output planning result"
                )

        issue_keys = [
            (issue.observation_ids, issue.code, issue.detail, issue.blocking)
            for issue in self.issues
        ]
        if len(issue_keys) != len(set(issue_keys)):
            raise ValueError("public planning issues must be unique")
        return self


def _public_issues(trace: PlaceIntentSuggestionTrace) -> tuple[PlannerIssue, ...]:
    """전역 issue와 숨긴 rejected candidate의 이유를 순서대로 중복 없이 보존한다."""

    candidates = trace.outcome.rejected
    issue_groups = (
        trace.outcome.issues,
        *(candidate.result.not_applied for candidate in candidates),
        *(candidate.result.unsupported for candidate in candidates),
        *(candidate.result.clarifications for candidate in candidates),
    )
    seen: set[tuple[tuple[str, ...], str, str, bool]] = set()
    public = []
    for issue in (item for group in issue_groups for item in group):
        key = (issue.observation_ids, issue.code, issue.detail, issue.blocking)
        if key in seen:
            continue
        seen.add(key)
        public.append(issue)
    return tuple(public)


def project_place_discovery_planning(
    trace: PlaceIntentSuggestionTrace,
) -> PlaceDiscoveryPlanningData:
    """내부 trace에서 raw/grounded/normalized provider 자료를 제외한 결과만 만든다."""

    outcome = trace.outcome
    return PlaceDiscoveryPlanningData(
        status=outcome.status,
        source_disposition=outcome.source_disposition,
        resolution=outcome.resolution,
        lenses=trace.lenses or SearchLensOutcome(target_lenses=(), signal_lenses=()),
        issues=_public_issues(trace),
        rejected_candidate_count=len(outcome.rejected),
    )


class PlaceIntentCompatibilityBridge:
    """오케스트레이션 모양의 입력과 현재 Place intent 서비스를 잇는다."""

    def __init__(self, service: PlaceIntentSuggestionService):
        self._service = service

    async def plan(self, request: PlaceCapabilityInput) -> PlaceDiscoveryPlanningData:
        trace = await self._service.inspect(
            request.query,
            spatial=request.spatial,
            limit_per_kind=request.limit_per_kind,
            conditions=request.conditions,
        )
        return project_place_discovery_planning(trace)


__all__ = [
    "PlaceCapabilityInput",
    "PlaceDiscoveryPlanningData",
    "PlaceIntentCompatibilityBridge",
    "project_place_discovery_planning",
]
