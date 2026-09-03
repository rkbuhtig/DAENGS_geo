"""walk trace 하나를 Android/GPX/ADB capture replay로 바꾸는 경계."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scripts.sim.walk.android_replay import (
    ANDROID_REPLAY_FORMAT,
    GPX_NAMESPACE,
    AndroidReplayContract,
    build_android_replay_artifacts,
    main,
    replay_with_adb,
)
from scripts.sim.walk.bundle import build_scenario_from_spec
from scripts.sim.walk.spec import WalkTraceScenarioSpec


def _spec(**overrides) -> WalkTraceScenarioSpec:
    payload = {
        "format": "walk-trace-scenario-v1",
        "seed": 73,
        "session_id": "android-replay-walk",
        "dog_id": "dog-73",
        "started_at": datetime(2026, 9, 3, 8, tzinfo=UTC),
        "origin": {"lat": 37.4979, "lng": 127.0276},
        "route": {
            "name": "android-replay-route",
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


def test_android_replay_preserves_observed_capture_and_omits_missing_truth_samples():
    scenario = build_scenario_from_spec(
        _spec(
            faults=[
                {"kind": "dropout", "id": "tunnel", "start_s": 15, "end_s": 25},
                {
                    "kind": "accuracy",
                    "id": "tree-cover",
                    "start_s": 40,
                    "end_s": 45,
                    "accuracy_m": 85,
                },
            ]
        )
    )
    replay = build_android_replay_artifacts(scenario).replay
    observed_rows = [row for row in scenario.trace["samples"] if row["observed_fix"] is not None]

    assert replay.format == ANDROID_REPLAY_FORMAT
    assert len(replay.samples) == len(observed_rows)
    assert replay.receipt.omitted_missing_sample_count == 3
    assert [sample.sample_id for sample in replay.samples] == [
        row["sample_id"] for row in observed_rows
    ]
    assert max(sample.delay_from_previous_ms for sample in replay.samples) == 20_000
    low_accuracy = [sample for sample in replay.samples if sample.accuracy_m == 85]
    assert len(low_accuracy) == 2
    assert all(sample.is_mock for sample in replay.samples)
    assert "truth" not in replay.samples[0].model_dump()
    assert "fault_ids" not in replay.samples[0].model_dump()
    json.dumps(replay.model_dump(mode="json"), allow_nan=False)


def test_delivery_changes_receipt_only_not_location_samples_or_gpx():
    plain = build_android_replay_artifacts(build_scenario_from_spec(_spec()))
    delivered = build_android_replay_artifacts(
        build_scenario_from_spec(
            _spec(
                delivery={
                    "base_latency_s": 0.25,
                    "batch_size": 3,
                    "reverse_within_batch": True,
                    "delay_windows": [{"id": "offline", "start_s": 15, "end_s": 25, "delay_s": 60}],
                    "duplicate_at_s": [10],
                }
            )
        )
    )

    assert delivered.replay.samples == plain.replay.samples
    assert delivered.replay.control_events == plain.replay.control_events
    assert delivered.gpx == plain.gpx
    assert delivered.replay.receipt.delivery_applied is False
    assert delivered.replay.receipt.source_delivery_event_count == (
        plain.replay.receipt.source_delivery_event_count + 1
    )


def test_gpx_breaks_track_segments_at_missing_samples_and_preserves_extensions():
    scenario = build_scenario_from_spec(
        _spec(faults=[{"kind": "dropout", "id": "tunnel", "start_s": 15, "end_s": 25}])
    )
    artifacts = build_android_replay_artifacts(scenario)
    root = ET.fromstring(artifacts.gpx)
    namespace = {"gpx": GPX_NAMESPACE}

    segments = root.findall(".//gpx:trkseg", namespace)
    points = root.findall(".//gpx:trkpt", namespace)
    assert len(segments) == 2
    assert len(points) == len(artifacts.replay.samples)
    assert points[0].find("gpx:time", namespace).text == "2026-09-03T08:00:00Z"
    assert "daengs:accuracyMeters" in artifacts.gpx
    assert "daengs:isMock" in artifacts.gpx


def test_chain_transitions_become_explicit_controls_and_adb_refuses_to_hide_them():
    scenario = build_scenario_from_spec(
        _spec(
            sensor={
                "kind": "perfect",
                "sample_interval_s": 5,
                "accuracy_m": 3,
                "chain_breaks_m": [100],
            }
        )
    )
    replay = build_android_replay_artifacts(scenario).replay

    assert len(replay.control_events) == 1
    assert replay.control_events[0].type == "chain_break"
    with pytest.raises(ValueError, match="cannot apply chain breaks"):
        replay_with_adb(replay, runner=lambda command: None, sleeper=lambda seconds: None)


def test_adb_replay_scales_capture_delays_and_puts_longitude_before_latitude():
    replay = build_android_replay_artifacts(build_scenario_from_spec(_spec())).replay
    payload = replay.model_dump(mode="json")
    payload["samples"] = payload["samples"][:3]
    payload["receipt"]["source_truth_sample_count"] = 3
    payload["receipt"]["emitted_location_sample_count"] = 3
    contract = AndroidReplayContract.model_validate(payload)
    commands = []
    delays = []

    count = replay_with_adb(
        contract,
        speed_multiplier=5,
        serial="emulator-5554",
        runner=lambda command: commands.append(list(command)),
        sleeper=delays.append,
    )

    assert count == 3
    assert delays == [1.0, 1.0]
    assert commands[0][:6] == ["adb", "-s", "emulator-5554", "emu", "geo", "fix"]
    assert commands[0][-2:] == [
        f"{contract.samples[0].longitude:.9f}",
        f"{contract.samples[0].latitude:.9f}",
    ]


def test_adb_can_prime_the_first_fix_before_the_capture_timeline_starts():
    replay = build_android_replay_artifacts(build_scenario_from_spec(_spec())).replay
    payload = replay.model_dump(mode="json")
    payload["samples"] = payload["samples"][:2]
    payload["receipt"]["source_truth_sample_count"] = 2
    payload["receipt"]["emitted_location_sample_count"] = 2
    contract = AndroidReplayContract.model_validate(payload)
    commands = []
    delays = []

    replay_with_adb(
        contract,
        speed_multiplier=5,
        prime_wait_s=3,
        runner=lambda command: commands.append(list(command)),
        sleeper=delays.append,
    )

    assert commands[0] == commands[1]
    assert delays == [3, 1.0]


def test_contract_rejects_a_timeline_whose_delay_does_not_match_offsets():
    replay = build_android_replay_artifacts(build_scenario_from_spec(_spec())).replay
    payload = replay.model_dump(mode="json")
    payload["samples"][1]["delay_from_previous_ms"] += 1

    with pytest.raises(ValidationError, match="delay_from_previous_ms"):
        AndroidReplayContract.model_validate(payload)


def test_cli_writes_portable_android_and_gpx_artifacts(tmp_path):
    spec_path = tmp_path / "scenario.json"
    spec_path.write_text(_spec().model_dump_json(), encoding="utf-8")
    out = tmp_path / "android-replay"

    assert main(["--spec", str(spec_path), "--out", str(out)]) == 0
    assert {path.name for path in out.iterdir()} == {
        "android-replay.json",
        "android-route.gpx",
    }
    assert (
        json.loads((out / "android-replay.json").read_text(encoding="utf-8"))["format"]
        == ANDROID_REPLAY_FORMAT
    )
    assert ET.fromstring((out / "android-route.gpx").read_text(encoding="utf-8")).tag == (
        f"{{{GPX_NAMESPACE}}}gpx"
    )
