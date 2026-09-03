"""파일 기반 GPS trace 시나리오의 truth/observation/delivery 경계."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.sim.walk.bundle import build_scenario_from_spec
from scripts.sim.walk.cli import main
from scripts.sim.walk.spec import WalkTraceScenarioSpec


def _spec(**overrides) -> WalkTraceScenarioSpec:
    payload = {
        "format": "walk-trace-scenario-v1",
        "seed": 73,
        "dog_id": "dog-73",
        "started_at": datetime(2026, 9, 3, 8, tzinfo=UTC),
        "origin": {"lat": 37.4979, "lng": 127.0276},
        "route": {
            "name": "hand-drawn-zigzag",
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


def test_custom_route_and_motion_are_resolved_into_a_replayable_scenario():
    artifacts = build_scenario_from_spec(_spec())

    assert artifacts.scenario["session_id"].startswith("sim-trace-v1-")
    assert artifacts.manifest["route"]["name"] == "hand-drawn-zigzag"
    assert artifacts.manifest["behavior"]["name"] == "sniff-and-go"
    assert len(artifacts.trace["samples"]) == len(artifacts.observed.fixes)
    assert all(row["observed_fix"] is not None for row in artifacts.trace["samples"])


def test_explicit_fault_timeline_marks_missing_and_low_accuracy_samples():
    spec = _spec(
        faults=[
            {"kind": "dropout", "id": "underpass", "start_s": 20, "end_s": 30},
            {
                "kind": "accuracy",
                "id": "tree-cover",
                "start_s": 40,
                "end_s": 50,
                "accuracy_m": 95,
            },
            {
                "kind": "position_offset",
                "id": "single-spike",
                "at_s": 60,
                "east_m": 260,
                "north_m": 0,
            },
        ]
    )
    artifacts = build_scenario_from_spec(spec)
    rows = artifacts.trace["samples"]

    missing = [row for row in rows if "underpass" in row["fault_ids"]]
    inaccurate = [row for row in rows if "tree-cover" in row["fault_ids"]]
    spike = [row for row in rows if "single-spike" in row["fault_ids"]]
    assert missing and all(row["observed_fix"] is None for row in missing)
    assert inaccurate and all(row["observed_fix"]["accuracy_m"] == 95 for row in inaccurate)
    assert len(spike) == 1
    assert spike[0]["observed_fix"] is not None
    assert artifacts.computed.quality.jump_breaks > 0


def test_delivery_faults_do_not_rewrite_capture_order_or_canonical_facts():
    baseline = build_scenario_from_spec(_spec(session_id="delivery-invariant"))
    delayed = build_scenario_from_spec(
        _spec(
            session_id="delivery-invariant",
            delivery={
                "base_latency_s": 0.25,
                "batch_size": 3,
                "reverse_within_batch": True,
                "delay_windows": [{"id": "offline", "start_s": 15, "end_s": 25, "delay_s": 60}],
                "duplicate_at_s": [10],
            },
        )
    )

    assert baseline.observed.to_export() == delayed.observed.to_export()
    assert baseline.computed == delayed.computed
    events = delayed.delivery["events"]
    assert len(events) == len(delayed.observed.fixes) + 1
    assert sum(event["duplicate"] for event in events) == 1
    first_batch = [event for event in events if event["batch_id"] == "batch-000000"]
    assert [event["client_seq"] for event in first_batch if not event["duplicate"]] == [2, 1, 0]
    assert max(event["delivered_elapsed_s"] for event in events) >= 75


def test_each_duplicate_time_produces_an_event_when_targets_share_a_sample():
    artifacts = build_scenario_from_spec(
        _spec(delivery={"duplicate_at_s": [10.1, 10.2]})
    )

    duplicates = [event for event in artifacts.delivery["events"] if event["duplicate"]]
    assert len(duplicates) == 2
    assert duplicates[0]["sample_id"] == duplicates[1]["sample_id"]


def test_same_spec_reproduces_all_trace_layers():
    spec = _spec(
        sensor={
            "kind": "noisy",
            "sample_interval_s": 5,
            "accuracy_m": 3,
            "jitter_sigma_m": 2,
            "dropout_rate": 0.08,
        }
    )
    first = build_scenario_from_spec(spec)
    second = build_scenario_from_spec(spec)

    assert first.scenario == second.scenario
    assert first.trace == second.trace
    assert first.delivery == second.delivery
    assert first.derived == second.derived


def test_contract_rejects_unknown_versions_and_perfect_sensor_noise():
    with pytest.raises(ValidationError):
        _spec(format="walk-trace-scenario-v2")
    with pytest.raises(ValidationError, match="perfect sensor"):
        _spec(sensor={"kind": "perfect", "jitter_sigma_m": 2})


def test_checked_in_authored_example_stays_executable():
    example = (
        Path(__file__).parents[2] / "scripts" / "sim" / "walk" / "examples" / "sniff-and-go.json"
    )
    spec = WalkTraceScenarioSpec.model_validate_json(example.read_text(encoding="utf-8"))

    artifacts = build_scenario_from_spec(spec)
    assert artifacts.scenario["session_id"] == "lab-sniff-and-go"
    assert artifacts.computed.quality.rejected_low_accuracy > 0
    assert artifacts.computed.quality.jump_breaks > 0


def test_cli_can_replay_a_saved_scenario_contract(tmp_path):
    scenario_path = tmp_path / "authored.json"
    scenario_path.write_text(
        json.dumps(_spec(session_id="authored-walk").model_dump(mode="json")),
        encoding="utf-8",
    )
    out = tmp_path / "result"

    assert main(["--spec", str(scenario_path), "--out", str(out)]) == 0
    assert (
        json.loads((out / "scenario.json").read_text(encoding="utf-8"))["session_id"]
        == "authored-walk"
    )
    assert json.loads((out / "trace.json").read_text(encoding="utf-8"))["format"] == (
        "walk-trace-v1"
    )
    assert json.loads((out / "delivery.json").read_text(encoding="utf-8"))["format"] == (
        "walk-delivery-v1"
    )
