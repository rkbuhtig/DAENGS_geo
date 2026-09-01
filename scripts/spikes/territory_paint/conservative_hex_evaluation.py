"""continuous reference / raw Hex / 보수적 복원 Field를 같은 raster에서 비교한다.

    uv run python -m scripts.spikes.territory_paint.conservative_hex_evaluation \
        --out conservative-hex-evaluation.json

continuous brush는 완벽한 센서와 고정 붓을 사용한 평가 기준이지 실제 동선의 truth가 아니다.
복원 raster도 영구 자료나 통계 입력이 아니라 Cellophane의 사용자 표시 후보를 검산하는 표면이다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from app.features.territory.paint import NARROW_STEP, paint_sheet
from scripts.sim.walk.population import observe_population
from scripts.sim.walk.population_truth import build_population_truth
from scripts.spikes.territory_paint.conservative_hex_reconstruction import (
    ReconstructionSpec,
    reconstruct_cellophane,
    reconstruct_cellophanes,
)
from scripts.spikes.territory_paint.continuous_hex_comparison import (
    DEFAULT_PIXEL_M,
    DEFAULT_RADIUS_UNITS,
    METRICS,
    Pixel,
    RasterMetricField,
    RasterSpec,
    _gap_segment,
    highest_pixel_mass_regions,
    raster_metric_fields,
    rasterize_observation,
    repaint_observation,
)

RECONSTRUCTION_EVALUATION_FORMAT_VERSION = 1
MASS_METRICS = {"total_time", "time_utilization", "walk_utilization"}


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil(quantile * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def _boundary(pixels: set[Pixel]) -> set[Pixel]:
    neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1))
    return {
        pixel
        for pixel in pixels
        if any((pixel[0] + dx, pixel[1] + dy) not in pixels for dx, dy in neighbours)
    }


def _directed_boundary_distances(
    source: set[Pixel], target: set[Pixel], pixel_m: float
) -> list[float]:
    source_boundary = _boundary(source)
    target_boundary = _boundary(target)
    if not source_boundary or not target_boundary:
        return [] if source_boundary == target_boundary else [math.inf]
    return [
        min(math.hypot(left[0] - right[0], left[1] - right[1]) for right in target_boundary)
        * pixel_m
        for left in source_boundary
    ]


def _boundary_receipt(first: set[Pixel], second: set[Pixel], pixel_m: float) -> dict[str, float]:
    forward = _directed_boundary_distances(first, second, pixel_m)
    reverse = _directed_boundary_distances(second, first, pixel_m)
    both = forward + reverse
    return {
        "mean_symmetric_m": math.fsum(both) / len(both) if both else 0.0,
        "p95_symmetric_m": _percentile(both, 0.95),
        "reference_to_candidate_mean_m": math.fsum(forward) / len(forward) if forward else 0.0,
        "candidate_to_reference_mean_m": math.fsum(reverse) / len(reverse) if reverse else 0.0,
    }


def _iou(first: set[Pixel], second: set[Pixel]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 1.0


def _component_count(pixels: set[Pixel]) -> int:
    pending_pixels = set(pixels)
    count = 0
    neighbours = tuple(
        (dx, dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if dx or dy
    )
    while pending_pixels:
        count += 1
        stack = [pending_pixels.pop()]
        while stack:
            pixel = stack.pop()
            for dx, dy in neighbours:
                neighbour = (pixel[0] + dx, pixel[1] + dy)
                if neighbour in pending_pixels:
                    pending_pixels.remove(neighbour)
                    stack.append(neighbour)
    return count


def compare_raster_fields(
    reference: RasterMetricField,
    candidate: RasterMetricField,
) -> dict[str, float | int | str]:
    """지표 의미에 맞춰 두 common-raster field를 비교한다."""
    if reference.metric != candidate.metric:
        raise ValueError("서로 다른 metric은 비교할 수 없다")
    pixels = set(reference.values) | set(candidate.values)
    pairs = [
        (reference.values.get(pixel, 0.0), candidate.values.get(pixel, 0.0))
        for pixel in pixels
    ]
    active = [(left, right) for left, right in pairs if left > 0 or right > 0]
    absolute = [abs(left - right) for left, right in active]
    receipt: dict[str, float | int | str] = {
        "active_pixels": len(active),
        "mean_absolute_error": math.fsum(absolute) / len(absolute) if absolute else 0.0,
        "max_absolute_error": max(absolute, default=0.0),
    }
    if reference.metric not in MASS_METRICS:
        receipt["comparison"] = "pointwise_metric_on_common_raster"
        return receipt

    reference_total = math.fsum(reference.values.values())
    candidate_total = math.fsum(candidate.values.values())
    receipt.update(
        {
            "comparison": "mass_on_common_raster",
            "reference_total": reference_total,
            "candidate_total": candidate_total,
            "total_absolute_error": abs(candidate_total - reference_total),
            "normalized_l1": (
                math.fsum(
                    abs(left / reference_total - right / candidate_total)
                    for left, right in pairs
                )
                if reference_total > 0 and candidate_total > 0
                else 0.0
            ),
        }
    )
    return receipt


def _mass_region_receipts(
    reference: RasterMetricField,
    candidate: RasterMetricField,
    raster: RasterSpec,
) -> list[dict[str, object]]:
    reference_regions = highest_pixel_mass_regions(reference)
    candidate_regions = highest_pixel_mass_regions(candidate)
    rows = []
    for reference_region, candidate_region in zip(
        reference_regions, candidate_regions, strict=True
    ):
        reference_pixels = set(reference_region.pixels)
        candidate_pixels = set(candidate_region.pixels)
        rows.append(
            {
                "target_mass": reference_region.target_mass,
                "reference_achieved_mass": reference_region.achieved_mass,
                "candidate_achieved_mass": candidate_region.achieved_mass,
                "area_iou": _iou(reference_pixels, candidate_pixels),
                "reference_mass_captured_by_candidate": math.fsum(
                    reference.values.get(pixel, 0.0) for pixel in candidate_pixels
                ),
                "candidate_mass_captured_by_reference": math.fsum(
                    candidate.values.get(pixel, 0.0) for pixel in reference_pixels
                ),
                "boundary": _boundary_receipt(
                    reference_pixels, candidate_pixels, raster.pixel_m
                ),
            }
        )
    return rows


def radius_reconstruction_comparison(
    observation,
    reference_fields: dict[str, RasterMetricField],
    radius_u: float,
    raster: RasterSpec,
    *,
    blend_reach_cells: float = 1.75,
) -> dict[str, object]:
    sheets = repaint_observation(observation, radius_u)
    raw_sheets = reconstruct_cellophanes(
        sheets, raster, ReconstructionSpec(radius_u, "piecewise")
    )
    reconstructed_sheets = reconstruct_cellophanes(
        sheets,
        raster,
        ReconstructionSpec(radius_u, "local_blend", blend_reach_cells),
    )
    raw_fields = raster_metric_fields(raw_sheets)  # type: ignore[arg-type]
    reconstructed_fields = raster_metric_fields(reconstructed_sheets)  # type: ignore[arg-type]
    raw_support = set(raw_fields["total_time"].values)
    reconstructed_support = set(reconstructed_fields["total_time"].values)
    source_mass = math.fsum(sheet.occupancy[cell] for sheet in sheets for cell in sheet.occupancy)
    raw_mass = math.fsum(sheet.mass_s for sheet in raw_sheets)
    reconstructed_mass = math.fsum(sheet.mass_s for sheet in reconstructed_sheets)
    return {
        "radius_u": radius_u,
        "reconstruction": {
            "method": "local_blend",
            "blend_reach_cells": blend_reach_cells,
            "support_policy": "occupied_hex_union_per_connected_component",
        },
        "source_cell_count": sum(len(sheet.occupancy) for sheet in sheets),
        "mass": {
            "source_s": source_mass,
            "raw_piecewise_s": raw_mass,
            "reconstructed_s": reconstructed_mass,
            "raw_absolute_error_s": abs(raw_mass - source_mass),
            "reconstructed_absolute_error_s": abs(reconstructed_mass - source_mass),
        },
        "support": {
            "raw_pixels": len(raw_support),
            "reconstructed_pixels": len(reconstructed_support),
            "leakage_pixels": len(reconstructed_support - raw_support),
            "missing_pixels": len(raw_support - reconstructed_support),
            "raw_components": _component_count(raw_support),
            "reconstructed_components": _component_count(reconstructed_support),
        },
        "evaluation_work": {
            "raw_support": sum(sheet.support_evaluations for sheet in raw_sheets),
            "raw_piecewise": sum(sheet.weight_evaluations for sheet in raw_sheets),
            "reconstructed_support": sum(
                sheet.support_evaluations for sheet in reconstructed_sheets
            ),
            "reconstructed": sum(sheet.weight_evaluations for sheet in reconstructed_sheets),
        },
        "raw_piecewise": {
            "metrics": {
                metric: compare_raster_fields(reference_fields[metric], raw_fields[metric])
                for metric in METRICS
            },
            "mass_regions": {
                metric: _mass_region_receipts(reference_fields[metric], raw_fields[metric], raster)
                for metric in ("time_utilization", "walk_utilization")
            },
        },
        "reconstructed": {
            "metrics": {
                metric: compare_raster_fields(
                    reference_fields[metric], reconstructed_fields[metric]
                )
                for metric in METRICS
            },
            "mass_regions": {
                metric: _mass_region_receipts(
                    reference_fields[metric], reconstructed_fields[metric], raster
                )
                for metric in ("time_utilization", "walk_utilization")
            },
        },
    }


def _reconstructed_gap_probe(raster: RasterSpec, radius_units: tuple[float, ...]) -> list[dict[str, object]]:
    segments = [_gap_segment(-60.0, 0.0, 0), _gap_segment(60.0, 11.0, 1)]
    rows = []
    for radius_u in radius_units:
        sheet = paint_sheet(
            "reconstruction-gap-probe", segments[0].a.at, segments, radius_u, NARROW_STEP
        )
        reconstructed = reconstruct_cellophane(
            sheet, raster, ReconstructionSpec(radius_u, "local_blend")
        )
        # RasterSpec 원점은 population origin이므로 local (0, 0)을 포함하는 pixel을 직접 쓴다.
        midpoint_pixel = raster.pixel_at(raster.origin_lat, raster.origin_lng)
        midpoint_s = reconstructed.occupancy.get(midpoint_pixel, 0.0)
        rows.append(
            {
                "radius_u": radius_u,
                "midpoint_occupancy_s": midpoint_s,
                "bridged": midpoint_s > 0,
                "connected_components": reconstructed.connected_components,
            }
        )
    return rows


def build_reconstruction_evaluation_payload(
    *,
    pixel_m: float = DEFAULT_PIXEL_M,
    radius_units: tuple[float, ...] = DEFAULT_RADIUS_UNITS,
    blend_reach_cells: float = 1.75,
) -> dict[str, object]:
    if not radius_units or any(not math.isfinite(value) or value <= 0 for value in radius_units):
        raise ValueError("radius_units는 비어 있지 않은 양수 목록이어야 한다")
    observation = observe_population(build_population_truth(), sample_interval_s=5.0)
    raster = RasterSpec(pixel_m=pixel_m)
    reference_fields = raster_metric_fields(rasterize_observation(observation, raster))
    return {
        "format_version": RECONSTRUCTION_EVALUATION_FORMAT_VERSION,
        "reference_role": "perfect_sensor_continuous_brush_evaluation_reference_not_truth",
        "reconstruction_role": "ephemeral_display_candidate_not_storage_or_statistics_source",
        "population": {
            "generator_version": observation.generator_version,
            "run_id": observation.run_id,
            "sample_count": len(observation.walks),
        },
        "raster": {"pixel_m": raster.pixel_m},
        "radius_comparisons": [
            radius_reconstruction_comparison(
                observation,
                reference_fields,
                radius_u,
                raster,
                blend_reach_cells=blend_reach_cells,
            )
            for radius_u in radius_units
        ],
        "disconnected_chain_gap_probe": _reconstructed_gap_probe(raster, radius_units),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("conservative-hex-evaluation.json"))
    parser.add_argument("--pixel-m", type=float, default=DEFAULT_PIXEL_M)
    parser.add_argument("--blend-reach-cells", type=float, default=1.75)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    payload = build_reconstruction_evaluation_payload(
        pixel_m=args.pixel_m,
        blend_reach_cells=args.blend_reach_cells,
    )
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"{args.out}: {payload['population']['sample_count']} walks · "  # type: ignore[index]
        f"{len(payload['radius_comparisons'])} radii · "  # type: ignore[arg-type]
        f"{time.perf_counter() - started:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
