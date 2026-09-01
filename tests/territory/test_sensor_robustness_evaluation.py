"""paired GPS 오염 → canonical → Cellophane → 복원 Field 평가 계약."""

import json

import pytest

from scripts.spikes.territory_paint.sensor_robustness_evaluation import (
    FIXED_BLEND_REACH_CELLS,
    FIXED_RADIUS_U,
    SENSOR_SCENARIOS,
    build_sensor_robustness_payload,
)


@pytest.fixture(scope="module")
def payload():
    return build_sensor_robustness_payload(
        scenario_names=("clean_control", "combined"),
        walk_limit=3,
    )


def test_evaluator_freezes_projection_contract_on_a_new_sensor_holdout(payload):
    assert payload["format_version"] == 1
    assert payload["evaluation_role"] == "paired_sensor_holdout_not_product_threshold"
    assert payload["population"]["split"] == "sensor_holdout"
    assert payload["population"]["sample_count"] == 3
    assert payload["fixed_contract"] == {
        "radius_u": FIXED_RADIUS_U,
        "blend_reach_cells": FIXED_BLEND_REACH_CELLS,
        "pixel_m": 4.0,
        "reach_retuned": False,
        "exposure_retuned": False,
    }


def test_clean_control_is_identical_until_the_fixed_hex_projection(payload):
    clean = payload["scenarios"][0]

    assert clean["name"] == "clean_control"
    assert clean["collection"]["fix_retention"] == pytest.approx(1.0)
    assert clean["collection"]["accepted_time_retention"] == pytest.approx(1.0)
    assert clean["cellophane"]["support_iou"] == pytest.approx(1.0)
    for metric in clean["field"]["sensor_only_continuous"].values():
        assert metric["mean_absolute_error"] == pytest.approx(0.0)


def test_combined_scenario_reports_each_pipeline_stage_and_keeps_hard_invariants(payload):
    combined = payload["scenarios"][1]

    assert combined["name"] == "combined"
    assert combined["collection"]["fix_retention"] < 1.0
    assert combined["collection"]["candidate_quality"]["rejected_low_accuracy"] > 0
    assert set(combined["field"]) == {
        "sensor_only_continuous",
        "projection_given_sensor",
        "combined_against_perfect",
    }
    assert all(combined["hard_invariants"].values())
    assert combined["field"]["combined_against_perfect"]["support"]["leakage_pixels"] == 0


def test_payload_hides_latent_population_labels_and_sensor_seed(payload):
    encoded = json.dumps(payload, sort_keys=True)

    for forbidden in ('"seed"', '"branch"', '"hold"', "east_loop", "north_park"):
        assert forbidden not in encoded
    assert all("fingerprint" in row["profile"] for row in payload["scenarios"])


def test_declared_scenarios_cover_each_sensor_failure_axis():
    assert set(SENSOR_SCENARIOS) == {
        "clean_control",
        "jitter",
        "dropout",
        "outlier",
        "drift",
        "variable_accuracy",
        "combined",
    }


@pytest.mark.parametrize(
    "kwargs",
    (
        {"scenario_names": ()},
        {"scenario_names": ("jitter", "jitter")},
        {"scenario_names": ("unknown",)},
        {"walk_limit": 0},
    ),
)
def test_invalid_evaluation_contract_fails(kwargs):
    with pytest.raises(ValueError):
        build_sensor_robustness_payload(**kwargs)
