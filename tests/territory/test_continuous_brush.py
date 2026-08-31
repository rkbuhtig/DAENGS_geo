"""육각형 없는 연속 원 브러시 reference의 계산 계약."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.features.territory.continuous_brush import (
    BrushDab,
    continuous_brush_field,
    continuous_brush_spec,
    radial_kernel_area_m2,
)
from app.features.territory.paint import NARROW_SMOOTH, NARROW_STEP, flat
from app.features.walk.facts import Segment
from app.features.walk.models import WalkFix

EARTH_RADIUS_M = 6_371_000.0
LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 8, 31, 9, tzinfo=UTC)


def _at(east_m: float, seconds: float, chain: int = 0) -> WalkFix:
    lng = LNG + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(LAT))))
    return WalkFix(
        client_seq=round(seconds),
        chain_index=chain,
        at=START + timedelta(seconds=seconds),
        lat=LAT,
        lng=lng,
        accuracy_m=3.0,
        is_mock=True,
    )


def _segment(start_m: float, end_m: float, start_s: float, end_s: float, chain: int = 0):
    return Segment(
        a=_at(start_m, start_s, chain),
        b=_at(end_m, end_s, chain),
        dt=end_s - start_s,
        dist=end_m - start_m,
        offset_m=start_m,
        moving=end_m > start_m,
        chain_index=chain,
    )


def test_flat_kernel_area_matches_a_circle_and_smooth_profile_is_positive():
    assert radial_kernel_area_m2(flat(10.0)) == pytest.approx(math.pi * 10.0**2)
    assert radial_kernel_area_m2(NARROW_SMOOTH) > 0


def test_continuous_field_conserves_source_segment_seconds_without_a_grid():
    segments = [
        _segment(0.0, 30.0, 0.0, 30.0),
        _segment(30.0, 30.0, 30.0, 45.0),
        _segment(30.0, 60.0, 45.0, 75.0),
    ]

    field = continuous_brush_field(segments, NARROW_STEP)

    assert field.mass_s == pytest.approx(75.0)
    assert field.source_segment_s == pytest.approx(75.0)
    assert math.fsum(dab.mass_s for dab in field.dabs) == pytest.approx(75.0)
    assert field.spec.profile_fp == NARROW_STEP.fingerprint


def test_stationary_segment_forms_a_normalized_circle_of_time_mass():
    field = continuous_brush_field(
        [_segment(0.0, 0.0, 0.0, 10.0)],
        flat(10.0),
    )
    centre = _at(0.0, 0.0)
    inside = _at(9.0, 0.0)
    outside = _at(10.1, 0.0)
    expected_density = 10.0 / (math.pi * 10.0**2)

    assert field.density_s_per_m2_at(centre.lat, centre.lng) == pytest.approx(expected_density)
    assert field.density_s_per_m2_at(inside.lat, inside.lng) == pytest.approx(expected_density)
    assert field.density_s_per_m2_at(outside.lat, outside.lng) == 0


def test_retracing_doubles_time_density_but_not_peak_strength():
    segment = _segment(0.0, 60.0, 0.0, 60.0)
    once = continuous_brush_field([segment], NARROW_SMOOTH)
    twice = continuous_brush_field([segment, segment], NARROW_SMOOTH)
    centre = _at(30.0, 30.0)

    assert twice.density_s_per_m2_at(centre.lat, centre.lng) == pytest.approx(
        2 * once.density_s_per_m2_at(centre.lat, centre.lng)
    )
    assert twice.peak_at(centre.lat, centre.lng) == once.peak_at(centre.lat, centre.lng)


def test_segment_sampling_interval_does_not_materially_change_the_continuous_field():
    one_segment = [_segment(0.0, 60.0, 0.0, 60.0)]
    five_metre_segments = [
        _segment(float(start), float(start + 5), float(start), float(start + 5))
        for start in range(0, 60, 5)
    ]
    coarse = continuous_brush_field(one_segment, NARROW_SMOOTH)
    resampled = continuous_brush_field(five_metre_segments, NARROW_SMOOTH)

    assert coarse.mass_s == resampled.mass_s == 60.0
    for east_m in (10.0, 30.0, 50.0):
        point = _at(east_m, east_m)
        assert resampled.density_s_per_m2_at(point.lat, point.lng) == pytest.approx(
            coarse.density_s_per_m2_at(point.lat, point.lng),
            rel=0.03,
        )


def test_distinct_chains_do_not_create_a_brush_across_a_wide_gap():
    segments = [
        _segment(0.0, 20.0, 0.0, 20.0, chain=0),
        _segment(180.0, 200.0, 21.0, 41.0, chain=1),
    ]
    field = continuous_brush_field(segments, NARROW_STEP)
    first = _at(10.0, 10.0)
    gap = _at(100.0, 20.0)
    second = _at(190.0, 30.0)

    assert field.chain_indexes == frozenset({0, 1})
    assert field.density_s_per_m2_at(first.lat, first.lng) > 0
    assert field.density_s_per_m2_at(second.lat, second.lng) > 0
    assert field.density_s_per_m2_at(gap.lat, gap.lng) == 0
    assert field.peak_at(gap.lat, gap.lng) == 0


def test_reference_identity_tracks_profile_and_sampling_step():
    default = continuous_brush_spec(NARROW_STEP)
    same = continuous_brush_spec(NARROW_STEP, default.sample_step_m)
    changed_step = continuous_brush_spec(NARROW_STEP, default.sample_step_m + 0.5)
    changed_profile = continuous_brush_spec(NARROW_SMOOTH, default.sample_step_m)

    assert default.fingerprint == same.fingerprint
    assert changed_step.fingerprint != default.fingerprint
    assert changed_profile.fingerprint != default.fingerprint


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lat": 91.0, "lng": LNG, "mass_s": 1.0, "chain_index": 0},
        {"lat": LAT, "lng": 181.0, "mass_s": 1.0, "chain_index": 0},
        {"lat": LAT, "lng": LNG, "mass_s": 0.0, "chain_index": 0},
        {"lat": LAT, "lng": LNG, "mass_s": 1.0, "chain_index": -1},
    ],
)
def test_invalid_dabs_fail_at_the_boundary(kwargs):
    with pytest.raises(ValueError):
        BrushDab(**kwargs)
