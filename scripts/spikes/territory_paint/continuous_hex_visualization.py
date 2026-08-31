"""연속 원 reference와 Hex Cellophane을 실제 지도에서 비교할 상세 payload를 만든다.

    uv run python -m scripts.spikes.territory_paint.continuous_hex_visualization \
        --out continuous-hex-visualization.json

요약 수치는 ``continuous_hex_comparison``과 같은 계산 경로를 쓴다. 이 파일은 그 위에 연속
raster pixel 값, 서버에서 계산한 Hex polygon, 50·80·95% 경계만 더한다. 브라우저는 통계를
재계산하거나 육각형을 재구성하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.features.territory.paint import NARROW_STEP, paint_spec
from app.features.territory.spatial_stats import highest_mass_regions
from app.geo.cells import Cell, hex_boundary_latlng
from scripts.sim.walk.population import DEFAULT_POPULATION_ORIGIN, observe_population
from scripts.sim.walk.population_truth import build_population_truth
from scripts.spikes.territory_paint.continuous_hex_comparison import (
    DEFAULT_PIXEL_M,
    DEFAULT_RADIUS_UNITS,
    METRICS,
    Pixel,
    RasterMetricField,
    RasterSpec,
    hex_metric_fields,
    highest_pixel_mass_regions,
    radius_comparison,
    raster_metric_fields,
    rasterize_observation,
    repaint_observation,
)
from scripts.spikes.territory_paint.population_distribution import region_boundary_edges

VISUALIZATION_FORMAT_VERSION = 1
METRIC_LABELS = {
    "total_time": "총 관측 시간",
    "visit_rate": "산책당 방문률",
    "conditional_dwell": "방문당 체류",
    "time_utilization": "전체 시간 이용분포",
    "walk_utilization": "산책 동등 이용분포",
}


def _point_key(point: tuple[float, float]) -> tuple[float, float]:
    return round(point[0], 9), round(point[1], 9)


def pixel_region_boundary_edges(
    pixels: frozenset[Pixel],
    raster: RasterSpec,
) -> list[list[list[float]]]:
    """정사각 pixel 집합의 내부 공유 변을 제거하고 외곽 변만 지도 좌표로 낸다."""
    edges: dict[tuple[tuple[int, int], tuple[int, int]], tuple[tuple[int, int], tuple[int, int]]] = {}
    for pixel_x, pixel_y in sorted(pixels):
        corners = (
            (pixel_x, pixel_y),
            (pixel_x + 1, pixel_y),
            (pixel_x + 1, pixel_y + 1),
            (pixel_x, pixel_y + 1),
        )
        for start, end in zip(corners, (*corners[1:], corners[0]), strict=True):
            key = tuple(sorted((start, end)))
            if key in edges:
                del edges[key]
            else:
                edges[key] = (start, end)

    def latlng(vertex: tuple[int, int]) -> list[float]:
        lat, lng = raster.latlng_at_local(
            vertex[0] * raster.pixel_m,
            vertex[1] * raster.pixel_m,
        )
        return [lat, lng]

    return [[latlng(start), latlng(end)] for _key, (start, end) in sorted(edges.items())]


def _raster_bounds(
    pixels: set[Pixel], raster: RasterSpec
) -> tuple[dict[str, int], list[float]]:
    if not pixels:
        raise ValueError("시각화할 reference pixel이 없다")
    min_x = min(pixel[0] for pixel in pixels)
    max_x = max(pixel[0] for pixel in pixels)
    min_y = min(pixel[1] for pixel in pixels)
    max_y = max(pixel[1] for pixel in pixels)
    south, west = raster.latlng_at_local(min_x * raster.pixel_m, min_y * raster.pixel_m)
    north, east = raster.latlng_at_local(
        (max_x + 1) * raster.pixel_m,
        (max_y + 1) * raster.pixel_m,
    )
    return (
        {
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
            "width": max_x - min_x + 1,
            "height": max_y - min_y + 1,
        },
        [south, west, north, east],
    )


def _raster_payload(
    fields: dict[str, RasterMetricField],
    raster: RasterSpec,
) -> dict[str, object]:
    pixels = set(fields["total_time"].values)
    bounds, bbox = _raster_bounds(pixels, raster)
    rows = [
        {
            "x": pixel[0],
            "y": pixel[1],
            "values": {metric: fields[metric].values.get(pixel, 0.0) for metric in METRICS},
        }
        for pixel in sorted(pixels)
    ]
    regions = {
        metric: [
            {
                "target_mass": region.target_mass,
                "achieved_mass": region.achieved_mass,
                "pixel_count": len(region.pixels),
                "boundary_edges": pixel_region_boundary_edges(region.pixels, raster),
            }
            for region in highest_pixel_mass_regions(fields[metric])
        ]
        for metric in ("time_utilization", "walk_utilization")
    }
    return {
        "pixel_m": raster.pixel_m,
        "origin": [raster.origin_lat, raster.origin_lng],
        "bounds": bounds,
        "bbox": bbox,
        "pixels": rows,
        "metrics": {
            metric: {
                "label": METRIC_LABELS[metric],
                "unit": fields[metric].unit,
                "max_value": max(fields[metric].values.values(), default=0.0),
            }
            for metric in METRICS
        },
        "regions": regions,
    }


def _hex_payload(
    radius_u: float,
    fields,
    summary: dict[str, object],
) -> dict[str, object]:
    cells: set[Cell] = set(fields["total_time"].values)
    paint = paint_spec(radius_u, NARROW_STEP)
    rows = [
        {
            "id": f"{paint.grid_version}:{radius_u:g}:{cell[0]}:{cell[1]}",
            "q": cell[0],
            "r": cell[1],
            "boundary": [[lat, lng] for lat, lng in hex_boundary_latlng(*cell, radius_u)],
            "values": {metric: fields[metric].values.get(cell, 0.0) for metric in METRICS},
        }
        for cell in sorted(cells)
    ]
    regions = {
        metric: [
            {
                "target_mass": region.target_mass,
                "achieved_mass": region.achieved_mass,
                "cell_count": len(region.cells),
                "boundary_edges": region_boundary_edges(region.cells, radius_u),
            }
            for region in highest_mass_regions(fields[metric]).regions
        ]
        for metric in ("time_utilization", "walk_utilization")
    }
    return {
        "radius_u": radius_u,
        "ground_radius_m_at_origin": summary["ground_radius_m_at_origin"],
        "cell_area_m2_at_origin": summary["cell_area_m2_at_origin"],
        "paint_fp": paint.fingerprint,
        "cells": rows,
        "metrics": {
            metric: {
                "label": METRIC_LABELS[metric],
                "unit": fields[metric].unit,
                "max_value": max(fields[metric].values.values(), default=0.0),
            }
            for metric in METRICS
        },
        "regions": regions,
        "comparison": {
            "mass": summary["mass"],
            "support": summary["support"],
            "metrics": summary["metrics"],
            "mass_regions": summary["mass_regions"],
        },
    }


def build_visualization_payload(
    *,
    pixel_m: float = DEFAULT_PIXEL_M,
    radius_units: tuple[float, ...] = DEFAULT_RADIUS_UNITS,
) -> dict[str, object]:
    truth = build_population_truth()
    observation = observe_population(truth, sample_interval_s=5.0)
    raster = RasterSpec(pixel_m=pixel_m)
    reference_sheets = rasterize_observation(observation, raster)
    reference_fields = raster_metric_fields(reference_sheets)
    reference = _raster_payload(reference_fields, raster)

    radii = []
    all_points = [
        (reference["bbox"][0], reference["bbox"][1]),  # type: ignore[index]
        (reference["bbox"][2], reference["bbox"][3]),  # type: ignore[index]
    ]
    for radius_u in radius_units:
        sheets = repaint_observation(observation, radius_u)
        fields = hex_metric_fields(sheets, radius_u)
        summary = radius_comparison(
            observation,
            reference_sheets,
            reference_fields,
            radius_u,
            raster,
            sheets=sheets,
            fields=fields,
        )
        row = _hex_payload(radius_u, fields, summary)
        radii.append(row)
        all_points.extend(
            point
            for cell in row["cells"]  # type: ignore[union-attr]
            for point in cell["boundary"]  # type: ignore[index]
        )

    latitudes = [point[0] for point in all_points]
    longitudes = [point[1] for point in all_points]
    return {
        "format_version": VISUALIZATION_FORMAT_VERSION,
        "coordinate_order": "lat,lng",
        "home": list(DEFAULT_POPULATION_ORIGIN),
        "bbox": [min(latitudes), min(longitudes), max(latitudes), max(longitudes)],
        "population": {
            "generator_version": observation.generator_version,
            "run_id": observation.run_id,
            "sample_count": len(observation.walks),
        },
        "reference": reference,
        "radii": radii,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("continuous-hex-visualization.json"))
    parser.add_argument("--pixel-m", type=float, default=DEFAULT_PIXEL_M)
    args = parser.parse_args(argv)

    payload = build_visualization_payload(pixel_m=args.pixel_m)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"{args.out}: {payload['population']['sample_count']} walks · "  # type: ignore[index]
        f"{len(payload['reference']['pixels'])} raster pixels · "  # type: ignore[index,arg-type]
        f"{len(payload['radii'])} Hex radii"  # type: ignore[arg-type]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
