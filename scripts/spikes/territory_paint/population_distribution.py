"""30회 Cellophane의 다섯 통계와 50·80·95% 영역을 지도 payload로 만든다.

    uv run python -m scripts.spikes.territory_paint.population_distribution \
        --out cellophane-distribution.json
    DAENGS_DEV_CONSOLE=true uv run uvicorn app.main:app --reload
    # http://127.0.0.1:8000/cellophane-distribution

출력에는 evaluator-only branch·hold·seed가 없다. 관측을 통과한 Cellophane과 통계 영수증만
직렬화하며 좌표는 Naver Maps SDK가 바로 읽는 ``[lat, lng]`` 순서다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from app.features.territory.geojson import spatial_cell_id
from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import NARROW_STEP, paint_spec
from app.features.territory.spatial_stats import (
    SpatialField,
    highest_mass_regions,
    spatial_field,
)
from app.geo.cells import Cell, hex_boundary_latlng
from scripts.sim.walk.population import DEFAULT_POPULATION_ORIGIN, observe_population
from scripts.sim.walk.population_truth import build_population_truth

DISTRIBUTION_FORMAT_VERSION = 1
RADIUS_U = 8.0
METRICS = (
    "visit_rate",
    "total_time",
    "conditional_dwell",
    "time_utilization",
    "walk_utilization",
)
METRIC_LABELS = {
    "visit_rate": "산책당 방문률",
    "total_time": "총 관측 시간",
    "conditional_dwell": "방문당 체류",
    "time_utilization": "전체 시간 이용분포",
    "walk_utilization": "산책 동등 이용분포",
}


def _point_key(point: tuple[float, float]) -> tuple[float, float]:
    return round(point[0], 9), round(point[1], 9)


def region_boundary_edges(cells: frozenset[Cell], radius_u: float) -> list[list[list[float]]]:
    """영역 내부의 공유 변은 지우고 바깥 변만 ``[[lat,lng],[lat,lng]]``로 남긴다."""
    edges: dict[
        tuple[tuple[float, float], tuple[float, float]],
        tuple[tuple[float, float], tuple[float, float]],
    ] = {}
    for q, r in sorted(cells):
        ring = hex_boundary_latlng(q, r, radius_u)
        for start, end in zip(ring, (*ring[1:], ring[0]), strict=True):
            start_key, end_key = _point_key(start), _point_key(end)
            key = tuple(sorted((start_key, end_key)))
            if key in edges:
                del edges[key]
            else:
                edges[key] = (start_key, end_key)
    return [
        [[start[0], start[1]], [end[0], end[1]]] for _key, (start, end) in sorted(edges.items())
    ]


def _metric_receipt(field: SpatialField) -> dict[str, object]:
    denominator: float | str | None
    denominator = "per_cell" if isinstance(field.denominator, dict) else field.denominator
    return {
        "label": METRIC_LABELS[field.metric],
        "unit": field.unit,
        "normalization": field.normalization,
        "selected": field.selected,
        "contributing": field.contributing,
        "total": field.total,
        "denominator": denominator,
        "min_peak": field.min_peak,
        "paint_fp": field.paint_fp,
        "spec_fp": field.spec.fingerprint(),
        "max_value": max(field.values.values(), default=0.0),
    }


def build_distribution_payload() -> dict[str, object]:
    truth = build_population_truth()
    observation = observe_population(truth, radius_u=RADIUS_U)
    paint = paint_spec(RADIUS_U, NARROW_STEP)
    projection = Projection.from_paint_spec(paint)
    fields = {
        metric: spatial_field(
            observation.sheets,
            LayerSpec(Selector(), Aggregation(metric), projection),
        )
        for metric in METRICS
    }
    all_cells = sorted({cell for field in fields.values() for cell in field.values})

    rows = []
    all_points = []
    for cell in all_cells:
        q, r = cell
        boundary = [[lat, lng] for lat, lng in hex_boundary_latlng(q, r, RADIUS_U)]
        all_points.extend(boundary)
        denominators = {
            metric: field.denominator[cell]
            for metric, field in fields.items()
            if isinstance(field.denominator, dict) and cell in field.denominator
        }
        rows.append(
            {
                "cell_id": spatial_cell_id(paint.grid_version, RADIUS_U, cell),
                "q": q,
                "r": r,
                "boundary": boundary,
                "values": {metric: field.values.get(cell, 0.0) for metric, field in fields.items()},
                "numerators": {
                    metric: field.numerators.get(cell, 0.0) for metric, field in fields.items()
                },
                "denominators": denominators,
            }
        )

    regions = {}
    for metric in ("time_utilization", "walk_utilization"):
        region_set = highest_mass_regions(fields[metric])
        regions[metric] = [
            {
                "target_mass": region.target_mass,
                "achieved_mass": region.achieved_mass,
                "cutoff_value": region.cutoff_value,
                "cell_count": len(region.cells),
                "cell_ids": [
                    spatial_cell_id(paint.grid_version, RADIUS_U, cell)
                    for cell in sorted(region.cells)
                ],
                "boundary_edges": region_boundary_edges(region.cells, RADIUS_U),
            }
            for region in region_set.regions
        ]

    latitudes = [point[0] for point in all_points]
    longitudes = [point[1] for point in all_points]
    return {
        "format_version": DISTRIBUTION_FORMAT_VERSION,
        "coordinate_order": "lat,lng",
        "home": list(DEFAULT_POPULATION_ORIGIN),
        "bbox": [min(latitudes), min(longitudes), max(latitudes), max(longitudes)],
        "sample_count": len(observation.sheets),
        "cell_count": len(all_cells),
        "paint": {
            "paint_fp": paint.fingerprint,
            "paint_version": paint.paint_version,
            "grid_version": paint.grid_version,
            "radius_u": paint.radius_u,
            "profile_name": paint.profile_name,
            "profile_fp": paint.profile_fp,
            "sample_step_m": paint.sample_step_m,
        },
        "metrics": {metric: _metric_receipt(field) for metric, field in fields.items()},
        "regions": regions,
        "cells": rows,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("cellophane-distribution.json"))
    args = parser.parse_args(argv)

    payload = build_distribution_payload()
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    mass = math.fsum(
        row["values"]["walk_utilization"]  # type: ignore[index]
        for row in payload["cells"]  # type: ignore[union-attr]
    )
    print(
        f"{args.out}: {payload['sample_count']} walks · {payload['cell_count']} cells · "
        f"U_walk mass {mass:.9f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
