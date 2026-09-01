import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.discovery.place_intent.contract import ProposalDisposition, ProposalReason
from app.discovery.place_intent.lab import (
    CandidateExecution,
    PlaceIntentConfirmationRequest,
    _attempt_outcome,
    _attempt_snapshot,
    _ConfirmationStore,
    _InteractionStore,
    _limit_search_preview,
    _response_mode,
)
from app.discovery.place_intent.lenses import TargetSearchLens
from app.discovery.place_intent.observability import AttemptStatus, SearchResponseMode
from app.discovery.place_intent.suggestions import SuggestionResolution
from app.place.planning.contract import PlaceKind
from app.place.planning.intents import PlannerStatus
from app.place.search import PlaceSearchGroup, PlaceSearchResponse

ROOT = Path(__file__).resolve().parents[3]
HTML = (ROOT / "app" / "static" / "place_intent_lab.html").read_text(encoding="utf-8")


def test_intent_lab_shows_model_policy_and_real_search_layers() -> None:
    assert "AI의 여러 검색 방향을 실제 DB에서 본다" in HTML
    assert "/dev/place-intent/search" in HTML
    assert "Model interpretation" in HTML
    assert "Preserved signals" in HTML
    assert "Search lenses" in HTML
    assert "gate preview" in HTML
    assert "place.name" in HTML
    assert "preview_per_lens" in HTML
    assert "data.trace.lenses.target_lenses" in HTML
    assert "signal.required ? 'required' : 'optional'" in HTML
    assert "/dev/place-intent/confirm" in HTML
    assert "/dev/place-intent/refine" in HTML
    assert "/dev/place-intent/interact" in HTML
    assert "/dev/place-intent/observations" in HTML
    assert "이 검색 방향을 명시적으로 확인" in HTML
    assert "처음부터 다시" in HTML
    assert "Operator observations" in HTML
    assert "response · " in HTML
    assert "proposer " in HTML
    assert "fallback " in HTML
    assert "탭이나 장소 마커를 누르는 것은 확인이 아닙니다." in HTML
    assert "실행 가능한 lens가 없어 지도에 표시할 장소가 없습니다." in HTML


def test_intent_lab_limits_each_lens_preview_across_groups() -> None:
    search = PlaceSearchResponse.model_construct(
        conditions=None,
        groups=[
            PlaceSearchGroup.model_construct(
                kind=PlaceKind.CAFE,
                limit=3,
                truncated=False,
                results=["cafe-1", "cafe-2"],
            ),
            PlaceSearchGroup.model_construct(
                kind=PlaceKind.RESTAURANT,
                limit=3,
                truncated=False,
                results=["restaurant-1", "restaurant-2"],
            ),
        ],
    )

    limited = _limit_search_preview(search, 3)

    assert [group.results for group in limited.groups] == [
        ["cafe-1", "cafe-2"],
        ["restaurant-1"],
    ]
    assert [group.truncated for group in limited.groups] == [False, True]


def test_attempt_failure_distinguishes_spatial_empty_from_gate_elimination() -> None:
    trace = cast(object, SimpleNamespace(raw=object()))
    spatial_empty = cast(
        CandidateExecution,
        SimpleNamespace(
            search=SimpleNamespace(groups=[]),
            preview=SimpleNamespace(initial_candidates=0, gates=()),
        ),
    )
    gate_empty = cast(
        CandidateExecution,
        SimpleNamespace(
            search=SimpleNamespace(groups=[]),
            preview=SimpleNamespace(
                initial_candidates=8,
                gates=(SimpleNamespace(remaining=0),),
            ),
        ),
    )

    assert _attempt_outcome(trace, (spatial_empty,)) == (
        AttemptStatus.NEEDS_CLARIFICATION,
        "spatial_candidates_empty",
    )
    assert _attempt_outcome(trace, (gate_empty,)) == (
        AttemptStatus.NEEDS_CLARIFICATION,
        "gate_eliminated_all",
    )


def test_attempt_observation_separates_proposer_reason_from_product_outcome() -> None:
    trace = cast(
        object,
        SimpleNamespace(
            raw=SimpleNamespace(
                disposition=ProposalDisposition.ABSTAINED,
                reason=ProposalReason.INSUFFICIENT_TARGET,
            ),
            outcome=SimpleNamespace(
                status=PlannerStatus.NEEDS_CLARIFICATION,
                resolution=None,
                issues=(),
            ),
            lenses=None,
        ),
    )

    response_mode = _response_mode(trace, AttemptStatus.NEEDS_CLARIFICATION)
    snapshot = _attempt_snapshot(
        trace,
        (),
        response_mode=response_mode,
        failure_code="no_executable_lens",
    )

    assert response_mode is SearchResponseMode.CLARIFICATION
    assert snapshot["proposer"] == {
        "disposition": "abstained",
        "reason": "insufficient_target",
    }
    assert snapshot["product_outcome"] == {
        "response_mode": "clarification",
        "failure_code": "no_executable_lens",
    }
    assert snapshot["fallback_policy"] is None


def test_completed_exploratory_search_has_distinct_response_mode() -> None:
    trace = cast(
        object,
        SimpleNamespace(
            outcome=SimpleNamespace(
                status=PlannerStatus.READY,
                resolution=SuggestionResolution.EXPLORATORY,
            )
        ),
    )

    assert _response_mode(trace, AttemptStatus.COMPLETED) is SearchResponseMode.EXPLORATORY_RESULTS


def test_confirmation_offer_is_lens_bound_expiring_and_single_use() -> None:
    now = [10.0]
    tokens = iter(("a" * 24, "b" * 24))
    store = _ConfirmationStore(
        ttl_s=5,
        max_entries=2,
        clock=lambda: now[0],
        token_factory=lambda: next(tokens),
    )
    lens = cast(TargetSearchLens, SimpleNamespace(lens_id="lens:one"))
    search_id = uuid4()

    token = store.issue(lens, search_id)

    with pytest.raises(ValueError, match="does not match"):
        store.consume(token, "lens:other")
    pending = store.consume(token, "lens:one")
    assert pending.lens is lens
    assert pending.search_id == search_id
    with pytest.raises(KeyError, match="missing or expired"):
        store.consume(token, "lens:one")

    expired = store.issue(lens, search_id)
    now[0] = 16.0
    with pytest.raises(KeyError, match="missing or expired"):
        store.consume(expired, "lens:one")


def test_interaction_offer_is_search_bound_and_reusable_until_expiry() -> None:
    now = [10.0]
    store = _InteractionStore(
        ttl_s=5,
        max_entries=2,
        clock=lambda: now[0],
        token_factory=lambda: "a" * 24,
    )
    search_id = uuid4()
    trace = cast(object, SimpleNamespace())
    token = store.issue(
        search_id=search_id,
        utterance="조용한 곳",
        trace=trace,
        preview_per_lens=3,
        lat=37.5,
        lng=126.9,
        radius_m=3000,
    )

    assert store.get(token, search_id).utterance == "조용한 곳"
    assert store.get(token, search_id).search_id == search_id
    with pytest.raises(ValueError, match="does not match"):
        store.get(token, uuid4())
    now[0] = 16.0
    with pytest.raises(KeyError, match="missing or expired"):
        store.get(token, search_id)


def test_confirmation_request_cannot_supply_or_forge_target_intents() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PlaceIntentConfirmationRequest.model_validate(
            {
                "lens_id": "lens:one",
                "confirmation_token": "a" * 24,
                "confirmable_targets": [{"intent_type": "kind", "kind": "hospital"}],
            }
        )


def test_intent_lab_renders_provider_text_without_html_injection() -> None:
    assert "name.textContent = place.name" in HTML
    assert "quote.textContent" in HTML
    assert "introNote.textContent = lens.support_note" in HTML
    assert "innerHTML = place.name" not in HTML


def test_intent_lab_renders_invalid_model_output_as_a_typed_empty_state() -> None:
    assert "if (!trace.raw)" in HTML
    assert "modelState = raw ? raw.disposition : 'invalid_output'" in HTML
    assert "data.trace.raw ? data.trace.raw.interpretations.length : 0" in HTML


def _paths_with_dev_console(enabled: bool) -> set[str]:
    environment = os.environ.copy()
    environment["DAENGS_DEV_CONSOLE"] = "true" if enabled else "false"
    command = """
from app.main import app

def collect_paths(routes):
    paths = []
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.append(path)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.extend(collect_paths(original_router.routes))
    return paths

print("\\n".join(sorted(collect_paths(app.routes))))
"""
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def test_intent_lab_routes_are_behind_dev_console_gate() -> None:
    paths = {
        "/place-intent-lab",
        "/dev/place-intent/search",
        "/dev/place-intent/confirm",
        "/dev/place-intent/refine",
        "/dev/place-intent/interact",
        "/dev/place-intent/observations",
    }
    assert paths.isdisjoint(_paths_with_dev_console(False))
    assert paths <= _paths_with_dev_console(True)
