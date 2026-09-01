from collections.abc import Iterator

from app.discovery.place_intent.contract import (
    EvidenceQuote,
    IntentInterpretation,
    LLMIntentOutput,
    LLMIntentProposal,
    ProposalDisposition,
    materialize_llm_output,
)
from app.discovery.place_intent.hypotheses import build_search_hypotheses
from app.discovery.place_intent.lenses import (
    FacetOptionAvailability,
    LensAvailability,
    LensMappingScope,
    LensType,
    compile_search_lenses,
)
from app.discovery.place_intent.suggestions import compile_intent_suggestions
from app.place.planning.contract import CapabilityId, PlaceKind
from app.place.planning.intents import (
    ActivityId,
    ActivityIntent,
    BooleanCapabilityIntent,
    IntentRole,
    KindIntent,
    ObjectIntent,
    PlannerStatus,
    SearchObjectId,
    SemanticIntent,
)

_SPATIAL = {"lat": 37.5563, "lng": 126.9236, "radius_m": 3000}


def _ids() -> Iterator[str]:
    index = 0
    while True:
        index += 1
        yield f"lens-source-{index}"


def _proposal(role: IntentRole, intent, quote: str) -> LLMIntentProposal:
    return LLMIntentProposal(
        role=role,
        intent=intent,
        evidence=EvidenceQuote(quote=quote, start=None, end=None),
    )


def _compile(utterance: str, *proposals: LLMIntentProposal):
    ids = _ids()
    grounded = materialize_llm_output(
        utterance,
        LLMIntentOutput(
            disposition=ProposalDisposition.PROPOSED,
            interpretations=(IntentInterpretation(proposals=proposals),),
            reason=None,
        ),
        id_factory=lambda: next(ids),
    )
    normalized = build_search_hypotheses(grounded)
    suggestions = compile_intent_suggestions(
        grounded,
        spatial=_SPATIAL,
        limit_per_kind=3,
    )
    return compile_search_lenses(
        normalized,
        suggestions,
        spatial=_SPATIAL,
        limit_per_kind=3,
    )


def test_play_hypotheses_become_three_executable_broad_lenses() -> None:
    lenses = _compile(
        "강아지랑 놀고 싶음",
        _proposal(
            IntentRole.GOAL,
            ActivityIntent(activity_id=ActivityId.PLAY),
            "놀고 싶음",
        ),
    )

    assert [item.display_label for item in lenses.target_lenses] == [
        "#놀기",
        "#산책·야외",
        "#같이 쉬기",
    ]
    assert all(item.mapping_scope is LensMappingScope.BROAD for item in lenses.target_lenses)
    assert all(item.availability is LensAvailability.EXECUTABLE for item in lenses.target_lenses)
    assert all(item.candidate.result.status is PlannerStatus.READY for item in lenses.target_lenses)
    assert lenses.executable_targets == lenses.target_lenses


def test_buying_dog_toy_exposes_pet_shop_without_inventory_overclaim() -> None:
    lenses = _compile(
        "강아지 장난감 사고 싶어 펫샵",
        _proposal(
            IntentRole.GOAL,
            ActivityIntent(activity_id=ActivityId.BUY),
            "사고 싶어",
        ),
        _proposal(
            IntentRole.GOAL,
            ObjectIntent(object_id=SearchObjectId.DOG_TOY),
            "강아지 장난감",
        ),
        _proposal(
            IntentRole.REQUIRED_TARGET,
            KindIntent(kind=PlaceKind.PET_SHOP),
            "펫샵",
        ),
    )

    assert len(lenses.target_lenses) == 1
    lens = lenses.target_lenses[0]
    assert lens.display_label == "#펫샵"
    assert lens.mapping_scope is LensMappingScope.DIRECT
    assert lens.confirmable_targets == (KindIntent(kind=PlaceKind.PET_SHOP),)
    assert "판매·재고는 보장하지 않습니다" in lens.support_note


def test_quiet_fallbacks_are_executable_but_disclose_missing_ranking() -> None:
    lenses = _compile(
        "조용한 곳",
        _proposal(
            IntentRole.REQUIRED_CONDITION,
            SemanticIntent(concept_id="semantic.quiet"),
            "조용한 곳",
        ),
    )

    assert [item.display_label for item in lenses.target_lenses] == [
        "#식사·카페",
        "#나들이",
        "#문화공간",
    ]
    assert all(
        item.mapping_scope is LensMappingScope.PRODUCT_FALLBACK for item in lenses.target_lenses
    )
    assert all(item.availability is LensAvailability.EXECUTABLE for item in lenses.target_lenses)
    assert all(
        "조용함을 확인한 결과가 아니라" in item.support_note for item in lenses.target_lenses
    )
    signal = lenses.signal_lenses[0]
    assert signal.lens_type is LensType.MODIFIER
    assert signal.display_label == "#조용한 분위기"
    assert signal.availability is LensAvailability.DEFERRED


def test_cheap_becomes_a_non_executing_cost_question_with_honest_options() -> None:
    lenses = _compile(
        "싸게 갈 수 있는 곳",
        _proposal(
            IntentRole.REQUIRED_CONDITION,
            SemanticIntent(concept_id="semantic.cheap"),
            "싸게 갈 수 있는 곳",
        ),
    )

    assert not lenses.target_lenses
    signal = lenses.signal_lenses[0]
    assert signal.lens_type is LensType.UNRESOLVED
    assert signal.availability is LensAvailability.NEEDS_SELECTION
    assert [item.display_label for item in signal.options] == [
        "가까운 곳",
        "반려견 추가요금",
        "입장료",
        "물건값",
    ]
    assert signal.options[0].availability is FacetOptionAvailability.PROXY
    assert all(
        item.availability is FacetOptionAvailability.UNAVAILABLE for item in signal.options[1:]
    )


def test_blocking_cost_facet_prevents_an_otherwise_ready_target_from_execution() -> None:
    lenses = _compile(
        "싼 카페",
        _proposal(
            IntentRole.REQUIRED_TARGET,
            KindIntent(kind=PlaceKind.CAFE),
            "카페",
        ),
        _proposal(
            IntentRole.REQUIRED_CONDITION,
            SemanticIntent(concept_id="semantic.cheap"),
            "싼",
        ),
    )

    lens = lenses.target_lenses[0]
    assert lens.candidate.result.status is PlannerStatus.READY
    assert lens.availability is LensAvailability.NEEDS_SELECTION
    assert lens.unresolved_facet_ids == ("cost.dimension",)
    assert not lenses.executable_targets


def test_common_hard_condition_blocks_every_expanded_play_lens() -> None:
    lenses = _compile(
        "놀고 싶고 주차는 꼭 돼야 해",
        _proposal(
            IntentRole.GOAL,
            ActivityIntent(activity_id=ActivityId.PLAY),
            "놀고 싶고",
        ),
        _proposal(
            IntentRole.REQUIRED_CONDITION,
            BooleanCapabilityIntent(
                capability_id=CapabilityId.OPERATIONS_PARKING,
                value=True,
            ),
            "주차는 꼭 돼야 해",
        ),
    )

    assert len(lenses.target_lenses) == 3
    assert all(item.availability is LensAvailability.BLOCKED for item in lenses.target_lenses)
    assert all(
        "unsupported_capability_strength" in item.unsupported_signals
        for item in lenses.target_lenses
    )
    assert not lenses.executable_targets
