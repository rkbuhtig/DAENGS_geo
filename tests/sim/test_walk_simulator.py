"""산책 시뮬레이터의 truth → observation → canonical 경계."""

from __future__ import annotations

import json
import math

import pytest

from scripts.sim.walk.bundle import build_scenario, write_scenario
from scripts.sim.walk.cli import main
from scripts.sim.walk.kinematics import integrate_motion
from scripts.sim.walk.model import BehaviorPlan, SlowMotif, behavior_preset
from scripts.sim.walk.route import route_preset
from scripts.spikes.territory_paint.cellophane_replay import DeviceExport, parse_export


def test_same_seed_reproduces_every_truth_and_observed_fix():
    first = build_scenario(seed=17)
    second = build_scenario(seed=17)

    assert first.manifest == second.manifest
    assert first.truth == second.truth
    assert first.observed.to_export() == second.observed.to_export()
    assert first.derived == second.derived
    assert first.cellophane_geojson == second.cellophane_geojson


def test_seed_changes_behavior_without_changing_the_named_route():
    first = build_scenario(seed=17)
    second = build_scenario(seed=18)

    assert first.manifest["behavior"] != second.manifest["behavior"]
    assert first.manifest["route"] == second.manifest["route"]
    assert first.manifest["session_id"] != second.manifest["session_id"]


@pytest.mark.parametrize(
    ("override", "value"),
    (
        ({"route_name": "loop"}, "route"),
        ({"sample_interval_s": 3.0}, "sampling"),
        ({"chain_breaks_m": (300.0,)}, "chain break"),
        ({"origin_lat": 37.6}, "origin"),
    ),
)
def test_scenario_identity_changes_with_observation_inputs(override, value):
    baseline = build_scenario(seed=17)
    changed = build_scenario(seed=17, **override)

    assert baseline.manifest["session_id"] != changed.manifest["session_id"], value


def test_explicit_session_identity_is_preserved():
    artifacts = build_scenario(session_id="scenario-under-review")

    assert artifacts.manifest["session_id"] == "scenario-under-review"
    assert artifacts.observed.session_id == "scenario-under-review"
    assert artifacts.computed.facts.session_id == "scenario-under-review"


def test_slow_motif_must_fit_at_the_start_of_the_behavior():
    with pytest.raises(ValueError, match="slow motif must fit"):
        BehaviorPlan(
            name="steady",
            length_m=100.0,
            base_speed_mps=1.0,
            slow_motifs=(SlowMotif(centre_m=1.0, width_m=10.0, min_factor=0.5),),
        )


@pytest.mark.parametrize("name", ("straight", "s-curve", "loop", "out-and-back"))
def test_route_presets_have_the_requested_arc_length(name):
    route = route_preset(name, 600.0)
    assert route.length_m == pytest.approx(600.0, abs=1e-6)
    assert route.point_at(0.0) == route.points_xy[0]
    assert route.point_at(route.length_m) == route.points_xy[-1]


def test_rotation_and_translation_do_not_change_behavior_timing():
    behavior = behavior_preset("fatigued", 500.0, seed=5)
    route = route_preset("s-curve", 500.0)
    moved = route.transformed(rotation_degrees=73.0, east_m=230.0, north_m=-91.0)
    original_truth = integrate_motion(behavior, route)
    moved_truth = integrate_motion(behavior, moved)

    assert moved_truth.duration_s == pytest.approx(original_truth.duration_s, abs=1e-9)
    for before, after in zip(
        original_truth.samples(3.0), moved_truth.samples(3.0), strict=True
    ):
        assert after.elapsed_s == before.elapsed_s
        assert after.progress_m == before.progress_m
        assert after.forward_speed_mps == before.forward_speed_mps
        assert after.latent_state == before.latent_state


def test_holds_are_truth_time_not_a_generated_cellophane_intensity():
    artifacts = build_scenario(
        behavior_name="exploratory",
        route_name="straight",
        length_m=400.0,
        seed=91,
        sample_interval_s=2.0,
    )
    held = [sample for sample in artifacts.truth["samples"] if sample["latent_state"] == "hold"]

    assert held
    assert all(sample["forward_speed_mps"] == 0 for sample in held)
    assert artifacts.computed.facts.stop_count >= 2
    assert "occupancy" not in artifacts.manifest["behavior"]


def test_explicit_chain_break_never_creates_a_bridging_segment():
    artifacts = build_scenario(
        behavior_name="steady",
        route_name="straight",
        length_m=300.0,
        seed=2,
        sample_interval_s=2.0,
        chain_breaks_m=(150.0,),
    )
    segments = artifacts.computed.trail.segments

    assert artifacts.computed.trail.quality.explicit_breaks == 1
    assert {segment.chain_index for segment in segments} == {0, 1}
    assert all(segment.a.chain_index == segment.b.chain_index for segment in segments)


def test_canonical_paint_conserves_the_observed_segment_time():
    artifacts = build_scenario(seed=301, chain_breaks_m=(330.0,))
    payload = json.loads(artifacts.cellophane_geojson)
    observed_s = math.fsum(segment.dt for segment in artifacts.computed.trail.segments)

    assert payload["meta"]["mass_conserved"] is True
    assert payload["meta"]["source_segment_s"] == pytest.approx(observed_s, abs=1e-9)
    assert payload["meta"]["occupancy_mass_s"] == pytest.approx(observed_s, abs=1e-9)


def test_bundle_exposes_derived_segment_speed_without_claiming_sensor_speed():
    artifacts = build_scenario(seed=8)
    speeds = [segment["speed_mps"] for segment in artifacts.derived["segments"]]

    assert speeds
    assert min(speeds) < max(speeds)
    assert all("speed_mps" not in fix for fix in artifacts.observed.to_export()["fixes"])


def test_walk_export_is_the_existing_replay_contract():
    artifacts = build_scenario(seed=44)
    device = DeviceExport.model_validate(artifacts.observed.to_export())
    replayed_device, replayed = parse_export(device.model_dump(mode="json"))

    assert replayed_device.session.id == artifacts.observed.session_id
    assert replayed.facts == artifacts.computed.facts
    assert replayed.trail.quality.to_dict() == artifacts.computed.trail.quality.to_dict()


def test_cli_writes_all_truth_observation_and_derived_layers(tmp_path, capsys):
    out = tmp_path / "scenario"
    assert main([
        "--behavior", "fatigued",
        "--route", "loop",
        "--length-m", "300",
        "--seed", "9",
        "--session-id", "fatigued-loop-review",
        "--chain-break-m", "180",
        "--out", str(out),
    ]) == 0

    assert {path.name for path in out.iterdir()} == {
        "scenario.json",
        "manifest.json",
        "truth.json",
        "walk-export.json",
        "trace.json",
        "delivery.json",
        "derived.json",
        "cellophane.geojson",
    }
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["seed"] == 9
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))[
        "session_id"
    ] == "fatigued-loop-review"
    assert "written to" in capsys.readouterr().out


def test_writer_refuses_to_overwrite_an_existing_run(tmp_path):
    out = tmp_path / "scenario"
    artifacts = build_scenario(seed=1)
    write_scenario(out, artifacts)
    with pytest.raises(FileExistsError, match="not empty"):
        write_scenario(out, artifacts)
