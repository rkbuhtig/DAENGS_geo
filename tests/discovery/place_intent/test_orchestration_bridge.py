import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.discovery.place_intent.contract import (
    EvidenceQuote,
    IntentInterpretation,
    IntentProposerInvalidOutputError,
    LLMIntentOutput,
    LLMIntentProposal,
    LLMSearchDirective,
    ProposalDisposition,
    ProposalReason,
    SearchModeId,
)
from app.discovery.place_intent.lenses import LensAvailability, LensMappingScope
from app.discovery.place_intent.orchestration_bridge import (
    PlaceCapabilityInput,
    PlaceIntentCompatibilityBridge,
)
from app.discovery.place_intent.service import PlaceIntentSuggestionService
from app.discovery.place_intent.suggestions import SuggestionResolution
from app.place.planning.contract import PlaceKind, PlaceSearchConditions, PlaceSpatialConstraint
from app.place.planning.intents import IntentRole, KindIntent, PlannerStatus

_SPATIAL = PlaceSpatialConstraint(lat=37.5563, lng=126.9236, radius_m=3_000)


class _OutputProposer:
    def __init__(self, output: LLMIntentOutput):
        self._output = output
        self.utterances: list[str] = []

    async def propose(self, utterance: str) -> LLMIntentOutput:
        self.utterances.append(utterance)
        return self._output


class _InvalidOutputProposer:
    async def propose(self, utterance: str) -> LLMIntentOutput:
        del utterance
        raise IntentProposerInvalidOutputError(
            "provider schema failure",
            raw_output="sensitive provider output",
        )


def _proposal(role: IntentRole, intent, quote: str) -> LLMIntentProposal:
    return LLMIntentProposal(
        role=role,
        intent=intent,
        evidence=EvidenceQuote(quote=quote, start=None, end=None),
    )


def _bridge(output: LLMIntentOutput) -> PlaceIntentCompatibilityBridge:
    return PlaceIntentCompatibilityBridge(
        PlaceIntentSuggestionService(
            _OutputProposer(output),
            observation_id_factory=iter(
                f"bridge-observation-{index}" for index in range(1, 100)
            ).__next__,
        )
    )


def test_capability_input_rejects_blank_but_preserves_the_original_query() -> None:
    request = PlaceCapabilityInput(
        query="  조용한 곳  ",
        spatial=_SPATIAL,
        limit_per_kind=20,
    )

    assert request.query == "  조용한 곳  "

    with pytest.raises(ValidationError, match="query must not be blank"):
        PlaceCapabilityInput(query="   ", spatial=_SPATIAL, limit_per_kind=20)


def test_capability_input_accepts_values_not_dog_identity() -> None:
    conditions = PlaceSearchConditions(
        dog_size="small",
        dog_weight_kg=4.2,
        dog_age_years=3,
    )
    request = PlaceCapabilityInput(
        query="강아지와 갈 카페",
        spatial=_SPATIAL,
        limit_per_kind=20,
        conditions=conditions,
    )

    assert request.conditions == conditions
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PlaceCapabilityInput.model_validate(
            {
                "query": "강아지와 갈 카페",
                "spatial": _SPATIAL.model_dump(),
                "limit_per_kind": 20,
                "dog_id": "dog-123",
            }
        )


@pytest.mark.asyncio
async def test_bridge_preserves_trusted_spatial_and_conditions_in_the_plan() -> None:
    output = LLMIntentOutput(
        disposition=ProposalDisposition.PROPOSED,
        interpretations=(
            IntentInterpretation(
                proposals=(
                    _proposal(
                        IntentRole.REQUIRED_TARGET,
                        KindIntent(kind=PlaceKind.CAFE),
                        "카페",
                    ),
                )
            ),
        ),
        reason=None,
    )
    conditions = PlaceSearchConditions(dog_size="small")
    request = PlaceCapabilityInput(
        query="  카페 찾아줘  ",
        spatial=_SPATIAL,
        limit_per_kind=20,
        conditions=conditions,
    )

    proposer = _OutputProposer(output)
    bridge = PlaceIntentCompatibilityBridge(
        PlaceIntentSuggestionService(
            proposer,
            observation_id_factory=iter(
                f"bridge-observation-{index}" for index in range(1, 100)
            ).__next__,
        )
    )

    data = await bridge.plan(request)

    assert data.status is PlannerStatus.READY
    assert proposer.utterances == [request.query]
    assert data.contract_version == "place-discovery-planning-v1"
    assert len(data.lenses.target_lenses) == 1
    target = data.lenses.target_lenses[0]
    assert target.availability is LensAvailability.EXECUTABLE
    assert target.candidate.result.plan is not None
    assert target.candidate.result.plan.spatial == _SPATIAL
    assert target.candidate.result.plan.conditions == conditions


@pytest.mark.asyncio
async def test_open_discovery_returns_three_lenses_without_choosing_one() -> None:
    output = LLMIntentOutput(
        disposition=ProposalDisposition.PROPOSED,
        interpretations=(
            IntentInterpretation(
                search_directive=LLMSearchDirective(
                    mode=SearchModeId.OPEN_DISCOVERY,
                    evidence=EvidenceQuote(
                        quote="네가 추천해봐",
                        start=None,
                        end=None,
                    ),
                ),
                proposals=(),
            ),
        ),
        reason=None,
    )
    request = PlaceCapabilityInput(
        query="오늘 심심한데 네가 추천해봐",
        spatial=_SPATIAL,
        limit_per_kind=20,
    )

    data = await _bridge(output).plan(request)

    assert data.status is PlannerStatus.READY
    assert [item.display_label for item in data.lenses.target_lenses] == [
        "#먹고 쉬기",
        "#가볍게 나가기",
        "#구경하기",
    ]
    assert all(
        item.mapping_scope is LensMappingScope.OPEN_DISCOVERY for item in data.lenses.target_lenses
    )
    assert len(data.lenses.executable_targets) == 3


@pytest.mark.asyncio
async def test_ambiguous_interpretations_remain_separate_exploratory_lenses() -> None:
    output = LLMIntentOutput(
        disposition=ProposalDisposition.AMBIGUOUS,
        interpretations=(
            IntentInterpretation(
                proposals=(
                    _proposal(
                        IntentRole.REQUIRED_TARGET,
                        KindIntent(kind=PlaceKind.CAFE),
                        "카페",
                    ),
                )
            ),
            IntentInterpretation(
                proposals=(
                    _proposal(
                        IntentRole.REQUIRED_TARGET,
                        KindIntent(kind=PlaceKind.PET_SHOP),
                        "펫샵",
                    ),
                )
            ),
        ),
        reason=ProposalReason.MULTIPLE_PLAUSIBLE_READINGS,
    )
    request = PlaceCapabilityInput(
        query="카페 아니면 펫샵",
        spatial=_SPATIAL,
        limit_per_kind=20,
    )

    data = await _bridge(output).plan(request)

    assert data.status is PlannerStatus.READY
    assert data.source_disposition is ProposalDisposition.AMBIGUOUS
    assert data.resolution is SuggestionResolution.EXPLORATORY
    assert [item.display_label for item in data.lenses.target_lenses] == ["#카페", "#펫샵"]
    assert len(data.lenses.executable_targets) == 2


@pytest.mark.asyncio
async def test_invalid_provider_output_becomes_public_issue_without_leaking_raw_output() -> None:
    bridge = PlaceIntentCompatibilityBridge(PlaceIntentSuggestionService(_InvalidOutputProposer()))
    request = PlaceCapabilityInput(
        query="강아지가 좋아하는 곳",
        spatial=_SPATIAL,
        limit_per_kind=20,
    )

    data = await bridge.plan(request)
    payload = data.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False)

    assert data.status is PlannerStatus.NEEDS_CLARIFICATION
    assert data.source_disposition is None
    assert not data.lenses.target_lenses
    assert not data.lenses.signal_lenses
    assert [issue.code for issue in data.issues] == ["intent_proposer_invalid_output"]
    assert "provider schema failure" not in encoded
    assert "sensitive provider output" not in encoded
    assert set(payload) == {
        "contract_version",
        "status",
        "source_disposition",
        "resolution",
        "lenses",
        "issues",
        "rejected_candidate_count",
    }


def test_bridge_does_not_import_the_operational_orchestration_contracts() -> None:
    source_path = (
        Path(__file__).parents[3] / "app" / "discovery" / "place_intent" / "orchestration_bridge.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    assert not {name for name in imports if name.startswith(("daengs_backend", "langgraph"))}
