"""검증된 Place lens를 검색하고 source-aware presentation까지 조립한다."""

from collections.abc import Awaitable, Callable
from typing import Literal, Self

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.place_intent.lenses import (
    LensAvailability,
    SearchSignalLens,
    TargetSearchLens,
)
from app.discovery.place_intent.orchestration_bridge import (
    PlaceCapabilityInput,
    PlaceDiscoveryPlanningData,
    PlaceIntentCompatibilityBridge,
)
from app.place.planning.contract import (
    MAX_TOTAL_RESULTS,
    CapabilityId,
    GateMode,
    PlaceSearchPlan,
    PlanningModel,
)
from app.place.planning.execution import purpose_kinds
from app.place.presentation.assembler import assemble_place_presentation
from app.place.presentation.contract import PlacePresentation
from app.place.presentation.needs import InformationNeedId
from app.place.search import PlaceSearchResponse, search_place_plan
from app.place.source_facts.bundle import CandidateFactBundle, SourceFactKey
from app.place.source_facts.reader import (
    MAX_BUNDLE_CANDIDATES,
    load_candidate_fact_bundles,
    source_fact_key,
)

SearchPlanExecutor = Callable[
    [AsyncSession, PlaceSearchPlan],
    Awaitable[PlaceSearchResponse],
]
SourceFactLoader = Callable[
    [AsyncSession, list[SourceFactKey]],
    Awaitable[list[CandidateFactBundle]],
]

MAX_DISCOVERY_RESULTS = MAX_TOTAL_RESULTS
_OPTION_NEEDS = {
    item.value: item
    for item in (
        InformationNeedId.COST_TRAVEL_DISTANCE,
        InformationNeedId.COST_PET_FEE,
        InformationNeedId.COST_ADMISSION,
        InformationNeedId.COST_PRODUCT_PRICE,
    )
}


def _signal_belongs_to_target(signal: SearchSignalLens, target: TargetSearchLens) -> bool:
    marker = ":facet:"
    if marker not in signal.lens_id or not signal.lens_id.startswith("signal:"):
        return False
    hypothesis_set_key = signal.lens_id.removeprefix("signal:").split(marker, maxsplit=1)[0]
    return target.lens_id.startswith(f"lens:{hypothesis_set_key}:")


class PlaceDiscoveryLensResult(PlanningModel):
    """한 executable lens의 검색 결과와 같은 순서의 표시 모델."""

    lens_id: str = Field(min_length=1, max_length=160)
    display_label: str = Field(min_length=1, max_length=80)
    support_note: str = Field(min_length=1, max_length=300)
    information_needs: tuple[InformationNeedId, ...] = ()
    search: PlaceSearchResponse
    presentations: tuple[PlacePresentation, ...] = ()

    @model_validator(mode="after")
    def presentations_match_search_hits(self) -> Self:
        hit_keys = [hit.place.key for group in self.search.groups for hit in group.results]
        presentation_keys = [item.place_key for item in self.presentations]
        if presentation_keys != hit_keys:
            raise ValueError("presentations must match search hits in group order")
        return self


class PlaceDiscoveryData(PlanningModel):
    """공통 capability 봉투에 넣을 수 있는 완결된 Place 발견 데이터."""

    contract_version: Literal["place-discovery-v1"] = "place-discovery-v1"
    planning: PlaceDiscoveryPlanningData
    lens_results: tuple[PlaceDiscoveryLensResult, ...] = ()

    @model_validator(mode="after")
    def results_match_executable_lenses(self) -> Self:
        expected = [item.lens_id for item in self.planning.lenses.executable_targets]
        actual = [item.lens_id for item in self.lens_results]
        if actual != expected:
            raise ValueError("lens results must cover executable target lenses in order")
        return self


def information_needs_for_lens(
    lens: TargetSearchLens,
    signal_lenses: tuple[SearchSignalLens, ...],
) -> tuple[InformationNeedId, ...]:
    """lens가 보존한 의미를 표시 우선순위로 옮기되 검색 조건으로 승격하지 않는다."""

    needs = list(lens.information_need_ids)
    plan = lens.candidate.result.plan
    if plan is None:
        raise ValueError("information needs require a ready target plan")
    if any(
        gate.capability_id is CapabilityId.OPERATIONS_PARKING and gate.mode is not GateMode.OFF
        for gate in plan.gates
    ):
        needs.append(InformationNeedId.OPERATIONS_PARKING)
    if plan.conditions is not None and (
        plan.conditions.dog_size is not None or plan.conditions.dog_weight_kg is not None
    ):
        needs.append(InformationNeedId.PET_SIZE)
    needs.extend(
        _OPTION_NEEDS[item.selected_option_id]
        for item in signal_lenses
        if item.availability is LensAvailability.RESOLVED
        and item.selected_option_id in _OPTION_NEEDS
        and _signal_belongs_to_target(item, lens)
    )
    return tuple(dict.fromkeys(needs))


def _source_keys(searches: list[PlaceSearchResponse]) -> list[SourceFactKey]:
    unique: dict[tuple[str, str], SourceFactKey] = {}
    for search in searches:
        for group in search.groups:
            for hit in group.results:
                key = source_fact_key(hit.place.key)
                if key is not None:
                    unique.setdefault((key.source, key.source_ref), key)
    return list(unique.values())


async def _load_bundles(
    db: AsyncSession,
    keys: list[SourceFactKey],
    loader: SourceFactLoader,
) -> dict[tuple[str, str], CandidateFactBundle]:
    bundles: dict[tuple[str, str], CandidateFactBundle] = {}
    for offset in range(0, len(keys), MAX_BUNDLE_CANDIDATES):
        chunk = keys[offset : offset + MAX_BUNDLE_CANDIDATES]
        loaded = await loader(db, chunk)
        if [item.key for item in loaded] != chunk:
            raise RuntimeError("source fact loader must preserve every requested key in order")
        for item in loaded:
            bundles[(item.key.source, item.key.source_ref)] = item
    return bundles


class PlaceDiscoveryAssemblyService:
    """planning과 실행을 잇는 얇은 서비스. LLM 원출력이나 전역 route를 소유하지 않는다."""

    def __init__(
        self,
        bridge: PlaceIntentCompatibilityBridge,
        *,
        searcher: SearchPlanExecutor = search_place_plan,
        source_fact_loader: SourceFactLoader = load_candidate_fact_bundles,
    ):
        self._bridge = bridge
        self._searcher = searcher
        self._source_fact_loader = source_fact_loader

    async def discover(
        self,
        db: AsyncSession,
        request: PlaceCapabilityInput,
    ) -> PlaceDiscoveryData:
        planning = await self._bridge.plan(request)
        return await self.execute(db, planning)

    async def execute(
        self,
        db: AsyncSession,
        planning: PlaceDiscoveryPlanningData,
    ) -> PlaceDiscoveryData:
        """초기 planning 또는 사용자가 refinement한 planning을 같은 방식으로 실행한다."""

        targets = planning.lenses.executable_targets
        plans = []
        planned_result_count = 0
        for target in targets:
            plan = target.candidate.result.plan
            if plan is None:
                raise RuntimeError("executable target lens did not carry a search plan")
            plans.append(plan)
            planned_result_count += plan.limit_per_kind * len(purpose_kinds(plan))
        if planned_result_count > MAX_DISCOVERY_RESULTS:
            raise ValueError(
                "discovery plans exceed the aggregate "
                f"{MAX_DISCOVERY_RESULTS}-result execution budget"
            )

        searches = [await self._searcher(db, plan) for plan in plans]

        bundles = await _load_bundles(
            db,
            _source_keys(searches),
            self._source_fact_loader,
        )
        lens_results = []
        for target, search in zip(targets, searches, strict=True):
            needs = information_needs_for_lens(target, planning.lenses.signal_lenses)
            presentations = []
            for group in search.groups:
                for hit in group.results:
                    key = source_fact_key(hit.place.key)
                    bundle = bundles.get((key.source, key.source_ref)) if key is not None else None
                    presentations.append(
                        assemble_place_presentation(
                            hit,
                            group,
                            lens_id=target.lens_id,
                            lens_label=target.display_label,
                            lens_support_note=target.support_note,
                            information_needs=needs,
                            source_facts=bundle,
                        )
                    )
            lens_results.append(
                PlaceDiscoveryLensResult(
                    lens_id=target.lens_id,
                    display_label=target.display_label,
                    support_note=target.support_note,
                    information_needs=needs,
                    search=search,
                    presentations=tuple(presentations),
                )
            )
        return PlaceDiscoveryData(planning=planning, lens_results=tuple(lens_results))


__all__ = [
    "MAX_DISCOVERY_RESULTS",
    "PlaceDiscoveryAssemblyService",
    "PlaceDiscoveryData",
    "PlaceDiscoveryLensResult",
    "information_needs_for_lens",
]
