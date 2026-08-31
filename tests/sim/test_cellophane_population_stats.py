"""30회 fixture의 latent 의도가 PR1 통계에서 관측 신호로 회수되는지 사후 평가한다."""

import math

import pytest

from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import NARROW_STEP, paint_spec
from app.features.territory.spatial_stats import highest_mass_regions, spatial_field
from app.geo.cells import hex_cell
from scripts.sim.walk.population import DEFAULT_POPULATION_ORIGIN, observe_population
from scripts.sim.walk.population_truth import build_population_truth
from scripts.sim.walk.sensor import local_xy_to_latlng

REFERENCE_XY = {
    "home": (0.0, 0.0),
    "junction": (0.0, 100.0),
    "east": (210.0, 155.0),
    "south": (35.0, -165.0),
    "north_park": (0.0, 365.0),
    "exploration": (-195.0, 225.0),
}


def _reference_cells(radius_u: float) -> dict[str, tuple[int, int]]:
    return {
        name: hex_cell(
            *local_xy_to_latlng(*xy, *DEFAULT_POPULATION_ORIGIN),
            radius_u,
        )
        for name, xy in REFERENCE_XY.items()
    }


def test_population_statistics_recover_frequency_dwell_and_mass_region_signals():
    # truth는 생성과 사후 채점에만 쓰고, 아래 통계 함수에는 observed Cellophane만 전달한다.
    observation = observe_population(build_population_truth())
    paint = paint_spec(8.0, NARROW_STEP)
    projection = Projection.from_paint_spec(paint)

    def calculate(metric: str):
        return spatial_field(
            observation.sheets,
            LayerSpec(Selector(), Aggregation(metric), projection),
        )

    rate = calculate("visit_rate")
    dwell = calculate("conditional_dwell")
    by_time = calculate("time_utilization")
    by_walk = calculate("walk_utilization")
    cells = _reference_cells(paint.radius_u)

    assert rate.values[cells["home"]] == 1.0
    assert rate.values[cells["junction"]] == 1.0
    assert rate.values[cells["east"]] == pytest.approx(14 / 30)
    assert rate.values[cells["south"]] == pytest.approx(9 / 30)
    assert rate.values[cells["north_park"]] == pytest.approx(4 / 30)
    assert rate.values[cells["exploration"]] == pytest.approx(1 / 30)

    ordinary_dwell = max(dwell.values[cells[name]] for name in ("east", "south", "exploration"))
    assert dwell.values[cells["north_park"]] > ordinary_dwell * 5

    distance = math.fsum(
        abs(by_time.values.get(cell, 0.0) - by_walk.values.get(cell, 0.0))
        for cell in set(by_time.values) | set(by_walk.values)
    )
    assert distance > 0.03
    assert by_time.values[cells["north_park"]] > by_walk.values[cells["north_park"]]

    for field in (by_time, by_walk):
        core, routine, fringe = highest_mass_regions(field).regions
        assert cells["east"] in core.cells
        assert cells["south"] in routine.cells
        assert cells["exploration"] not in core.cells
        assert cells["exploration"] not in routine.cells
        assert cells["exploration"] in fringe.cells
