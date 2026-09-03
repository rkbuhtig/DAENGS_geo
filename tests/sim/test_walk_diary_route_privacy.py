"""WalkDiaryRoute 저장 후보의 노출·단절·충실도 실험."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from app.geo.cells import EARTH_R
from scripts.spikes.walk_diary_route import projector as diary_route
from scripts.spikes.walk_diary_route.projector import (
    EXPERIMENT_PROFILES,
    DiaryRouteProfile,
    build_diary_route_experiment,
    project_candidate,
)

START = datetime(2026, 9, 3, 8, tzinfo=UTC)
ORIGIN_LAT = 37.5
ORIGIN_LNG = 127.0


def _fix(index: int, east_m: float, north_m: float, *, chain_index: int = 0) -> WalkFix:
    return WalkFix(
        client_seq=index,
        chain_index=chain_index,
        at=START + timedelta(seconds=index * 20),
        lat=ORIGIN_LAT + north_m / EARTH_R * 180 / math.pi,
        lng=ORIGIN_LNG
        + east_m / (EARTH_R * math.cos(math.radians(ORIGIN_LAT)))
        * 180
        / math.pi,
        accuracy_m=3,
    )


def _trail(points: list[tuple[float, float, int]]):
    fixes = [
        _fix(index, east, north, chain_index=chain)
        for index, (east, north, chain) in enumerate(points)
    ]
    computed = compute_facts("privacy-route", "dog-1", START, fixes[-1].at, fixes)
    return computed.trail, computed.facts.started_at


def _profile(profile_id: str):
    return next(profile for profile in EXPERIMENT_PROFILES if profile.id == profile_id)


def test_path_distance_trim_still_exposes_a_later_home_revisit():
    trail, started_at = _trail(
        [(0, 0, 0), (120, 0, 0), (0, 0, 0), (0, 120, 0)]
    )

    candidate = project_candidate(trail, started_at, _profile("trim-60m"))

    assert candidate["status"] == "available"
    assert candidate["metrics"]["nearest_geometry_to_start_m"] < 1


def test_spatial_endpoint_mask_clips_every_revisit_and_splits_the_visible_route():
    trail, started_at = _trail(
        [(0, 0, 0), (120, 0, 0), (0, 0, 0), (0, 120, 0)]
    )

    candidate = project_candidate(trail, started_at, _profile("zone-60m-q5-s5"))

    assert candidate["status"] == "available"
    assert candidate["metrics"]["nearest_geometry_to_start_m"] >= 59.99
    assert candidate["metrics"]["visible_fragment_count"] >= 2


def test_canonical_chain_break_is_never_reconnected_by_the_diary_candidate():
    trail, started_at = _trail(
        [(0, 0, 0), (80, 0, 0), (80, 80, 1), (160, 80, 1)]
    )

    candidate = project_candidate(trail, started_at, _profile("canonical-detail"))

    assert len(candidate["fragments"]) == 2
    assert [fragment["source_chain_index"] for fragment in candidate["fragments"]] == [0, 1]


def test_path_trim_consumes_the_requested_distance_across_canonical_fragments():
    trail, started_at = _trail(
        [(0, 0, 0), (40, 0, 0), (50, 0, 1), (150, 0, 1), (250, 0, 1)]
    )

    candidate = project_candidate(trail, started_at, _profile("trim-60m"))

    first_point = candidate["fragments"][0]["points"][0]
    assert first_point["lng"] > _fix(0, 59, 0).lng


def test_simplification_keeps_collinear_speed_band_transitions():
    trail, started_at = _trail(
        [(0, 0, 0), (10, 0, 0), (30, 0, 0), (70, 0, 0), (110, 0, 0),
         (130, 0, 0), (140, 0, 0)]
    )
    profile = DiaryRouteProfile("speed-transition", "none", 0, 0, 5)

    candidate = project_candidate(trail, started_at, profile)
    bands = candidate["fragments"][0]["speed_bands"]

    assert {"relative_slow", "relative_mid", "relative_fast"} <= set(bands)
    assert candidate["metrics"]["speed_band_change_count"] >= 2
    assert candidate["metrics"]["output_vertex_count"] > 2


def test_unavailable_route_has_no_fabricated_zero_fidelity():
    trail, started_at = _trail([(0, 0, 0), (80, 0, 0)])

    candidate = project_candidate(trail, started_at, _profile("zone-60m-q5-s5"))

    assert candidate["status"] == "unavailable"
    assert candidate["metrics"]["fidelity_sample_count"] == 0
    assert candidate["metrics"]["fidelity_p95_m"] is None
    assert candidate["metrics"]["fidelity_max_m"] is None


def test_candidate_distinguishes_canonical_breaks_from_endpoint_redaction():
    trail, started_at = _trail(
        [(0, 0, 0), (80, 0, 0), (80, 80, 1), (160, 80, 1)]
    )

    candidate = project_candidate(trail, started_at, _profile("zone-60m-q5-s5"))

    assert {gap["kind"] for gap in candidate["gaps"]} == {
        "canonical_chain_break",
        "endpoint_redaction",
    }


def test_exact_privacy_intersections_are_declared_quantization_exceptions():
    trail, started_at = _trail([(0, 0, 0), (100, 100, 0), (200, 100, 0)])

    candidate = project_candidate(trail, started_at, _profile("zone-60m-q5-s5"))

    assert candidate["profile"]["quantization_scope"] == (
        "interior_vertices_except_exact_privacy_intersections"
    )
    assert candidate["metrics"]["off_grid_privacy_boundary_vertex_count"] > 0


def test_fidelity_mapping_does_not_rescan_the_whole_route_for_every_point(monkeypatch):
    trail, started_at = _trail([(float(index), 0, 0) for index in range(200)])
    calls = 0
    original = diary_route._point_segment_distance

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(diary_route, "_point_segment_distance", counted)

    project_candidate(trail, started_at, _profile("canonical-detail"))

    assert calls < len(trail.segments) * 4


def test_experiment_payload_is_explicitly_non_persistent_and_json_safe():
    trail, started_at = _trail([(0, 0, 0), (80, 0, 0), (120, 50, 0)])

    experiment = build_diary_route_experiment(trail, started_at)

    assert experiment["format"] == "walk-diary-route-experiment-v1"
    assert experiment["semantics"]["persistence"] == "forbidden_experiment_only"
    assert [candidate["profile"]["id"] for candidate in experiment["candidates"]] == [
        profile.id for profile in EXPERIMENT_PROFILES
    ]
    json.dumps(experiment, ensure_ascii=False, allow_nan=False)
