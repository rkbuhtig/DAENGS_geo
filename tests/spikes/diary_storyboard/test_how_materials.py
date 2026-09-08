"""Visible shape, noise counterexamples, source anchoring and HOW-only boundaries."""

from datetime import datetime, timedelta, timezone

import pytest

from scripts.spikes.diary_storyboard.how_demo import START, route, scenarios
from scripts.spikes.diary_storyboard.how_materials import (
    HowPolicy,
    HowSource,
    build_how,
    query_how,
)


def sample(name):
    return scenarios()[name]["source"]


def of_kind(catalog, kind):
    return [m for m in catalog["materials"] if m["kind"] == kind]


@pytest.mark.parametrize("name,direction,angle", [("right", "right", -90), ("left", "left", 90)])
def test_large_turns_keep_direction_and_observed_anchor(name, direction, angle):
    source = sample(name)
    before = source.model_dump(mode="json")
    turn, = of_kind(build_how(source), "turn")
    assert turn["metrics"]["direction"] == direction
    assert turn["metrics"]["signed_angle_deg"] == pytest.approx(angle, abs=3)
    assert turn["anchor"]["client_seq"] == 18  # actual corner sample at 90 seconds
    assert turn["support"]["from_seq"] < 18 < turn["support"]["to_seq"]
    assert source.model_dump(mode="json") == before


def test_noisy_straight_line_does_not_become_turns():
    catalog = build_how(sample("straight"))
    assert len(of_kind(catalog, "straight_run")) == 1
    assert not of_kind(catalog, "turn") and not of_kind(catalog, "local_stay")
    assert len(catalog["shape_runs"][0]["vertices"]) == 2
    assert catalog["shape_runs"][0]["source_fix_count"] == 25


def test_stationary_jitter_is_one_local_stay_with_no_direction_changes():
    catalog = build_how(sample("stay"))
    stay, = catalog["materials"]
    assert stay["kind"] == "local_stay"
    assert stay["metrics"]["observed_duration_s"] == 90
    assert stay["metrics"]["bounding_diagonal_m"] < 6
    assert stay["subject"] == "recording_device"


def test_stay_and_turn_can_coexist_without_rewriting_stay_as_turn_duration():
    catalog = build_how(sample("pause_turn"))
    stay, = of_kind(catalog, "local_stay")
    turn, = of_kind(catalog, "turn")
    assert stay["metrics"]["observed_duration_s"] >= 60
    assert turn["metrics"]["direction"] == "right"
    assert turn["support"]["time_meaning"] == "observed_support_window"
    assert "duration_s" not in turn["metrics"]


def test_return_on_previous_leg_is_retrace_but_parallel_return_is_not():
    catalog = build_how(sample("out_back"))
    retrace, = of_kind(catalog, "retrace")
    assert not of_kind(catalog, "local_stay")
    assert retrace["metrics"]["return_displacement_m"] == pytest.approx(80, abs=3)
    assert retrace["metrics"]["previous_to_seq"] == retrace["support"]["from_seq"]
    assert not of_kind(build_how(sample("parallel")), "retrace")


@pytest.mark.parametrize("name", ["short", "shallow"])
def test_small_or_shallow_bends_are_not_visible_turns(name):
    assert not of_kind(build_how(sample(name)), "turn")


def test_gap_at_corner_is_not_a_turn_or_a_stay_and_queries_cannot_cross_chain():
    catalog = build_how(sample("gap"))
    assert catalog["canonical_quality"]["gap_breaks"] == 1
    assert not of_kind(catalog, "turn") and not of_kind(catalog, "local_stay")
    assert {m["support"]["chain_index"] for m in catalog["materials"]} == {0, 1}
    found = query_how(catalog, at=START + timedelta(seconds=300), chain_index=1, lookback_s=400)
    assert found and all(m["support"]["chain_index"] == 1 for m in found)


@pytest.mark.parametrize("accuracy,canonical_rejections", [(30, 0), (80, 1)])
def test_accuracy_rejection_splits_support_instead_of_drawing_through_corner(
    accuracy, canonical_rejections
):
    source = sample("right")
    fixes = list(source.fixes)
    fixes[18] = fixes[18].model_copy(update={"accuracy_m": accuracy})
    catalog = build_how(source.model_copy(update={"fixes": tuple(fixes)}))
    assert catalog["canonical_quality"]["rejected_low_accuracy"] == canonical_rejections
    assert not of_kind(catalog, "turn")
    if accuracy == 30:
        assert len(catalog["quality_audit"]) == 2
        assert {r["reason"] for r in catalog["quality_audit"]} == {"how_accuracy_rejection"}


def test_sub_jump_threshold_spike_is_rejected_by_how_speed_gate():
    source = sample("straight")
    fixes = list(source.fixes)
    fixes[12] = fixes[12].model_copy(update={"lat": fixes[12].lat + 0.001})
    catalog = build_how(source.model_copy(update={"fixes": tuple(fixes)}))
    assert catalog["canonical_quality"]["jump_breaks"] == 0
    assert {r["reason"] for r in catalog["quality_audit"]} == {"how_speed_rejection"}
    assert not of_kind(catalog, "turn")


def test_candidate_becomes_available_after_support_not_at_the_turn_anchor():
    catalog = build_how(sample("right"))
    early = query_how(catalog, at=START + timedelta(seconds=95), chain_index=0, lookback_s=200)
    late = query_how(catalog, at=START + timedelta(seconds=180), chain_index=0, lookback_s=200)
    assert not of_kind({"materials": early}, "turn")
    assert len(of_kind({"materials": late}, "turn")) == 1
    assert all("anchor" not in m for m in late)
    assert not query_how(catalog, at=START + timedelta(seconds=400), chain_index=0, lookback_s=10)


def test_sample_rate_change_does_not_change_clean_corner_direction():
    for step in (3, 5, 10):
        source = route("resample", [(0, 0, 0), (90, 0, 90), (180, 90, 90)], step_s=step)
        turn, = of_kind(build_how(source), "turn")
        assert turn["metrics"]["signed_angle_deg"] == pytest.approx(-90, abs=0.1)


def test_policy_versions_and_source_change_candidate_references():
    source = sample("right")
    a, b = build_how(source), build_how(source, HowPolicy(simplify_m=9))
    assert a == build_how(HowSource.model_validate_json(source.model_dump_json()))
    assert a["source_sha256"] == b["source_sha256"]
    assert {m["ref"]["version"] for m in a["materials"]}.isdisjoint(
        m["ref"]["version"] for m in b["materials"]
    )
    assert a["evidence_origin"] == "mock"


def test_all_output_spans_and_anchors_resolve_to_source_without_where_or_purpose():
    for case in scenarios().values():
        source = case["source"]
        fixes = {p.client_seq: p for p in source.fixes}
        catalog = build_how(source)
        for m in catalog["materials"]:
            support, anchor = m["support"], m["anchor"]
            point = fixes[anchor["client_seq"]]
            assert support["from_seq"] <= anchor["client_seq"] <= support["to_seq"]
            assert datetime.fromisoformat(anchor["at"]) == point.at
            assert (anchor["lat"], anchor["lng"]) == (point.lat, point.lng)
            assert datetime.fromisoformat(support["started_at"]) == fixes[support["from_seq"]].at
            assert datetime.fromisoformat(support["ended_at"]) == fixes[support["to_seq"]].at
            assert m["axis"] == "how" and "where" not in m and "purpose" not in m


def test_mixed_timezone_spellings_keep_chronological_support():
    source = sample("right")
    fixes = tuple(p.model_copy(update={"at": p.at.astimezone(timezone(timedelta(hours=9)))})
                  if i % 2 else p for i, p in enumerate(source.fixes))
    baseline = build_how(source)
    mixed = build_how(source.model_copy(update={"fixes": fixes}))
    assert [(m["kind"], m["anchor"]["at"]) for m in baseline["materials"]] == [
        (m["kind"], m["anchor"]["at"]) for m in mixed["materials"]
    ]


def test_empty_source_and_invalid_input_contracts():
    source = sample("right").model_dump(mode="json")
    source["fixes"] = []
    assert build_how(source)["materials"] == []
    source["where"] = {"park": True}
    with pytest.raises(ValueError):
        build_how(source)
    with pytest.raises(ValueError):
        HowPolicy(turn_min_deg=160, reversal_min_deg=150)
    with pytest.raises(ValueError):
        naive = datetime(2026, 1, 1)  # noqa: DTZ001 -- intentional invalid boundary input
        query_how({"materials": []}, at=naive, chain_index=0)
