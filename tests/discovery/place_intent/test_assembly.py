from collections.abc import Iterator

import pytest

from app.discovery.place_intent.assembly import PlaceDiscoveryAssemblyService
from app.discovery.place_intent.contract import (
    EvidenceQuote,
    IntentInterpretation,
    LLMIntentOutput,
    LLMIntentProposal,
    ProposalDisposition,
    ProposalReason,
)
from app.discovery.place_intent.orchestration_bridge import (
    PlaceCapabilityInput,
    PlaceIntentCompatibilityBridge,
)
from app.discovery.place_intent.service import PlaceIntentSuggestionService
from app.place.contracts import (
    PlaceClassification,
    PlaceFacts,
    PlaceMatch,
    PlaceRef,
    PlaceResult,
)
from app.place.planning.contract import PlaceKind, PlaceSpatialConstraint
from app.place.planning.execution import purpose_kinds
from app.place.planning.intents import (
    ActivityId,
    ActivityIntent,
    IntentRole,
    KindIntent,
    ObjectIntent,
    SearchObjectId,
    SemanticIntent,
)
from app.place.presentation.needs import InformationNeedId
from app.place.search import PlaceSearchGroup, PlaceSearchHit, PlaceSearchResponse
from app.place.source_facts.bundle import (
    SourceFactKey,
    SourceFactVariant,
    build_candidate_fact_bundle,
)
from app.place.source_facts.kto import project_kto
from app.place.source_facts.states import DetailAcquisitionState, FactState


class _Proposer:
    async def propose(self, utterance: str) -> LLMIntentOutput:
        assert utterance == "조용한 여행지 찾아줘"
        return LLMIntentOutput(
            disposition=ProposalDisposition.PROPOSED,
            interpretations=(
                IntentInterpretation(
                    proposals=(
                        LLMIntentProposal(
                            role=IntentRole.REQUIRED_TARGET,
                            intent=KindIntent(kind=PlaceKind.TRAVEL),
                            evidence=EvidenceQuote(quote="여행지", start=None, end=None),
                        ),
                        LLMIntentProposal(
                            role=IntentRole.PREFERENCE,
                            intent=SemanticIntent(concept_id="semantic.quiet"),
                            evidence=EvidenceQuote(quote="조용한", start=None, end=None),
                        ),
                    )
                ),
            ),
            reason=None,
        )


class _OutputProposer:
    def __init__(self, query: str, output: LLMIntentOutput):
        self._query = query
        self._output = output

    async def propose(self, utterance: str) -> LLMIntentOutput:
        assert utterance == self._query
        return self._output


def _proposal(role: IntentRole, intent, quote: str) -> LLMIntentProposal:
    return LLMIntentProposal(
        role=role,
        intent=intent,
        evidence=EvidenceQuote(quote=quote, start=None, end=None),
    )


def _output(*proposals: LLMIntentProposal) -> LLMIntentOutput:
    return LLMIntentOutput(
        disposition=ProposalDisposition.PROPOSED,
        interpretations=(IntentInterpretation(proposals=proposals),),
        reason=None,
    )


def _ids() -> Iterator[str]:
    for index in range(1, 100):
        yield f"assembly-observation-{index}"


def _place() -> PlaceResult:
    key = PlaceRef(source="kto", ref="K1")
    return PlaceResult(
        key=key,
        name="테스트 여행지",
        lat=37.556,
        lng=126.923,
        distance_m=420,
        match=PlaceMatch(source=key, kind="travel"),
        classifications=[
            PlaceClassification(
                source=key,
                source_category="12",
                kind="travel",
                mapping_version="test-v1",
            )
        ],
        facts=PlaceFacts(address="서울 마포구"),
    )


async def test_discovery_executes_each_lens_and_returns_serializable_presentations() -> None:
    ids = _ids()
    bridge = PlaceIntentCompatibilityBridge(
        PlaceIntentSuggestionService(
            _Proposer(),
            observation_id_factory=lambda: next(ids),
        )
    )
    searched = []

    async def searcher(db, plan):
        del db
        searched.append(plan)
        kind = purpose_kinds(plan)[0]
        return PlaceSearchResponse(
            conditions=plan.conditions,
            groups=[
                PlaceSearchGroup(
                    kind=kind,
                    limit=plan.limit_per_kind,
                    results=[PlaceSearchHit(place=_place())],
                )
            ],
        )

    loaded = []

    async def loader(db, keys):
        del db
        loaded.extend(keys)
        projection = project_kto(
            {"contenttypeid": "12"},
            {"acmpyTypeCd": "전구역 동반가능"},
            detail_state=FactState.KNOWN,
        )
        return [
            build_candidate_fact_bundle(
                key,
                [
                    SourceFactVariant(
                        source_ref=key.source_ref,
                        record_ref="record:1",
                        occurrence_count=1,
                        snapshot="test-snapshot",
                        detail_state=DetailAcquisitionState.FETCHED,
                        projection=projection,
                    )
                ],
            )
            for key in keys
        ]

    service = PlaceDiscoveryAssemblyService(
        bridge,
        searcher=searcher,
        source_fact_loader=loader,
    )
    request = PlaceCapabilityInput(
        query="조용한 여행지 찾아줘",
        spatial=PlaceSpatialConstraint(lat=37.5563, lng=126.9236, radius_m=3_000),
        limit_per_kind=10,
    )

    result = await service.discover(None, request)  # type: ignore[arg-type]
    payload = result.model_dump(mode="json")

    assert len(searched) == 1
    assert loaded == [SourceFactKey(source="kto", source_ref="K1")]
    assert result.contract_version == "place-discovery-v1"
    assert len(result.lens_results) == 1
    lens = result.lens_results[0]
    assert lens.information_needs == (InformationNeedId.AMBIENCE_QUIET,)
    assert lens.presentations[0].place_key == _place().key
    assert "ambience.quiet.unavailable" in {item.code for item in lens.presentations[0].notices}
    assert payload["lens_results"][0]["presentations"][0]["title"] == "테스트 여행지"
    assert "raw" not in payload["planning"]


async def test_non_executable_planning_does_not_touch_search_or_source_facts() -> None:
    class InvalidProposer:
        async def propose(self, utterance: str) -> LLMIntentOutput:
            del utterance
            return LLMIntentOutput(
                disposition=ProposalDisposition.ABSTAINED,
                interpretations=(),
                reason=ProposalReason.INSUFFICIENT_TARGET,
            )

    bridge = PlaceIntentCompatibilityBridge(PlaceIntentSuggestionService(InvalidProposer()))
    calls = []

    async def searcher(db, plan):
        calls.append((db, plan))
        raise AssertionError("search must not run")

    async def loader(db, keys):
        calls.append((db, keys))
        raise AssertionError("source fact load must not run")

    service = PlaceDiscoveryAssemblyService(
        bridge,
        searcher=searcher,
        source_fact_loader=loader,
    )
    request = PlaceCapabilityInput(
        query="모르겠어",
        spatial=PlaceSpatialConstraint(lat=37.5563, lng=126.9236, radius_m=3_000),
        limit_per_kind=10,
    )

    result = await service.discover(None, request)  # type: ignore[arg-type]

    assert not calls
    assert not result.lens_results


@pytest.mark.parametrize(
    ("query", "output", "expected_need", "expected_lenses"),
    [
        (
            "강아지랑 놀고 싶음",
            _output(
                _proposal(
                    IntentRole.GOAL,
                    ActivityIntent(activity_id=ActivityId.PLAY),
                    "놀고 싶음",
                )
            ),
            InformationNeedId.ACTIVITY_PLAY,
            3,
        ),
        (
            "강아지 장난감 사고 싶어",
            _output(
                _proposal(
                    IntentRole.GOAL,
                    ObjectIntent(object_id=SearchObjectId.DOG_TOY),
                    "강아지 장난감",
                ),
                _proposal(
                    IntentRole.GOAL,
                    ActivityIntent(activity_id=ActivityId.BUY),
                    "사고 싶어",
                ),
            ),
            InformationNeedId.PRODUCTS_PURCHASABLE,
            1,
        ),
    ],
)
async def test_composed_meaning_reaches_every_discovery_lens(
    query: str,
    output: LLMIntentOutput,
    expected_need: InformationNeedId,
    expected_lenses: int,
) -> None:
    ids = _ids()
    bridge = PlaceIntentCompatibilityBridge(
        PlaceIntentSuggestionService(
            _OutputProposer(query, output),
            observation_id_factory=lambda: next(ids),
        )
    )

    async def searcher(db, plan):
        del db
        return PlaceSearchResponse(
            conditions=plan.conditions,
            groups=[
                PlaceSearchGroup(
                    kind=purpose_kinds(plan)[0],
                    limit=plan.limit_per_kind,
                    results=[],
                )
            ],
        )

    async def loader(db, keys):
        del db
        assert not keys
        return []

    service = PlaceDiscoveryAssemblyService(
        bridge,
        searcher=searcher,
        source_fact_loader=loader,
    )
    request = PlaceCapabilityInput(
        query=query,
        spatial=PlaceSpatialConstraint(lat=37.5563, lng=126.9236, radius_m=3_000),
        limit_per_kind=10,
    )

    result = await service.discover(None, request)  # type: ignore[arg-type]

    assert len(result.lens_results) == expected_lenses
    assert all(item.information_needs == (expected_need,) for item in result.lens_results)


async def test_aggregate_budget_is_checked_before_any_search() -> None:
    query = "강아지랑 놀고 싶음"
    ids = _ids()
    bridge = PlaceIntentCompatibilityBridge(
        PlaceIntentSuggestionService(
            _OutputProposer(
                query,
                _output(
                    _proposal(
                        IntentRole.GOAL,
                        ActivityIntent(activity_id=ActivityId.PLAY),
                        "놀고 싶음",
                    )
                ),
            ),
            observation_id_factory=lambda: next(ids),
        )
    )
    calls = []

    async def searcher(db, plan):
        calls.append((db, plan))
        raise AssertionError("search must not run above the aggregate budget")

    async def loader(db, keys):
        calls.append((db, keys))
        raise AssertionError("source facts must not load above the aggregate budget")

    service = PlaceDiscoveryAssemblyService(
        bridge,
        searcher=searcher,
        source_fact_loader=loader,
    )
    request = PlaceCapabilityInput(
        query=query,
        spatial=PlaceSpatialConstraint(lat=37.5563, lng=126.9236, radius_m=3_000),
        limit_per_kind=2_000,
    )

    with pytest.raises(ValueError, match="aggregate 5000-result execution budget"):
        await service.discover(None, request)  # type: ignore[arg-type]

    assert not calls
