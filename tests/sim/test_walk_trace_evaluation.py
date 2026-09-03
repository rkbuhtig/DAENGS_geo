"""Walk Trace의 perfect 기준군 대비 정량 평가 영수증."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.sim.walk.bundle import build_scenario_from_spec
from scripts.sim.walk.evaluation import EVALUATION_FORMAT, evaluate_scenario
from scripts.sim.walk.spec import WalkTraceScenarioSpec


def _spec(**overrides) -> WalkTraceScenarioSpec:
    payload = {
        "format": "walk-trace-scenario-v1",
        "seed": 73,
        "session_id": "evaluation-walk",
        "dog_id": "dog-73",
        "started_at": datetime(2026, 9, 3, 8, tzinfo=UTC),
        "origin": {"lat": 37.4979, "lng": 127.0276},
        "route": {
            "name": "evaluation-route",
            "points_xy": [[0, 0], [90, 0], [120, 40], [210, 40]],
        },
        "motion": {
            "name": "sniff-and-go",
            "base_speed_mps": 1.2,
            "slow_motifs": [{"centre_m": 60, "width_m": 20, "min_factor": 0.35}],
            "holds": [{"progress_m": 130, "duration_s": 12}],
        },
        "sensor": {"kind": "perfect", "sample_interval_s": 5, "accuracy_m": 3},
        "faults": [],
        "delivery": {},
    }
    payload.update(overrides)
    return WalkTraceScenarioSpec.model_validate(payload)


def test_perfect_control_exposes_sampling_bias_without_inventing_a_threshold():
    evaluation = evaluate_scenario(build_scenario_from_spec(_spec()))

    assert evaluation["format"] == EVALUATION_FORMAT
    assert evaluation["sensor"]["fix_retention"] == 1
    assert evaluation["sensor"]["position_error_m"]["max"] < 0.001
    assert evaluation["canonical"]["accepted_time_vs_perfect"] == 1
    assert evaluation["canonical"]["excess_false_distance_vs_perfect_m"] == 0
    assert evaluation["cellophane"]["support_iou_vs_perfect"] == 1
    assert evaluation["delivery"]["duplicate_event_count"] == 0
    assert evaluation["delivery"]["out_of_capture_order_event_count"] == 0
    assert evaluation["hard_invariants_passed"] is True
    assert "threshold" in evaluation["role"]
    json.dumps(evaluation, ensure_ascii=False, allow_nan=False)


def test_authored_faults_are_attributed_across_sensor_canonical_and_field_layers():
    example = (
        Path(__file__).parents[2]
        / "scripts"
        / "sim"
        / "walk"
        / "examples"
        / "sniff-and-go.json"
    )
    spec = WalkTraceScenarioSpec.model_validate_json(example.read_text(encoding="utf-8"))
    evaluation = evaluate_scenario(build_scenario_from_spec(spec))

    faults = {item["id"]: item for item in evaluation["sensor"]["explicit_fault_attribution"]}
    assert faults["underpass"]["missing_sample_count"] > 0
    assert faults["tree-cover"]["observed_sample_count"] > 0
    assert faults["tree-cover"]["accepted_sample_count"] == 0
    assert faults["single-spike"]["accepted_sample_count"] == 1
    assert evaluation["sensor"]["position_error_m"]["max"] > 200
    assert evaluation["canonical"]["quality"]["jump_breaks"] > 0
    assert evaluation["canonical"]["false_distance_during_hold_m"] > 0
    assert evaluation["canonical"]["excess_false_distance_vs_perfect_m"] > 0
    assert evaluation["cellophane"]["support_iou_vs_perfect"] < 1
    assert evaluation["cellophane"]["mass_conserved"] is True


def test_delivery_faults_only_change_the_delivery_receipt():
    baseline = evaluate_scenario(build_scenario_from_spec(_spec()))
    delayed = evaluate_scenario(
        build_scenario_from_spec(
            _spec(
                delivery={
                    "base_latency_s": 0.25,
                    "batch_size": 3,
                    "reverse_within_batch": True,
                    "delay_windows": [
                        {"id": "offline", "start_s": 15, "end_s": 25, "delay_s": 60}
                    ],
                    "duplicate_at_s": [10],
                }
            )
        )
    )

    assert delayed["sensor"] == baseline["sensor"]
    assert delayed["canonical"] == baseline["canonical"]
    assert delayed["cellophane"] == baseline["cellophane"]
    assert delayed["delivery"]["duplicate_event_count"] == 1
    assert delayed["delivery"]["out_of_capture_order_event_count"] > 0
    assert delayed["delivery"]["latency_s"]["max"] >= 60
    assert delayed["delivery"]["preserves_capture_and_canonical"] is True


def test_evaluation_is_deterministic_and_only_hard_invariants_are_pass_fail():
    first = evaluate_scenario(build_scenario_from_spec(_spec()))
    second = evaluate_scenario(build_scenario_from_spec(_spec()))

    assert first == second
    assert set(first["hard_invariants"]) == {
        "finite_numeric_output",
        "cellophane_mass_conserved",
        "delivery_sample_ids_resolve",
        "every_observed_sample_delivered",
        "delivery_preserves_capture_and_canonical",
    }
    assert all(isinstance(value, bool) for value in first["hard_invariants"].values())
    assert first["canonical"]["moving_distance_error_m"] != pytest.approx(0)
