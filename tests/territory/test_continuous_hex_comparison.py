"""연속 원 reference와 Hex Cellophane 비교 evaluator 계약."""

import json
import math
from datetime import UTC, datetime, timedelta

import pytest

from app.features.territory.continuous_brush import continuous_brush_field
from app.features.territory.paint import flat
from app.features.walk.facts import Segment
from app.features.walk.models import WalkFix
from scripts.spikes.territory_paint.continuous_hex_comparison import (
    DEFAULT_RADIUS_UNITS,
    RasterMetricField,
    RasterSheet,
    RasterSpec,
    build_comparison_payload,
    highest_pixel_mass_regions,
    raster_metric_fields,
    rasterize_continuous_field,
)

LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 8, 31, 9, tzinfo=UTC)


def _fix(east_m: float, seconds: float) -> WalkFix:
    lng = LNG + math.degrees(east_m / (6_378_137.0 * math.cos(math.radians(LAT))))
    return WalkFix(
        client_seq=round(seconds),
        chain_index=0,
        at=START + timedelta(seconds=seconds),
        lat=LAT,
        lng=lng,
        accuracy_m=3.0,
        is_mock=True,
    )


@pytest.fixture(scope="module")
def comparison_payload():
    return build_comparison_payload()


def test_raster_measurement_canvas_preserves_continuous_time_mass():
    segment = Segment(
        a=_fix(0.0, 0.0),
        b=_fix(40.0, 40.0),
        dt=40.0,
        dist=40.0,
        offset_m=0.0,
        moving=True,
        chain_index=0,
    )
    field = continuous_brush_field([segment], flat(10.0), step_m=2.0)
    sheet = rasterize_continuous_field("walk-1", field, RasterSpec(pixel_m=2.0))

    assert sheet.mass_s == pytest.approx(40.0)
    assert sheet.source_segment_s == pytest.approx(40.0)
    assert sheet.raw_kernel_integral_ratio == pytest.approx(1.0, rel=0.08)
    assert sheet.dab_count == 20


def test_raster_statistics_use_the_same_five_metric_definitions_as_cellophane():
    sheets = (
        RasterSheet("a", {(0, 0): 6.0, (1, 0): 4.0}, {(0, 0): 1.0, (1, 0): 0.5}, 10.0, 2, 2, 1.0),
        RasterSheet("b", {(0, 0): 20.0}, {(0, 0): 1.0}, 20.0, 1, 1, 1.0),
    )
    fields = raster_metric_fields(sheets)

    assert set(fields) == {
        "total_time", "visit_rate", "conditional_dwell", "time_utilization", "walk_utilization"
    }
    assert fields["total_time"].values == {(0, 0): 26.0, (1, 0): 4.0}
    assert fields["visit_rate"].values == {(0, 0): 1.0, (1, 0): 0.5}
    assert fields["conditional_dwell"].values == {(0, 0): 13.0, (1, 0): 4.0}
    assert fields["time_utilization"].values[(0, 0)] == pytest.approx(26 / 30)
    assert fields["walk_utilization"].values[(0, 0)] == pytest.approx(0.8)


def test_pixel_mass_regions_keep_equal_cutoff_pixels_together():
    field = RasterMetricField(
        "time_utilization", {(0, 0): 0.4, (1, 0): 0.3, (2, 0): 0.3}, 1, 1, "share"
    )
    region = highest_pixel_mass_regions(field, (0.5,))[0]

    assert region.achieved_mass == pytest.approx(1.0)
    assert region.pixels == frozenset({(0, 0), (1, 0), (2, 0)})


def test_population_comparison_conserves_mass_and_measures_all_radii(comparison_payload):
    reference = comparison_payload["reference"]
    comparisons = comparison_payload["radius_comparisons"]

    assert comparison_payload["population"]["sample_count"] == 30
    assert reference["mass_absolute_error_s"] < 1e-8
    assert reference["raw_kernel_integral_ratio"] == pytest.approx(1.0, rel=0.03)
    assert [row["radius_u"] for row in comparisons] == list(DEFAULT_RADIUS_UNITS)
    for row in comparisons:
        assert row["mass"]["absolute_error_s"] < 1e-8
        assert 0 <= row["support"]["sampled_area_iou"] <= 1
        assert set(row["metrics"]) == {
            "total_time", "visit_rate", "conditional_dwell", "time_utilization", "walk_utilization"
        }
        for metric in ("time_utilization", "walk_utilization"):
            assert 0 <= row["metrics"][metric]["normalized_l1"] <= 2
            assert [region["target_mass"] for region in row["mass_regions"][metric]] == [0.5, 0.8, 0.95]
            assert all(0 <= region["area_iou"] <= 1 for region in row["mass_regions"][metric])


def test_finer_hex_radius_is_closer_to_the_continuous_reference(comparison_payload):
    fine, middle, coarse = comparison_payload["radius_comparisons"]

    assert fine["support"]["sampled_area_iou"] > middle["support"]["sampled_area_iou"]
    assert middle["support"]["sampled_area_iou"] > coarse["support"]["sampled_area_iou"]
    assert fine["metrics"]["time_utilization"]["normalized_l1"] < middle["metrics"]["time_utilization"]["normalized_l1"]
    assert middle["metrics"]["time_utilization"]["normalized_l1"] < coarse["metrics"]["time_utilization"]["normalized_l1"]


def test_sensor_interval_and_disconnected_gap_are_reported_without_latent_labels(comparison_payload):
    sensitivity = comparison_payload["sensor_interval_sensitivity"]
    gap = comparison_payload["disconnected_chain_gap_probe"]
    encoded = json.dumps(comparison_payload, sort_keys=True)

    assert [row["sample_interval_s"] for row in sensitivity] == [1.0, 5.0, 10.0]
    assert all(row["sensor_kind"] == "perfect" for row in sensitivity)
    assert all(0 <= row["time_utilization_l1_from_5s"] <= 2 for row in sensitivity)
    assert gap["continuous_bridged"] is False
    assert all(row["bridged"] is False for row in gap["hex"])
    assert all(label not in encoded for label in ('"branch"', '"hold"', '"seed"'))


@pytest.mark.parametrize("pixel_m", [0.0, -1.0, math.inf])
def test_invalid_raster_resolution_fails_at_the_boundary(pixel_m):
    with pytest.raises(ValueError):
        RasterSpec(pixel_m=pixel_m)
