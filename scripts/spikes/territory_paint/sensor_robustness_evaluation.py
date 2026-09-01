"""고정된 8u / 1.75 cell 복원이 GPS 오염에서 유지되는지 paired population으로 측정한다.

    uv run python -m scripts.spikes.territory_paint.sensor_robustness_evaluation \
        --out sensor-robustness-evaluation.json

같은 latent 산책을 perfect sensor와 한 종류의 noisy sensor로 각각 관측한다. 센서 오염 뒤에는
제품의 기존 `compute_facts`와 Cellophane paint를 그대로 통과시킨다. 이번 evaluator는 reach나
exposure를 다시 맞추지 않으며 soft metric을 합격선으로 승격하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

from app.geo.cells import cell_area_m2
from scripts.sim.walk.population import (
    PopulationObservation,
    observe_population_with_sensor,
)
from scripts.sim.walk.population_truth import build_population_truth
from scripts.sim.walk.sensor import NoisySensor, PerfectSensor
from scripts.spikes.territory_paint.conservative_hex_evaluation import (
    build_radius_reconstruction_layers,
    compare_raster_fields,
    reconstruction_comparison_receipt,
)
from scripts.spikes.territory_paint.continuous_hex_comparison import (
    DEFAULT_PIXEL_M,
    METRICS,
    RasterSpec,
    raster_metric_fields,
    rasterize_observation,
)

SENSOR_ROBUSTNESS_FORMAT_VERSION = 1
SENSOR_ROBUSTNESS_POPULATION_SEED = 488_201
FIXED_RADIUS_U = 8.0
FIXED_BLEND_REACH_CELLS = 1.75

SENSOR_SCENARIOS: dict[str, NoisySensor] = {
    "clean_control": NoisySensor(seed=10_001),
    "jitter": NoisySensor(jitter_sigma_m=4.0, accuracy_sigma_m=2.0, seed=10_002),
    "dropout": NoisySensor(dropout_rate=0.12, seed=10_003),
    "outlier": NoisySensor(outlier_rate=0.008, outlier_distance_m=260.0, seed=10_004),
    "drift": NoisySensor(drift_east_m=18.0, drift_north_m=-10.0, seed=10_005),
    "variable_accuracy": NoisySensor(
        accuracy_sigma_m=6.0,
        low_accuracy_rate=0.08,
        low_accuracy_m=80.0,
        seed=10_006,
    ),
    "combined": NoisySensor(
        jitter_sigma_m=3.0,
        accuracy_sigma_m=4.0,
        dropout_rate=0.08,
        outlier_rate=0.004,
        outlier_distance_m=260.0,
        drift_east_m=12.0,
        drift_north_m=-6.0,
        low_accuracy_rate=0.05,
        low_accuracy_m=80.0,
        seed=10_007,
    ),
}


def _sensor_profile(sensor: NoisySensor) -> dict[str, object]:
    full = sensor.to_dict()
    encoded = json.dumps(full, sort_keys=True, separators=(",", ":")).encode()
    return {
        "fingerprint": hashlib.sha256(encoded).hexdigest()[:16],
        "parameters": {key: value for key, value in full.items() if key not in {"kind", "seed"}},
    }


def _quality_totals(observation: PopulationObservation) -> dict[str, int]:
    totals: dict[str, int] = {}
    for walk in observation.walks:
        for name, value in walk.computed.quality.to_dict().items():
            totals[name] = totals.get(name, 0) + value
    return totals


def _collection_receipt(
    baseline: PopulationObservation,
    candidate: PopulationObservation,
) -> dict[str, object]:
    baseline_fixes = sum(len(walk.observed.fixes) for walk in baseline.walks)
    candidate_fixes = sum(len(walk.observed.fixes) for walk in candidate.walks)
    baseline_segment_s = math.fsum(walk.accepted_segment_s for walk in baseline.walks)
    candidate_segment_s = math.fsum(walk.accepted_segment_s for walk in candidate.walks)
    baseline_distance_m = math.fsum(walk.computed.facts.distance_m for walk in baseline.walks)
    candidate_distance_m = math.fsum(walk.computed.facts.distance_m for walk in candidate.walks)
    return {
        "baseline_fix_count": baseline_fixes,
        "candidate_fix_count": candidate_fixes,
        "fix_retention": candidate_fixes / baseline_fixes if baseline_fixes else 1.0,
        "baseline_accepted_segment_s": baseline_segment_s,
        "candidate_accepted_segment_s": candidate_segment_s,
        "accepted_time_retention": (
            candidate_segment_s / baseline_segment_s if baseline_segment_s else 1.0
        ),
        "baseline_distance_m": baseline_distance_m,
        "candidate_distance_m": candidate_distance_m,
        "distance_ratio": candidate_distance_m / baseline_distance_m if baseline_distance_m else 1.0,
        "candidate_quality": _quality_totals(candidate),
    }


def _cellophane_receipt(
    baseline: PopulationObservation,
    candidate: PopulationObservation,
    *,
    radius_u: float,
    origin_lat: float,
) -> dict[str, object]:
    baseline_cells = {cell for sheet in baseline.sheets for cell in sheet.occupancy}
    candidate_cells = {cell for sheet in candidate.sheets for cell in sheet.occupancy}
    union = baseline_cells | candidate_cells
    accepted_s = math.fsum(walk.accepted_segment_s for walk in candidate.walks)
    painted_s = math.fsum(value for sheet in candidate.sheets for value in sheet.occupancy.values())
    hex_area = cell_area_m2(radius_u, origin_lat)
    return {
        "accepted_segment_s": accepted_s,
        "painted_s": painted_s,
        "mass_absolute_error_s": abs(painted_s - accepted_s),
        "baseline_cell_count": len(baseline_cells),
        "candidate_cell_count": len(candidate_cells),
        "support_iou": len(baseline_cells & candidate_cells) / len(union) if union else 1.0,
        "leakage_cells": len(candidate_cells - baseline_cells),
        "missing_cells": len(baseline_cells - candidate_cells),
        "leakage_area_m2": len(candidate_cells - baseline_cells) * hex_area,
        "missing_area_m2": len(baseline_cells - candidate_cells) * hex_area,
    }


def _all_finite(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_all_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(item) for item in value)
    return True


def _scenario_receipt(
    name: str,
    sensor: NoisySensor,
    truth,
    baseline: PopulationObservation,
    baseline_fields,
    raster: RasterSpec,
) -> dict[str, object]:
    candidate = observe_population_with_sensor(truth, sensor=sensor, radius_u=FIXED_RADIUS_U)
    candidate_continuous_fields = raster_metric_fields(rasterize_observation(candidate, raster))
    layers = build_radius_reconstruction_layers(
        candidate,
        FIXED_RADIUS_U,
        raster,
        blend_reach_cells=FIXED_BLEND_REACH_CELLS,
    )
    collection = _collection_receipt(baseline, candidate)
    cellophane = _cellophane_receipt(
        baseline,
        candidate,
        radius_u=FIXED_RADIUS_U,
        origin_lat=raster.origin_lat,
    )
    sensor_only = {
        metric: compare_raster_fields(baseline_fields[metric], candidate_continuous_fields[metric])
        for metric in METRICS
    }
    projection_given_sensor = reconstruction_comparison_receipt(
        candidate_continuous_fields, raster, layers
    )
    combined = reconstruction_comparison_receipt(baseline_fields, raster, layers)
    row: dict[str, object] = {
        "name": name,
        "profile": _sensor_profile(sensor),
        "run_id": candidate.run_id,
        "collection": collection,
        "cellophane": cellophane,
        "field": {
            "sensor_only_continuous": sensor_only,
            "projection_given_sensor": projection_given_sensor,
            "combined_against_perfect": combined,
        },
    }
    row["hard_invariants"] = {
        "finite_receipt": _all_finite(row),
        "cellophane_mass_conserved": cellophane["mass_absolute_error_s"] < 1e-8,
        "reconstruction_mass_conserved": combined["mass"]["reconstructed_absolute_error_s"] < 1e-8,  # type: ignore[index]
        "reconstruction_support_leakage_zero": combined["support"]["leakage_pixels"] == 0,  # type: ignore[index]
        "reconstruction_support_missing_zero": combined["support"]["missing_pixels"] == 0,  # type: ignore[index]
    }
    return row


def build_sensor_robustness_payload(
    *,
    pixel_m: float = DEFAULT_PIXEL_M,
    scenario_names: tuple[str, ...] = tuple(SENSOR_SCENARIOS),
    walk_limit: int | None = None,
) -> dict[str, object]:
    if not scenario_names or len(set(scenario_names)) != len(scenario_names):
        raise ValueError("scenario_names는 비어 있지 않은 중복 없는 목록이어야 한다")
    unknown = set(scenario_names) - set(SENSOR_SCENARIOS)
    if unknown:
        raise ValueError(f"지원하지 않는 sensor scenario: {sorted(unknown)}")
    if walk_limit is not None and walk_limit <= 0:
        raise ValueError("walk_limit는 양수여야 한다")

    truth = build_population_truth(seed=SENSOR_ROBUSTNESS_POPULATION_SEED)
    if walk_limit is not None:
        truth = replace(truth, walks=truth.walks[:walk_limit])
    baseline = observe_population_with_sensor(
        truth,
        sensor=PerfectSensor(sample_interval_s=5.0, accuracy_m=3.0),
        radius_u=FIXED_RADIUS_U,
    )
    raster = RasterSpec(pixel_m=pixel_m)
    baseline_fields = raster_metric_fields(rasterize_observation(baseline, raster))
    scenarios = [
        _scenario_receipt(
            name,
            SENSOR_SCENARIOS[name],
            truth,
            baseline,
            baseline_fields,
            raster,
        )
        for name in scenario_names
    ]
    return {
        "format_version": SENSOR_ROBUSTNESS_FORMAT_VERSION,
        "evaluation_role": "paired_sensor_holdout_not_product_threshold",
        "fixed_contract": {
            "radius_u": FIXED_RADIUS_U,
            "blend_reach_cells": FIXED_BLEND_REACH_CELLS,
            "pixel_m": raster.pixel_m,
            "reach_retuned": False,
            "exposure_retuned": False,
        },
        "population": {
            "split": "sensor_holdout",
            "generator_version": baseline.generator_version,
            "baseline_run_id": baseline.run_id,
            "sample_count": len(baseline.walks),
        },
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("sensor-robustness-evaluation.json"))
    parser.add_argument("--pixel-m", type=float, default=DEFAULT_PIXEL_M)
    parser.add_argument("--walk-limit", type=int)
    parser.add_argument("--scenario", action="append", choices=tuple(SENSOR_SCENARIOS))
    args = parser.parse_args(argv)
    started = time.perf_counter()
    payload = build_sensor_robustness_payload(
        pixel_m=args.pixel_m,
        scenario_names=tuple(args.scenario) if args.scenario else tuple(SENSOR_SCENARIOS),
        walk_limit=args.walk_limit,
    )
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"{args.out}: {payload['population']['sample_count']} walks · "  # type: ignore[index]
        f"{len(payload['scenarios'])} sensor scenarios · "  # type: ignore[arg-type]
        f"{time.perf_counter() - started:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
