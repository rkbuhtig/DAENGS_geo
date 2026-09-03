"""같은 실제 움직임의 perfect 기준군과 후보 GPS trace를 정량 비교한다.

이 모듈의 값은 실험 영수증이지 제품 합격선이 아니다. 생성기의 hold는 센서 구간이
실제 정지 시간과 겹친 거리와 Perfect 기준군 대비 차이를 재는 데만 쓰며, 제품
행동/일기 의미로 승격하지 않는다.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any

from app.geo.cells import EARTH_R
from scripts.sim.walk.bundle import ScenarioArtifacts, build_scenario_from_spec
from scripts.sim.walk.kinematics import MotionTruth, integrate_motion
from scripts.sim.walk.spec import DeliverySpec, SensorSpec, WalkTraceScenarioSpec

EVALUATION_FORMAT = "walk-trace-evaluation-v1"


def _rounded(value: float) -> float:
    return round(value, 6)


def _ratio(numerator: float, denominator: float) -> float | None:
    return _rounded(numerator / denominator) if denominator else None


def _percentile(ordered: Sequence[float], percentile: float) -> float | None:
    if not ordered:
        return None
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return _rounded(ordered[index])


def _distribution(values: Iterable[float]) -> dict[str, int | float | None]:
    ordered = sorted(values)
    if not ordered:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p95": None,
            "mean": None,
            "max": None,
        }
    return {
        "count": len(ordered),
        "min": _rounded(ordered[0]),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "mean": _rounded(math.fsum(ordered) / len(ordered)),
        "max": _rounded(ordered[-1]),
    }


def _motion(spec: WalkTraceScenarioSpec) -> MotionTruth:
    route = spec.route.to_geometry()
    return integrate_motion(spec.motion.to_behavior(route.length_m), route)


def _perfect_baseline_spec(spec: WalkTraceScenarioSpec) -> WalkTraceScenarioSpec:
    return spec.model_copy(
        update={
            "sensor": SensorSpec(
                kind="perfect",
                sample_interval_s=spec.sensor.sample_interval_s,
                accuracy_m=3.0,
                chain_breaks_m=spec.sensor.chain_breaks_m,
            ),
            "faults": (),
            "delivery": DeliverySpec(),
        }
    )


def _neutral_delivery_spec(spec: WalkTraceScenarioSpec) -> WalkTraceScenarioSpec:
    return spec.model_copy(update={"delivery": DeliverySpec()})


def _position_errors_m(artifacts: ScenarioArtifacts) -> list[float]:
    origin = artifacts.scenario["origin"]
    origin_lat = float(origin["lat"])
    origin_lng = float(origin["lng"])
    longitude_radius = EARTH_R * math.cos(math.radians(origin_lat))
    errors = []
    for row in artifacts.trace["samples"]:
        observed = row["observed_fix"]
        if observed is None:
            continue
        east_m = math.radians(float(observed["lng"]) - origin_lng) * longitude_radius
        north_m = math.radians(float(observed["lat"]) - origin_lat) * EARTH_R
        truth = row["truth"]
        errors.append(
            math.hypot(east_m - float(truth["east_m"]), north_m - float(truth["north_m"]))
        )
    return errors


def _fault_attribution(artifacts: ScenarioArtifacts) -> list[dict[str, object]]:
    accepted_sequences = {fix.client_seq for fix in artifacts.computed.receipt_input.accepted_fixes}
    rows = artifacts.trace["samples"]
    receipts = []
    for fault in artifacts.scenario["faults"]:
        affected = [row for row in rows if fault["id"] in row["fault_ids"]]
        observed = [row for row in affected if row["observed_fix"] is not None]
        receipts.append(
            {
                "id": fault["id"],
                "kind": fault["kind"],
                "affected_sample_count": len(affected),
                "observed_sample_count": len(observed),
                "missing_sample_count": len(affected) - len(observed),
                "accepted_sample_count": sum(
                    row["observed_fix"]["client_seq"] in accepted_sequences for row in observed
                ),
            }
        )
    return receipts


def _hold_intervals(motion: MotionTruth) -> list[tuple[float, float]]:
    return [
        (left.elapsed_s, right.elapsed_s)
        for left, right in pairwise(motion.timeline)
        if left.progress_m == right.progress_m
    ]


def _overlap_s(start_s: float, end_s: float, intervals: Sequence[tuple[float, float]]) -> float:
    return math.fsum(
        max(0.0, min(end_s, hold_end) - max(start_s, hold_start))
        for hold_start, hold_end in intervals
    )


def _hold_receipt(
    artifacts: ScenarioArtifacts,
    motion: MotionTruth,
) -> dict[str, float]:
    intervals = _hold_intervals(motion)
    allocated_distance_m = 0.0
    accepted_hold_s = 0.0
    for segment in artifacts.computed.trail.segments:
        start_s = (segment.a.at - artifacts.computed.facts.started_at).total_seconds()
        end_s = (segment.b.at - artifacts.computed.facts.started_at).total_seconds()
        overlap_s = _overlap_s(start_s, end_s, intervals)
        accepted_hold_s += overlap_s
        # 표본 구간이 move→hold 경계를 가로지르면 실제 이동의 일부도
        # 이 값에 포함된다. 따라서 false distance가 아니라 겹침 배분 거리로 명시한다.
        allocated_distance_m += segment.dist * overlap_s / segment.dt
    return {
        "truth_hold_s": _rounded(math.fsum(end - start for start, end in intervals)),
        "accepted_hold_s": _rounded(accepted_hold_s),
        "distance_allocated_over_hold_m": _rounded(allocated_distance_m),
    }


def _canonical_receipt(
    artifacts: ScenarioArtifacts,
    baseline: ScenarioArtifacts,
    motion: MotionTruth,
) -> dict[str, object]:
    facts = artifacts.computed.facts
    truth_distance_m = motion.route.length_m
    truth_duration_s = motion.duration_s
    accepted_time_s = math.fsum(segment.dt for segment in artifacts.computed.trail.segments)
    baseline_accepted_time_s = math.fsum(segment.dt for segment in baseline.computed.trail.segments)
    hold = _hold_receipt(artifacts, motion)
    baseline_hold = _hold_receipt(baseline, motion)
    truth_moving_s = truth_duration_s - hold["truth_hold_s"]
    distance_error_m = facts.moving_distance_m - truth_distance_m
    return {
        "truth_distance_m": _rounded(truth_distance_m),
        "candidate_moving_distance_m": facts.moving_distance_m,
        "moving_distance_error_m": _rounded(distance_error_m),
        "moving_distance_relative_error": _ratio(distance_error_m, truth_distance_m),
        "truth_duration_s": _rounded(truth_duration_s),
        "accepted_time_s": _rounded(accepted_time_s),
        "accepted_time_vs_truth": _ratio(accepted_time_s, truth_duration_s),
        "accepted_time_vs_perfect": _ratio(accepted_time_s, baseline_accepted_time_s),
        "truth_moving_s": _rounded(truth_moving_s),
        "candidate_moving_s": facts.moving_s,
        "moving_time_error_s": _rounded(facts.moving_s - truth_moving_s),
        "candidate_stop_s": facts.stop_s,
        "stop_time_error_s": _rounded(facts.stop_s - hold["truth_hold_s"]),
        **hold,
        "perfect_distance_allocated_over_hold_m": baseline_hold["distance_allocated_over_hold_m"],
        "distance_allocated_over_hold_vs_perfect_m": _rounded(
            hold["distance_allocated_over_hold_m"] - baseline_hold["distance_allocated_over_hold_m"]
        ),
        "quality": artifacts.computed.trail.quality.to_dict(),
    }


def _cell_ids(payload: Mapping[str, object]) -> set[str]:
    return {
        str(feature["id"])
        for feature in payload["features"]
        if feature["properties"].get("kind") == "cell"
    }


def _cellophane_receipt(
    artifacts: ScenarioArtifacts,
    baseline: ScenarioArtifacts,
) -> dict[str, object]:
    candidate = json.loads(artifacts.cellophane_geojson)
    perfect = json.loads(baseline.cellophane_geojson)
    candidate_cells = _cell_ids(candidate)
    perfect_cells = _cell_ids(perfect)
    union = candidate_cells | perfect_cells
    candidate_meta = candidate["meta"]
    return {
        "candidate_cell_count": len(candidate_cells),
        "perfect_cell_count": len(perfect_cells),
        "support_iou_vs_perfect": _ratio(len(candidate_cells & perfect_cells), len(union))
        if union
        else 1.0,
        "missing_cell_count": len(perfect_cells - candidate_cells),
        "leakage_cell_count": len(candidate_cells - perfect_cells),
        "source_segment_s": _rounded(candidate_meta["source_segment_s"]),
        "occupancy_mass_s": _rounded(candidate_meta["occupancy_mass_s"]),
        "mass_error_s": _rounded(candidate_meta["mass_error_s"]),
        "mass_conserved": candidate_meta["mass_conserved"],
    }


def _delivery_receipt(
    artifacts: ScenarioArtifacts,
    neutral: ScenarioArtifacts,
) -> dict[str, object]:
    events = sorted(artifacts.delivery["events"], key=lambda event: event["delivery_index"])
    unique_events = [event for event in events if not event["duplicate"]]
    observed_ids = set(artifacts.trace["observed_sample_ids"])
    delivered_ids = {event["sample_id"] for event in unique_events}
    out_of_order = 0
    latest_capture = -math.inf
    for event in unique_events:
        capture = float(event["captured_elapsed_s"])
        if capture < latest_capture:
            out_of_order += 1
        latest_capture = max(latest_capture, capture)
    latencies = [
        float(event["delivered_elapsed_s"]) - float(event["captured_elapsed_s"])
        for event in unique_events
    ]
    preserves = (
        artifacts.observed.to_export() == neutral.observed.to_export()
        and artifacts.computed == neutral.computed
        and artifacts.cellophane_geojson == neutral.cellophane_geojson
    )
    return {
        "event_count": len(events),
        "unique_event_count": len(unique_events),
        "duplicate_event_count": len(events) - len(unique_events),
        "batch_count": len({event["batch_id"] for event in events}),
        "latency_s": _distribution(latencies),
        "out_of_capture_order_event_count": out_of_order,
        "dangling_sample_id_count": sum(event["sample_id"] not in observed_ids for event in events),
        "undelivered_observed_sample_count": len(observed_ids - delivered_ids),
        "preserves_capture_and_canonical": preserves,
    }


def _all_finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(_all_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(item) for item in value)
    return True


def evaluate_scenario(artifacts: ScenarioArtifacts) -> dict[str, object]:
    """시나리오를 perfect 기준군과 짝지어 threshold 없는 관찰값을 만든다."""
    spec = WalkTraceScenarioSpec.model_validate(artifacts.scenario)
    motion = _motion(spec)
    baseline = build_scenario_from_spec(_perfect_baseline_spec(spec))
    neutral = (
        artifacts
        if spec.delivery == DeliverySpec()
        else build_scenario_from_spec(_neutral_delivery_spec(spec))
    )
    trace_samples = artifacts.trace["samples"]
    position_errors = _position_errors_m(artifacts)
    sensor = {
        "truth_sample_count": len(trace_samples),
        "observed_fix_count": len(artifacts.observed.fixes),
        "missing_sample_count": sum(row["observed_fix"] is None for row in trace_samples),
        "fix_retention": _ratio(len(artifacts.observed.fixes), len(trace_samples)),
        "position_error_m": _distribution(position_errors),
        "explicit_fault_attribution": _fault_attribution(artifacts),
    }
    canonical = _canonical_receipt(artifacts, baseline, motion)
    cellophane = _cellophane_receipt(artifacts, baseline)
    delivery = _delivery_receipt(artifacts, neutral)
    evaluation: dict[str, object] = {
        "format": EVALUATION_FORMAT,
        "role": "paired experiment receipt; soft metrics are not product thresholds",
        "scenario_id": artifacts.scenario["session_id"],
        "baseline": {
            "sensor_kind": "perfect",
            "explicit_fault_count": 0,
            "delivery_kind": "neutral",
            "observed_fix_count": len(baseline.observed.fixes),
            "position_error_m": _distribution(_position_errors_m(baseline)),
            "moving_distance_m": baseline.computed.facts.moving_distance_m,
            "accepted_time_s": baseline.derived["accepted_segment_s"],
            "cell_count": json.loads(baseline.cellophane_geojson)["meta"]["cell_count"],
        },
        "sensor": sensor,
        "canonical": canonical,
        "cellophane": cellophane,
        "delivery": delivery,
    }
    hard_invariants = {
        "finite_numeric_output": _all_finite(evaluation),
        "cellophane_mass_conserved": cellophane["mass_conserved"] is True,
        "delivery_sample_ids_resolve": delivery["dangling_sample_id_count"] == 0,
        "every_observed_sample_delivered": delivery["undelivered_observed_sample_count"] == 0,
        "delivery_preserves_capture_and_canonical": delivery["preserves_capture_and_canonical"]
        is True,
    }
    evaluation["hard_invariants"] = hard_invariants
    evaluation["hard_invariants_passed"] = all(hard_invariants.values())
    return evaluation
