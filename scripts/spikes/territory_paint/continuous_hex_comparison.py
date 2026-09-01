"""같은 canonical 산책을 연속 원 field와 Hex Cellophane에 투영해 수치로 비교한다.

정사각 raster는 새 저장 형식이 아니다. grid-free continuous brush를 유한 면적으로 적분하고
Hex의 piecewise-constant 값을 같은 위치에서 읽기 위한 evaluator-only 측정 캔버스다.

    uv run python -m scripts.spikes.territory_paint.continuous_hex_comparison \
        --out continuous-hex-comparison.json

출력은 30회 관측 산책의 다섯 통계, support 면적, 50·80·95% 질량 영역, Hex 반지름
4·8·12u 민감도와 perfect sensor 수집 간격 민감도를 담는다. 생성기의 branch·hold·seed 같은
latent label은 싣지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.features.territory.continuous_brush import (
    ContinuousBrushField,
    continuous_brush_field,
)
from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import NARROW_STEP, Cellophane, paint_sheet, paint_spec
from app.features.territory.spatial_stats import (
    DEFAULT_MASS_LEVELS,
    SpatialField,
    highest_mass_regions,
    spatial_field,
)
from app.features.walk.facts import Segment
from app.features.walk.models import WalkFix
from app.geo.cells import (
    cell_area_m2,
    hex_boundary_latlng,
    hex_cell,
    inverse_mercator,
    mercator,
    metres_per_unit,
)
from scripts.sim.walk.population import (
    DEFAULT_POPULATION_ORIGIN,
    PopulationObservation,
    observe_population,
)
from scripts.sim.walk.population_truth import build_population_truth
from scripts.sim.walk.sensor import local_xy_to_latlng

COMPARISON_FORMAT_VERSION = 1
DEFAULT_PIXEL_M = 4.0
DEFAULT_RADIUS_UNITS = (4.0, 8.0, 12.0)
DEFAULT_SAMPLE_INTERVALS_S = (1.0, 5.0, 10.0)
METRICS = (
    "total_time",
    "visit_rate",
    "conditional_dwell",
    "time_utilization",
    "walk_utilization",
)

Pixel = tuple[int, int]


@dataclass(frozen=True)
class RasterSpec:
    """연속 field를 적분할 evaluator-only 정사각 측정 캔버스."""

    pixel_m: float = DEFAULT_PIXEL_M
    origin_lat: float = DEFAULT_POPULATION_ORIGIN[0]
    origin_lng: float = DEFAULT_POPULATION_ORIGIN[1]

    def __post_init__(self) -> None:
        if not math.isfinite(self.pixel_m) or self.pixel_m <= 0:
            raise ValueError("pixel_m은 유한한 양수여야 한다")
        if not -85 <= self.origin_lat <= 85 or not -180 <= self.origin_lng <= 180:
            raise ValueError("raster origin이 Web Mercator 범위 밖이다")

    @property
    def pixel_area_m2(self) -> float:
        return self.pixel_m**2

    @property
    def _origin_xy(self) -> tuple[float, float]:
        return mercator(self.origin_lat, self.origin_lng)

    @property
    def _ground_scale(self) -> float:
        return metres_per_unit(self.origin_lat)

    def local_xy(self, lat: float, lng: float) -> tuple[float, float]:
        x, y = mercator(lat, lng)
        origin_x, origin_y = self._origin_xy
        scale = self._ground_scale
        return (x - origin_x) * scale, (y - origin_y) * scale

    def pixel_at(self, lat: float, lng: float) -> Pixel:
        east, north = self.local_xy(lat, lng)
        return math.floor(east / self.pixel_m), math.floor(north / self.pixel_m)

    def centre_xy(self, pixel: Pixel) -> tuple[float, float]:
        return (pixel[0] + 0.5) * self.pixel_m, (pixel[1] + 0.5) * self.pixel_m

    def centre_latlng(self, pixel: Pixel) -> tuple[float, float]:
        east, north = self.centre_xy(pixel)
        return self.latlng_at_local(east, north)

    def latlng_at_local(self, east_m: float, north_m: float) -> tuple[float, float]:
        """측정 캔버스의 local ground-metre 좌표를 지도 좌표로 되돌린다."""
        origin_x, origin_y = self._origin_xy
        scale = self._ground_scale
        return inverse_mercator(origin_x + east_m / scale, origin_y + north_m / scale)


@dataclass(frozen=True)
class RasterSheet:
    """한 continuous field를 raster에 질량 보존형으로 적분한 측정 결과."""

    walk_id: str
    occupancy: dict[Pixel, float]
    peak: dict[Pixel, float]
    source_segment_s: float
    dab_count: int
    stamp_evaluations: int
    raw_kernel_integral_ratio: float

    @property
    def mass_s(self) -> float:
        return math.fsum(self.occupancy.values())


@dataclass(frozen=True)
class RasterMetricField:
    metric: str
    values: dict[Pixel, float]
    selected: int
    contributing: int
    unit: str


@dataclass(frozen=True)
class PixelMassRegion:
    target_mass: float
    achieved_mass: float
    cutoff_value: float | None
    pixels: frozenset[Pixel]


def rasterize_continuous_field(
    walk_id: str,
    field: ContinuousBrushField,
    raster: RasterSpec,
) -> RasterSheet:
    """dab마다 pixel-centre kernel을 적분하고 합을 1로 다시 맞춰 시간을 보존한다.

    `raw_kernel_integral_ratio`는 재정규화 전 사각 적분이 해석적 원 kernel 면적에 얼마나
    근접했는지 보여 준다. occupancy 자체는 각 dab을 정규화하므로 source seconds를 정확히
    보존한다.
    """
    occupancy: dict[Pixel, float] = {}
    peak: dict[Pixel, float] = {}
    raw_integral_s = 0.0
    evaluations = 0
    reach = field.profile.reach_m
    margin = math.ceil(reach / raster.pixel_m) + 1

    for dab in field.dabs:
        east, north = raster.local_xy(dab.lat, dab.lng)
        home = (math.floor(east / raster.pixel_m), math.floor(north / raster.pixel_m))
        stamp: list[tuple[Pixel, float]] = []
        for pixel_x in range(home[0] - margin, home[0] + margin + 1):
            for pixel_y in range(home[1] - margin, home[1] + margin + 1):
                evaluations += 1
                centre_east, centre_north = raster.centre_xy((pixel_x, pixel_y))
                distance = math.hypot(centre_east - east, centre_north - north)
                weight = field.profile.weight_at(distance)
                if weight > 0:
                    stamp.append(((pixel_x, pixel_y), weight))
        if not stamp:
            stamp = [(home, field.profile.weights[0])]
        weight_sum = math.fsum(weight for _, weight in stamp)
        raw_integral_s += (
            dab.mass_s * weight_sum * raster.pixel_area_m2 / field.kernel_area_m2
        )
        for pixel, weight in stamp:
            occupancy[pixel] = occupancy.get(pixel, 0.0) + dab.mass_s * weight / weight_sum
            peak[pixel] = max(peak.get(pixel, 0.0), weight)

    source_s = field.source_segment_s
    ratio = raw_integral_s / source_s if source_s else 1.0
    result = RasterSheet(
        walk_id=walk_id,
        occupancy=occupancy,
        peak=peak,
        source_segment_s=source_s,
        dab_count=len(field.dabs),
        stamp_evaluations=evaluations,
        raw_kernel_integral_ratio=ratio,
    )
    if not math.isclose(result.mass_s, source_s, rel_tol=1e-12, abs_tol=1e-8):
        raise RuntimeError("continuous raster가 source Segment 시간을 보존하지 못했다")
    return result


def rasterize_observation(
    observation: PopulationObservation,
    raster: RasterSpec,
) -> tuple[RasterSheet, ...]:
    return tuple(
        rasterize_continuous_field(
            walk.observed.session_id,
            continuous_brush_field(list(walk.computed.segments), NARROW_STEP),
            raster,
        )
        for walk in observation.walks
    )


def raster_metric_fields(
    sheets: tuple[RasterSheet, ...],
    *,
    min_peak: float = 0.0,
) -> dict[str, RasterMetricField]:
    """기존 spatial_stats와 같은 다섯 정의를 raster sheet에 적용한다."""
    if not math.isfinite(min_peak) or not 0 <= min_peak <= 1:
        raise ValueError("min_peak는 0 이상 1 이하의 유한한 값이어야 한다")
    if min_peak > 0 and any(
        not getattr(sheet, "supports_peak_threshold", True) for sheet in sheets
    ):
        raise ValueError("표시용 복원 raster는 min_peak=0만 지원한다")
    total_time: dict[Pixel, float] = {}
    visits: dict[Pixel, float] = {}
    walk_shares: dict[Pixel, float] = {}
    contributing = 0
    for sheet in sheets:
        mass = sheet.mass_s
        if mass > 0:
            contributing += 1
        for pixel, amount in sheet.occupancy.items():
            if sheet.peak.get(pixel, 0.0) < min_peak:
                continue
            total_time[pixel] = total_time.get(pixel, 0.0) + amount
            visits[pixel] = visits.get(pixel, 0.0) + 1.0
            if mass > 0:
                walk_shares[pixel] = walk_shares.get(pixel, 0.0) + amount / mass

    selected = len(sheets)
    total_mass = math.fsum(total_time.values())
    fields = {
        "total_time": RasterMetricField(
            "total_time", total_time, selected, contributing, "s"
        ),
        "visit_rate": RasterMetricField(
            "visit_rate",
            {pixel: count / selected for pixel, count in visits.items()} if selected else {},
            selected,
            selected,
            "ratio",
        ),
        "conditional_dwell": RasterMetricField(
            "conditional_dwell",
            {pixel: total_time[pixel] / visits[pixel] for pixel in total_time},
            selected,
            contributing,
            "s/visited_walk",
        ),
        "time_utilization": RasterMetricField(
            "time_utilization",
            ({pixel: value / total_mass for pixel, value in total_time.items()}
             if total_mass else {}),
            selected,
            contributing,
            "share",
        ),
        "walk_utilization": RasterMetricField(
            "walk_utilization",
            ({pixel: value / contributing for pixel, value in walk_shares.items()}
             if contributing else {}),
            selected,
            contributing,
            "share",
        ),
    }
    return fields


def highest_pixel_mass_regions(
    field: RasterMetricField,
    levels: tuple[float, ...] = DEFAULT_MASS_LEVELS,
) -> tuple[PixelMassRegion, ...]:
    if field.metric not in {"time_utilization", "walk_utilization"}:
        raise ValueError("질량 영역은 utilization field만 지원한다")
    if tuple(sorted(set(levels))) != levels or any(not 0 < level <= 1 for level in levels):
        raise ValueError("질량 영역 level은 중복 없이 오름차순이어야 한다")
    total = math.fsum(field.values.values())
    if not field.values:
        return tuple(PixelMassRegion(level, 0.0, None, frozenset()) for level in levels)
    if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("raster utilization 총질량은 1이어야 한다")

    ranked = sorted(field.values.items(), key=lambda item: (-item[1], item[0]))
    included: set[Pixel] = set()
    index = 0
    regions = []
    for level in levels:
        achieved = math.fsum(field.values[pixel] for pixel in included)
        cutoff = ranked[index - 1][1] if index else None
        while achieved < level and index < len(ranked):
            cutoff = ranked[index][1]
            while index < len(ranked) and ranked[index][1] == cutoff:
                included.add(ranked[index][0])
                index += 1
            achieved = math.fsum(field.values[pixel] for pixel in included)
        regions.append(PixelMassRegion(level, achieved, cutoff, frozenset(included)))
    return tuple(regions)


def repaint_observation(
    observation: PopulationObservation,
    radius_u: float,
) -> tuple[Cellophane, ...]:
    return tuple(
        paint_sheet(
            walk.observed.session_id,
            walk.observed.started_at,
            list(walk.computed.segments),
            radius_u,
            NARROW_STEP,
        )
        for walk in observation.walks
    )


def hex_metric_fields(
    sheets: tuple[Cellophane, ...],
    radius_u: float,
) -> dict[str, SpatialField]:
    paint = paint_spec(radius_u, NARROW_STEP)
    projection = Projection.from_paint_spec(paint)
    return {
        metric: spatial_field(
            sheets,
            LayerSpec(Selector(), Aggregation(metric), projection),
        )
        for metric in METRICS
    }


def _comparison_pixels(
    reference: dict[str, RasterMetricField],
    hex_fields: dict[str, SpatialField],
    radius_u: float,
    raster: RasterSpec,
) -> tuple[Pixel, ...]:
    pixels = {pixel for field in reference.values() for pixel in field.values}
    for field in hex_fields.values():
        for cell in field.values:
            pixels.update(raster.pixel_at(lat, lng) for lat, lng in hex_boundary_latlng(*cell, radius_u))
    if not pixels:
        return ()
    min_x = min(pixel[0] for pixel in pixels)
    max_x = max(pixel[0] for pixel in pixels)
    min_y = min(pixel[1] for pixel in pixels)
    max_y = max(pixel[1] for pixel in pixels)
    return tuple(
        (pixel_x, pixel_y)
        for pixel_x in range(min_x, max_x + 1)
        for pixel_y in range(min_y, max_y + 1)
    )


def _iou(first: set[Pixel], second: set[Pixel]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 1.0


def _compare_metric(
    reference: RasterMetricField,
    hex_field: SpatialField,
    pixels: tuple[Pixel, ...],
    radius_u: float,
    raster: RasterSpec,
) -> dict[str, float | int | str]:
    hex_area = cell_area_m2(radius_u, raster.origin_lat)
    reference_values = []
    hex_values = []
    for pixel in pixels:
        lat, lng = raster.centre_latlng(pixel)
        cell = hex_cell(lat, lng, radius_u)
        reference_values.append(reference.values.get(pixel, 0.0))
        hex_values.append(hex_field.values.get(cell, 0.0))

    active = [
        (left, right)
        for left, right in zip(reference_values, hex_values, strict=True)
        if left > 0 or right > 0
    ]
    if reference.metric == "visit_rate":
        errors = [abs(left - right) for left, right in active]
        return {
            "comparison": "dimensionless_at_pixel_centres",
            "active_pixels": len(active),
            "mean_absolute_error": math.fsum(errors) / len(errors) if errors else 0.0,
            "max_absolute_error": max(errors, default=0.0),
        }

    reference_densities = [value / raster.pixel_area_m2 for value in reference_values]
    hex_densities = [value / hex_area for value in hex_values]
    absolute_integral = math.fsum(
        abs(left - right) * raster.pixel_area_m2
        for left, right in zip(reference_densities, hex_densities, strict=True)
    )
    reference_integral = math.fsum(
        value * raster.pixel_area_m2 for value in reference_densities
    )
    hex_integral = math.fsum(value * raster.pixel_area_m2 for value in hex_densities)
    normalized_l1 = 0.0
    if reference_integral > 0 and hex_integral > 0:
        normalized_l1 = math.fsum(
            abs(left / reference_integral - right / hex_integral) * raster.pixel_area_m2
            for left, right in zip(reference_densities, hex_densities, strict=True)
        )
    return {
        "comparison": "area_density_on_common_raster",
        "active_pixels": len(active),
        "reference_integral": reference_integral,
        "hex_integral": hex_integral,
        "relative_l1": absolute_integral / reference_integral if reference_integral else 0.0,
        "normalized_l1": normalized_l1,
        "max_density_difference": max(
            (abs(left - right) for left, right in zip(reference_densities, hex_densities, strict=True)),
            default=0.0,
        ),
    }


def _mass_region_comparison(
    reference_field: RasterMetricField,
    hex_field: SpatialField,
    pixels: tuple[Pixel, ...],
    radius_u: float,
    raster: RasterSpec,
) -> list[dict[str, float | int]]:
    reference_regions = highest_pixel_mass_regions(reference_field)
    hex_regions = highest_mass_regions(hex_field).regions
    rows = []
    for reference_region, hex_region in zip(reference_regions, hex_regions, strict=True):
        hex_pixels = {
            pixel
            for pixel in pixels
            if hex_cell(*raster.centre_latlng(pixel), radius_u) in hex_region.cells
        }
        rows.append(
            {
                "target_mass": reference_region.target_mass,
                "reference_achieved_mass": reference_region.achieved_mass,
                "hex_achieved_mass": hex_region.achieved_mass,
                "reference_pixel_count": len(reference_region.pixels),
                "hex_projected_pixel_count": len(hex_pixels),
                "area_iou": _iou(set(reference_region.pixels), hex_pixels),
            }
        )
    return rows


def radius_comparison(
    observation: PopulationObservation,
    reference_sheets: tuple[RasterSheet, ...],
    reference_fields: dict[str, RasterMetricField],
    radius_u: float,
    raster: RasterSpec,
    *,
    sheets: tuple[Cellophane, ...] | None = None,
    fields: dict[str, SpatialField] | None = None,
) -> dict[str, object]:
    if sheets is None:
        sheets = repaint_observation(observation, radius_u)
    if fields is None:
        fields = hex_metric_fields(sheets, radius_u)
    pixels = _comparison_pixels(reference_fields, fields, radius_u, raster)
    reference_support = set(reference_fields["total_time"].values)
    hex_support = {
        pixel
        for pixel in pixels
        if hex_cell(*raster.centre_latlng(pixel), radius_u) in fields["total_time"].values
    }
    paint = paint_spec(radius_u, NARROW_STEP)
    source_mass = math.fsum(sheet.source_segment_s for sheet in reference_sheets)
    hex_mass = math.fsum(sheet.occupancy[cell] for sheet in sheets for cell in sheet.occupancy)
    return {
        "radius_u": radius_u,
        "ground_radius_m_at_origin": radius_u * metres_per_unit(raster.origin_lat),
        "paint_fp": paint.fingerprint,
        "sample_step_m": paint.sample_step_m,
        "cell_count": len(fields["total_time"].values),
        "cell_area_m2_at_origin": cell_area_m2(radius_u, raster.origin_lat),
        "mass": {
            "source_segment_s": source_mass,
            "hex_s": hex_mass,
            "absolute_error_s": abs(hex_mass - source_mass),
        },
        "support": {
            "reference_area_m2": len(reference_support) * raster.pixel_area_m2,
            "hex_area_m2": len(fields["total_time"].values)
            * cell_area_m2(radius_u, raster.origin_lat),
            "area_ratio_hex_over_reference": (
                len(fields["total_time"].values) * cell_area_m2(radius_u, raster.origin_lat)
                / (len(reference_support) * raster.pixel_area_m2)
                if reference_support else 1.0
            ),
            "sampled_area_iou": _iou(reference_support, hex_support),
        },
        "metrics": {
            metric: _compare_metric(reference_fields[metric], fields[metric], pixels, radius_u, raster)
            for metric in METRICS
        },
        "mass_regions": {
            metric: _mass_region_comparison(
                reference_fields[metric], fields[metric], pixels, radius_u, raster
            )
            for metric in ("time_utilization", "walk_utilization")
        },
    }


def _distribution_l1(
    first: RasterMetricField,
    second: RasterMetricField,
) -> float:
    pixels = set(first.values) | set(second.values)
    return math.fsum(abs(first.values.get(pixel, 0.0) - second.values.get(pixel, 0.0)) for pixel in pixels)


def _sensor_interval_sensitivity(
    raster: RasterSpec,
    baseline_observation: PopulationObservation,
    baseline_fields: dict[str, RasterMetricField],
    intervals_s: tuple[float, ...],
) -> list[dict[str, float | int | str]]:
    truth = build_population_truth()
    baseline_interval = 5.0
    rows = []
    for interval_s in intervals_s:
        if interval_s == baseline_interval:
            observation = baseline_observation
            fields = baseline_fields
        else:
            observation = observe_population(truth, sample_interval_s=interval_s)
            fields = raster_metric_fields(rasterize_observation(observation, raster))
        total_s = math.fsum(walk.accepted_segment_s for walk in observation.walks)
        baseline_total = math.fsum(baseline_fields["total_time"].values.values())
        support = set(fields["total_time"].values)
        baseline_support = set(baseline_fields["total_time"].values)
        rows.append(
            {
                "sensor_kind": "perfect",
                "sample_interval_s": interval_s,
                "sample_count": len(observation.walks),
                "accepted_segment_s": total_s,
                "accepted_time_delta_from_5s": total_s - baseline_total,
                "time_utilization_l1_from_5s": _distribution_l1(
                    baseline_fields["time_utilization"], fields["time_utilization"]
                ),
                "support_iou_from_5s": _iou(baseline_support, support),
            }
        )
    return rows


def _gap_segment(east_m: float, start_s: float, chain_index: int) -> Segment:
    lat, lng = local_xy_to_latlng(east_m, 0.0, *DEFAULT_POPULATION_ORIGIN)
    started_at = datetime(2026, 8, 31, 9, tzinfo=UTC)
    first = WalkFix(
        client_seq=chain_index * 2,
        chain_index=chain_index,
        at=started_at + timedelta(seconds=start_s),
        lat=lat,
        lng=lng,
        accuracy_m=3.0,
        is_mock=True,
    )
    second = first.model_copy(
        update={
            "client_seq": chain_index * 2 + 1,
            "at": started_at + timedelta(seconds=start_s + 10.0),
        }
    )
    return Segment(
        a=first,
        b=second,
        dt=10.0,
        dist=0.0,
        offset_m=0.0,
        moving=False,
        chain_index=chain_index,
    )


def _gap_bridge_probe(radius_units: tuple[float, ...]) -> dict[str, object]:
    """서로 다른 chain 두 점 사이의 빈 120m를 어느 투영도 새 선으로 잇지 않는지 본다."""
    segments = [_gap_segment(-60.0, 0.0, 0), _gap_segment(60.0, 11.0, 1)]
    midpoint = DEFAULT_POPULATION_ORIGIN
    continuous = continuous_brush_field(segments, NARROW_STEP)
    started_at = segments[0].a.at
    rows = []
    for radius_u in radius_units:
        sheet = paint_sheet("gap-probe", started_at, segments, radius_u, NARROW_STEP)
        midpoint_cell = hex_cell(*midpoint, radius_u)
        midpoint_s = sheet.occupancy.get(midpoint_cell, 0.0)
        rows.append(
            {
                "radius_u": radius_u,
                "midpoint_occupancy_s": midpoint_s,
                "bridged": midpoint_s > 0,
            }
        )
    midpoint_density = continuous.density_s_per_m2_at(*midpoint)
    return {
        "endpoint_separation_m": 120.0,
        "continuous_midpoint_density_s_per_m2": midpoint_density,
        "continuous_bridged": midpoint_density > 0,
        "hex": rows,
    }


def build_comparison_payload(
    *,
    pixel_m: float = DEFAULT_PIXEL_M,
    radius_units: tuple[float, ...] = DEFAULT_RADIUS_UNITS,
    sample_intervals_s: tuple[float, ...] = DEFAULT_SAMPLE_INTERVALS_S,
) -> dict[str, object]:
    if not radius_units or any(not math.isfinite(value) or value <= 0 for value in radius_units):
        raise ValueError("radius_units는 비어 있지 않은 양수 목록이어야 한다")
    if 5.0 not in sample_intervals_s:
        raise ValueError("수집 간격 민감도에는 baseline 5초가 포함되어야 한다")
    truth = build_population_truth()
    observation = observe_population(truth, sample_interval_s=5.0)
    raster = RasterSpec(pixel_m=pixel_m)
    reference_sheets = rasterize_observation(observation, raster)
    reference_fields = raster_metric_fields(reference_sheets)
    source_s = math.fsum(sheet.source_segment_s for sheet in reference_sheets)
    raster_s = math.fsum(sheet.mass_s for sheet in reference_sheets)
    weighted_kernel_ratio = (
        math.fsum(sheet.source_segment_s * sheet.raw_kernel_integral_ratio for sheet in reference_sheets)
        / source_s if source_s else 1.0
    )
    return {
        "format_version": COMPARISON_FORMAT_VERSION,
        "population": {
            "generator_version": observation.generator_version,
            "run_id": observation.run_id,
            "sample_count": len(observation.walks),
        },
        "reference": {
            "kind": "continuous_brush_on_evaluator_raster",
            "pixel_m": raster.pixel_m,
            "pixel_count": len(reference_fields["total_time"].values),
            "brush_fp": continuous_brush_field(
                list(observation.walks[0].computed.segments), NARROW_STEP
            ).spec.fingerprint,
            "profile_fp": NARROW_STEP.fingerprint,
            "dab_count": sum(sheet.dab_count for sheet in reference_sheets),
            "stamp_evaluations": sum(sheet.stamp_evaluations for sheet in reference_sheets),
            "source_segment_s": source_s,
            "raster_mass_s": raster_s,
            "mass_absolute_error_s": abs(raster_s - source_s),
            "raw_kernel_integral_ratio": weighted_kernel_ratio,
        },
        "radius_comparisons": [
            radius_comparison(
                observation, reference_sheets, reference_fields, radius_u, raster
            )
            for radius_u in radius_units
        ],
        "sensor_interval_sensitivity": _sensor_interval_sensitivity(
            raster, observation, reference_fields, sample_intervals_s
        ),
        "disconnected_chain_gap_probe": _gap_bridge_probe(radius_units),
        "deferred_sensor_cases": [
            "dropout",
            "drift",
            "outlier",
            "variable_accuracy",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("continuous-hex-comparison.json"))
    parser.add_argument("--pixel-m", type=float, default=DEFAULT_PIXEL_M)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    payload = build_comparison_payload(pixel_m=args.pixel_m)
    elapsed = time.perf_counter() - started
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"{args.out}: {payload['population']['sample_count']} walks · "  # type: ignore[index]
        f"{len(payload['radius_comparisons'])} radii · {elapsed:.2f}s"  # type: ignore[arg-type]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
