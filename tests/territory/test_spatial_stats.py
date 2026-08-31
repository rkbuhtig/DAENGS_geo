"""셀로판 z축 공간 통계 계약. `app/features/territory/spatial_stats.py`.

같은 어두움을 서로 다른 질문으로 풀어낼 수 있어야 한다.

    매일 빠르게 지나는 셀  방문률 높음 · 방문당 체류 낮음
    한 번 오래 머문 셀      방문률 낮음 · 방문당 체류 높음

또 긴 산책의 시간이 실제 비중을 갖는 `time_utilization`과 산책 한 장을 동등하게 세는
`walk_utilization`이 같은 자료에서 다른 답을 내야 한다.
"""

import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import NARROW_STEP, BrushProfile, Cellophane, paint_spec
from app.features.territory.spatial_stats import (
    conditional_dwell_field,
    highest_mass_regions,
    spatial_field,
    time_utilization_field,
    total_time_field,
    visit_rate_field,
    walk_utilization_field,
)

RADIUS_U = 8.0
PAINT_SPEC = paint_spec(RADIUS_U, NARROW_STEP)
COMMON = (10, 20)
RARE_LONG = (11, 20)
FRINGE = (12, 20)
AT = datetime(2026, 8, 1, 9, tzinfo=UTC)


def _sheet(
    walk_id: str,
    day: int,
    occupancy: dict[tuple[int, int], float],
    peak: dict[tuple[int, int], float] | None = None,
) -> Cellophane:
    return Cellophane(
        walk_id=walk_id,
        at=AT + timedelta(days=day),
        radius_u=RADIUS_U,
        profile=NARROW_STEP.name,
        occupancy=occupancy,
        peak=peak or {cell: 1.0 for cell in occupancy},
        paint_version=PAINT_SPEC.paint_version,
        grid_version=PAINT_SPEC.grid_version,
        profile_fp=PAINT_SPEC.profile_fp,
        sample_step_m=PAINT_SPEC.sample_step_m,
        paint_fp=PAINT_SPEC.fingerprint,
    )


def _spec(metric: str, min_peak: float = 0.0, *, since: date | None = None) -> LayerSpec:
    return LayerSpec(
        selector=Selector.of(since=since),
        aggregation=Aggregation(metric=metric, min_peak=min_peak),
        projection=Projection.from_paint_spec(PAINT_SPEC),
    )


def _three_walks() -> list[Cellophane]:
    """공통 셀은 매일 10초, 외곽 셀은 한 번 100초 머문다."""
    return [
        _sheet("long-rare", 0, {COMMON: 10.0, RARE_LONG: 100.0}),
        _sheet("routine-1", 1, {COMMON: 10.0}),
        _sheet("routine-2", 2, {COMMON: 10.0}),
    ]


def test_total_visit_and_conditional_dwell_answer_different_questions():
    sheets = _three_walks()
    total = total_time_field(sheets, _spec("total_time"))
    rate = visit_rate_field(sheets, _spec("visit_rate"))
    dwell = conditional_dwell_field(sheets, _spec("conditional_dwell"))

    assert total.values == {COMMON: 30.0, RARE_LONG: 100.0}
    assert rate.values == {COMMON: 1.0, RARE_LONG: 1 / 3}
    assert dwell.values == {COMMON: 10.0, RARE_LONG: 100.0}

    assert rate.numerators == {COMMON: 3.0, RARE_LONG: 1.0}
    assert rate.denominator == 3.0
    assert dwell.numerators == total.numerators
    assert dwell.denominator == {COMMON: 3.0, RARE_LONG: 1.0}


def test_time_and_walk_utilization_deliberately_weight_the_long_walk_differently():
    sheets = _three_walks()
    by_time = time_utilization_field(sheets, _spec("time_utilization"))
    by_walk = walk_utilization_field(sheets, _spec("walk_utilization"))

    assert math.isclose(sum(by_time.values.values()), 1.0)
    assert math.isclose(sum(by_walk.values.values()), 1.0)
    assert by_time.values[RARE_LONG] > by_time.values[COMMON]
    assert by_walk.values[RARE_LONG] < by_walk.values[COMMON]

    assert math.isclose(by_time.values[RARE_LONG], 100 / 130)
    assert math.isclose(by_walk.values[RARE_LONG], (100 / 110) / 3)
    assert by_time.normalization == "total_observed_time"
    assert by_walk.normalization == "equal_contributing_walks"


def test_min_peak_gates_visit_time_and_conditional_dwell_per_walk():
    sheets = [
        _sheet("direct", 0, {FRINGE: 5.0}, {FRINGE: 1.0}),
        _sheet("long-graze-1", 1, {FRINGE: 90.0}, {FRINGE: 0.15}),
        _sheet("long-graze-2", 2, {FRINGE: 80.0}, {FRINGE: 0.15}),
    ]
    total = total_time_field(sheets, _spec("total_time", 0.9))
    rate = visit_rate_field(sheets, _spec("visit_rate", 0.9))
    dwell = conditional_dwell_field(sheets, _spec("conditional_dwell", 0.9))

    assert total.values == {FRINGE: 5.0}
    assert rate.values == {FRINGE: 1 / 3}
    assert dwell.values == {FRINGE: 5.0}
    assert total.min_peak == rate.min_peak == dwell.min_peak == 0.9


def test_utilization_refuses_a_peak_gate_that_would_hide_lost_mass():
    sheets = _three_walks()
    with pytest.raises(ValueError, match="min_peak=0"):
        time_utilization_field(sheets, _spec("time_utilization", 0.4))
    with pytest.raises(ValueError, match="min_peak=0"):
        walk_utilization_field(sheets, _spec("walk_utilization", 0.4))


def test_result_keeps_spec_sample_counts_and_paint_generation():
    sheets = _three_walks()
    since = (AT + timedelta(days=1)).date()
    result = spatial_field(sheets, _spec("visit_rate", since=since))

    assert result.metric == "visit_rate"
    assert (result.selected, result.total, result.contributing) == (2, 3, 2)
    assert result.paint_fp == PAINT_SPEC.fingerprint
    assert result.spec.fingerprint() == _spec("visit_rate", since=since).fingerprint()


def test_query_selects_one_paint_generation_instead_of_mixing_the_z_axis():
    target = _sheet("target-generation", 0, {COMMON: 10.0})
    other_profile = BrushProfile("다른 세대", (3.0, 8.0, 20.0), (1.0, 0.5, 0.1))
    other_spec = paint_spec(RADIUS_U, other_profile)
    other = Cellophane(
        walk_id="other-generation",
        at=AT + timedelta(days=1),
        radius_u=RADIUS_U,
        profile=other_profile.name,
        occupancy={RARE_LONG: 999.0},
        peak={RARE_LONG: 1.0},
        paint_version=other_spec.paint_version,
        grid_version=other_spec.grid_version,
        profile_fp=other_spec.profile_fp,
        sample_step_m=other_spec.sample_step_m,
        paint_fp=other_spec.fingerprint,
    )

    result = total_time_field([target, other], _spec("total_time"))
    assert result.values == {COMMON: 10.0}
    assert (result.selected, result.total) == (1, 2)
    assert result.paint_fp == PAINT_SPEC.fingerprint


def test_empty_selection_is_not_reported_as_a_zero_percent_cell():
    future = date(2030, 1, 1)
    result = visit_rate_field(_three_walks(), _spec("visit_rate", since=future))
    assert result.values == {}
    assert result.numerators == {}
    assert result.denominator == 0.0
    assert (result.selected, result.total, result.contributing) == (0, 3, 0)


def test_empty_sheet_is_a_nonvisit_but_not_a_walk_utilization_contributor():
    sheets = [_sheet("observed", 0, {COMMON: 10.0}), _sheet("empty", 1, {})]
    rate = visit_rate_field(sheets, _spec("visit_rate"))
    utilization = walk_utilization_field(sheets, _spec("walk_utilization"))

    assert rate.values[COMMON] == 1 / 2
    assert (rate.selected, rate.contributing) == (2, 2)
    assert utilization.values == {COMMON: 1.0}
    assert (utilization.selected, utilization.contributing) == (2, 1)


def test_dispatch_rejects_canvas_and_unknown_metrics():
    with pytest.raises(ValueError, match="공간 통계 metric"):
        spatial_field(_three_walks(), _spec("walks"))
    with pytest.raises(ValueError, match="공간 통계 metric"):
        spatial_field(_three_walks(), _spec("mystery"))


def test_named_function_rejects_a_mismatched_metric_receipt():
    with pytest.raises(ValueError, match="metric='visit_rate'"):
        total_time_field(_three_walks(), _spec("visit_rate"))


@pytest.mark.parametrize("threshold", [-0.1, 1.1, math.nan])
def test_statistics_reject_invalid_peak_thresholds(threshold: float):
    with pytest.raises(ValueError, match="min_peak"):
        visit_rate_field(_three_walks(), _spec("visit_rate", threshold))


class _ReadCountingDict(dict):
    reads = 0

    def __contains__(self, key):
        type(self).reads += 1
        return super().__contains__(key)

    def get(self, key, default=None):
        type(self).reads += 1
        return super().get(key, default)


@pytest.mark.parametrize(
    ("metric", "calculate"),
    [
        ("total_time", total_time_field),
        ("visit_rate", visit_rate_field),
        ("conditional_dwell", conditional_dwell_field),
        ("time_utilization", time_utilization_field),
        ("walk_utilization", walk_utilization_field),
    ],
)
def test_sparse_aggregation_reads_each_present_cell_a_constant_number_of_times(metric, calculate):
    sheets = [
        _sheet(
            f"walk-{walk}",
            walk,
            _ReadCountingDict({(walk * 10 + cell, 0): 1.0 for cell in range(10)}),
        )
        for walk in range(10)
    ]
    _ReadCountingDict.reads = 0

    result = calculate(sheets, _spec(metric))

    assert len(result.values) == 100
    assert _ReadCountingDict.reads <= 100


def test_highest_mass_regions_are_nested_and_keep_the_field_receipt():
    field = walk_utilization_field(_three_walks(), _spec("walk_utilization"))
    result = highest_mass_regions(field, (0.5, 0.8, 0.95))

    core, routine, fringe = result.regions
    assert result.field is field
    assert core.cells <= routine.cells <= fringe.cells
    assert core.achieved_mass >= 0.5
    assert routine.achieved_mass >= 0.8
    assert fringe.achieved_mass >= 0.95


def test_highest_mass_region_includes_every_cell_tied_at_the_cutoff():
    sheets = [_sheet("one", 0, {(0, 0): 4.0, (1, 0): 2.0, (2, 0): 2.0, (3, 0): 2.0})]
    field = time_utilization_field(sheets, _spec("time_utilization"))
    region = highest_mass_regions(field, (0.5,)).regions[0]

    assert region.cutoff_value == 0.2
    assert region.cells == frozenset({(0, 0), (1, 0), (2, 0), (3, 0)})
    assert region.achieved_mass == 1.0


def test_highest_mass_region_normalizes_tolerated_rounding_drift_at_one_hundred_percent():
    field = time_utilization_field(_three_walks(), _spec("time_utilization"))
    drifted = replace(
        field,
        values={cell: value * (1 - 5e-10) for cell, value in field.values.items()},
    )

    region = highest_mass_regions(drifted, (1.0,)).regions[0]

    assert region.cells == frozenset(field.values)
    assert region.achieved_mass == pytest.approx(1.0)


def test_highest_mass_regions_reject_non_distribution_fields_and_bad_levels():
    with pytest.raises(ValueError, match="time_utilization"):
        highest_mass_regions(visit_rate_field(_three_walks(), _spec("visit_rate")))
    field = time_utilization_field(_three_walks(), _spec("time_utilization"))
    with pytest.raises(ValueError, match="오름차순"):
        highest_mass_regions(field, (0.8, 0.5))
