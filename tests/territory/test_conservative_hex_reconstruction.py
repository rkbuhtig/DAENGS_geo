"""Cellophane의 보수적 표시 raster 복원 계약."""

import json
import math
from datetime import UTC, datetime, timedelta

import pytest

from app.features.territory.paint import NARROW_STEP, paint_sheet
from app.features.walk.facts import Segment
from app.features.walk.models import WalkFix
from scripts.spikes.territory_paint.conservative_hex_evaluation import (
    build_reconstruction_evaluation_payload,
)
from scripts.spikes.territory_paint.conservative_hex_reconstruction import (
    ReconstructionSpec,
    reconstruct_cellophane,
)
from scripts.spikes.territory_paint.continuous_hex_comparison import (
    RasterSpec,
    raster_metric_fields,
)

LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 9, 1, 9, tzinfo=UTC)


def _fix(east_m: float, seconds: float, chain_index: int = 0) -> WalkFix:
    lng = LNG + math.degrees(east_m / (6_378_137.0 * math.cos(math.radians(LAT))))
    return WalkFix(
        client_seq=round(seconds),
        chain_index=chain_index,
        at=START + timedelta(seconds=seconds),
        lat=LAT,
        lng=lng,
        accuracy_m=3.0,
        is_mock=True,
    )


def _segment(start_m: float, end_m: float, start_s: float, chain_index: int = 0) -> Segment:
    duration = abs(end_m - start_m)
    return Segment(
        a=_fix(start_m, start_s, chain_index),
        b=_fix(end_m, start_s + duration, chain_index),
        dt=duration,
        dist=duration,
        offset_m=0.0,
        moving=True,
        chain_index=chain_index,
    )


def _sheet(walk_id: str, segments: list[Segment], radius_u: float = 8.0):
    return paint_sheet(walk_id, START, segments, radius_u, NARROW_STEP)


@pytest.fixture(scope="module")
def evaluation_payload():
    return build_reconstruction_evaluation_payload(radius_units=(8.0,))


@pytest.mark.parametrize("method", ["piecewise", "local_blend"])
def test_reconstruction_preserves_each_sheet_mass_and_support(method):
    source = _sheet("walk-1", [_segment(0.0, 80.0, 0.0)])
    raster = RasterSpec(pixel_m=2.0, origin_lat=LAT, origin_lng=LNG)
    reconstructed = reconstruct_cellophane(
        source, raster, ReconstructionSpec(8.0, method)
    )

    assert reconstructed.mass_s == pytest.approx(sum(source.occupancy.values()), abs=1e-8)
    assert reconstructed.source_cell_count == len(source.occupancy)
    assert reconstructed.support_pixel_count >= len(reconstructed.occupancy)
    assert reconstructed.connected_components == 1
    assert all(value > 0 for value in reconstructed.occupancy.values())


def test_reconstruction_is_deterministic_and_method_changes_only_distribution():
    source = _sheet("walk-1", [_segment(0.0, 80.0, 0.0)])
    raster = RasterSpec(pixel_m=2.0, origin_lat=LAT, origin_lng=LNG)
    spec = ReconstructionSpec(8.0, "local_blend")
    first = reconstruct_cellophane(source, raster, spec)
    second = reconstruct_cellophane(source, raster, spec)
    raw = reconstruct_cellophane(source, raster, ReconstructionSpec(8.0, "piecewise"))

    assert first == second
    assert set(first.occupancy) == set(raw.occupancy)
    assert first.occupancy != raw.occupancy
    assert first.mass_s == pytest.approx(raw.mass_s, abs=1e-8)


def test_disconnected_chains_do_not_create_a_gap_bridge():
    source = _sheet(
        "gap",
        [
            _segment(-10_010.0, -10_000.0, 0.0, 0),
            _segment(10_000.0, 10_010.0, 20.0, 1),
        ],
    )
    raster = RasterSpec(pixel_m=2.0, origin_lat=LAT, origin_lng=LNG)
    reconstructed = reconstruct_cellophane(
        source, raster, ReconstructionSpec(8.0, "local_blend")
    )

    assert reconstructed.connected_components == 2
    assert reconstructed.occupancy.get(raster.pixel_at(LAT, LNG), 0.0) == 0.0
    assert reconstructed.support_evaluations < reconstructed.source_cell_count * 200


def test_metric_semantics_are_recomputed_after_per_walk_reconstruction():
    raster = RasterSpec(pixel_m=2.0, origin_lat=LAT, origin_lng=LNG)
    sheets = tuple(
        reconstruct_cellophane(
            source,
            raster,
            ReconstructionSpec(8.0, "local_blend"),
        )
        for source in (
            _sheet("a", [_segment(0.0, 60.0, 0.0)]),
            _sheet("b", [_segment(0.0, 30.0, 0.0)]),
        )
    )
    fields = raster_metric_fields(sheets)  # type: ignore[arg-type]

    assert math.fsum(fields["total_time"].values.values()) == pytest.approx(90.0)
    assert math.fsum(fields["time_utilization"].values.values()) == pytest.approx(1.0)
    assert math.fsum(fields["walk_utilization"].values.values()) == pytest.approx(1.0)
    assert all(0.0 <= value <= 1.0 for value in fields["visit_rate"].values.values())
    assert all(value >= 0.0 for value in fields["conditional_dwell"].values.values())


def test_population_evaluation_compares_a_b_c_without_storage_or_truth_claims(
    evaluation_payload,
):
    row = evaluation_payload["radius_comparisons"][0]
    encoded = json.dumps(evaluation_payload, sort_keys=True)

    assert evaluation_payload["population"]["sample_count"] == 30
    assert "not_truth" in evaluation_payload["reference_role"]
    assert "not_storage" in evaluation_payload["reconstruction_role"]
    assert row["mass"]["raw_absolute_error_s"] < 1e-8
    assert row["mass"]["reconstructed_absolute_error_s"] < 1e-8
    assert row["support"]["leakage_pixels"] == 0
    assert row["support"]["missing_pixels"] == 0
    assert row["support"]["raw_components"] == row["support"]["reconstructed_components"]
    assert set(row["raw_piecewise"]["metrics"]) == set(row["reconstructed"]["metrics"])
    assert all(not probe["bridged"] for probe in evaluation_payload["disconnected_chain_gap_probe"])
    assert '"truth"' not in encoded


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius_u": 0.0},
        {"radius_u": math.inf},
        {"radius_u": 8.0, "blend_reach_cells": 0.0},
        {"radius_u": 8.0, "method": "unknown"},
    ],
)
def test_invalid_reconstruction_contract_fails_at_boundary(kwargs):
    with pytest.raises(ValueError):
        ReconstructionSpec(**kwargs)
