"""Observed-data calculations, history selection and source projection, without a live model."""

import copy
import json
import math

import pytest

from scripts.spikes.diary_storyboard.acquire import DEFAULT_RECIPE, generate_observations
from scripts.spikes.diary_storyboard.cached_environment import project_snapshots
from scripts.spikes.diary_storyboard.geo_adapter import QueryPolicy, build_evidence, measure
from scripts.spikes.diary_storyboard.storage import read


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    recipe = read(DEFAULT_RECIPE)
    for group, count in zip(recipe["history_groups"], (2, 1, 1), strict=True):
        group["count"] = count
    current, history, pins = generate_observations(
        recipe, tmp_path_factory.mktemp("diary-observed")
    )
    return current, history, pins, QueryPolicy.model_validate(recipe["query_policy"])


def spatial(evidence, anchor):
    return next(p for p in evidence.pieces if p.id == "spatial-" + anchor)


def test_computed_mass_and_once_per_walk_appearance(corpus):
    current, history, pins, policy = corpus
    evidence, audit = build_evidence(current, history, pins, policy, [])
    reading = spatial(evidence, "pin-01")
    assert reading.value["selected_walks"] == 4
    assert reading.value["appeared_walks"] == 3
    assert len(reading.value["current_observed_passages"]) == 2
    for receipt in audit["history_receipts"]:
        assert receipt["occupancy_mass_s"] == pytest.approx(receipt["canonical_segment_s"])
    for result in audit["spatial_readings"]:
        contributions = result["contributions"]
        assert len(contributions) == 4
        assert result["value"]["appeared_walks"] == sum(c["appeared"] for c in contributions)
        assert result["value"]["occupancy_mass_s"] == pytest.approx(
            math.fsum(c["mass_s"] for c in contributions)
        )
    assert evidence.started_at.isoformat() == "2026-09-06T07:00:00+09:00"


def test_changed_history_changes_the_calculated_ratio(corpus):
    current, history, pins, policy = corpus
    before, _ = build_evidence(current, history, pins, policy, [])
    # The third generated walk is the only route reaching the turn-around region.
    after, _ = build_evidence(current, history[:2] + history[3:], pins, policy, [])
    assert spatial(before, "micro-001").value["appearance_ratio"] == pytest.approx(1 / 4)
    assert spatial(after, "micro-001").value["appearance_ratio"] == 0
    assert spatial(after, "micro-001").value["selected_walks"] == 3


def test_empty_history_is_unknown_ratio_not_zero(corpus):
    current, _, pins, policy = corpus
    evidence, _ = build_evidence(current, [], pins, policy, [])
    value = spatial(evidence, "pin-01").value
    assert value["selected_walks"] == 0
    assert value["appearance_ratio"] is None
    assert value["mass_per_appeared_walk_s"] is None


def test_history_uses_local_time_tags_and_excludes_other_pet_and_future(corpus):
    current, history, pins, policy = corpus
    other = copy.deepcopy(history[0])
    other["session"].update(id="other-pet", dog_id="another-dog")
    future = copy.deepcopy(history[0])
    future["session"].update(
        id="future", started_at="2026-09-07T07:00:00+09:00", ended_at="2026-09-07T08:00:00+09:00"
    )
    morning = policy.model_copy(update={"tags": {"time_band": "morning"}})
    evidence, audit = build_evidence(current, [*history, other, future], pins, morning, [])
    assert spatial(evidence, "pin-01").value["selected_walks"] == 4
    assert {x["session_id"] for x in audit["excluded_history"]} == {"other-pet", "future"}
    assert spatial(evidence, "pin-01").provenance["query_policy"]["timezone"] == "Asia/Seoul"


def test_raw_observation_boundary_rejects_truth_and_does_not_leak_generator(corpus):
    current, history, pins, policy = corpus
    with pytest.raises(ValueError, match="observed walk export"):
        measure({**current, "truth": {"latent_state": "secret-answer"}})
    evidence, _ = build_evidence(current, history, pins, policy, [])
    encoded = evidence.model_dump_json()
    for forbidden in ('"seed"', '"holds"', '"fatigue"', '"truth_duration_s"', '"latent_state"'):
        assert forbidden not in encoded
    assert "sniffing" in encoded  # Explicit authored pin, not inferred from motion truth.


def test_duplicate_sessions_and_unresolvable_radius_are_rejected(corpus):
    current, history, pins, policy = corpus
    with pytest.raises(ValueError, match="duplicate"):
        build_evidence(current, [history[0], history[0]], pins, policy, [])
    with pytest.raises(ValueError, match="격자가 못 담는다"):
        build_evidence(current, history, pins, policy.model_copy(update={"radius_m": 1}), [])


def test_cached_environment_preserves_query_scope_and_omits_contacts():
    snapshot = {
        "name": "A_CE7",
        "endpoint": "https://dapi.kakao.com/v2/local/search/category.json",
        "query": {
            "x": 127.05633,
            "y": 37.48928,
            "radius": 250,
            "category_group_code": "CE7",
            "serviceKey": "key-must-not-escape",
        },
        "http_status": 200,
        "fetched_at": "2026-09-06T07:49:00+00:00",
        "response_sha256": "recorded-http-fingerprint",
        "data": {
            "meta": {"is_end": False, "total_count": 17},
            "documents": [
                {
                    "id": "1",
                    "place_name": "시험 카페",
                    "x": "127.0564",
                    "y": "37.4893",
                    "distance": "10",
                    "phone": "phone-must-not-escape",
                }
            ],
        },
    }
    anchors = [
        {"id": "near", "lat": 37.48928, "lng": 127.05633},
        {"id": "far", "lat": 37.48, "lng": 127.04},
    ]
    pieces = project_snapshots([snapshot], anchors, 15)
    assert pieces[0].measurement_status == "partial_cached_response"
    assert pieces[0].value["query_radius_m"] == 250
    assert pieces[0].value["provider_meta"]["total_count"] == 17
    assert pieces[1].measurement_status == "no_source"
    encoded = json.dumps([p.model_dump() for p in pieces])
    assert "must-not-escape" not in encoded
    failed = {**snapshot, "http_status": 503}
    assert project_snapshots([failed], anchors, 15)[0].measurement_status == "source_failed"
