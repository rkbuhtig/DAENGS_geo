"""같은 집에서 갈라지는 30회 Cellophane fixture의 truth/observation 경계."""

import math
from dataclasses import fields, replace

from scripts.sim.walk.population import observe_population
from scripts.sim.walk.population_truth import (
    BRANCH_COUNTS,
    ENTRANCE_XY,
    HOME_XY,
    JUNCTION_XY,
    build_population_truth,
)


def test_population_has_the_declared_30_walk_branch_mix_and_shared_stem():
    truth = build_population_truth()

    assert len(truth.walks) == 30
    assert truth.branch_counts == BRANCH_COUNTS
    assert len({walk.route.points_xy for walk in truth.walks}) == 6
    for walk in truth.walks:
        assert walk.route.points_xy[:3] == (HOME_XY, ENTRANCE_XY, JUNCTION_XY)
        assert walk.route.points_xy[-3:] == (JUNCTION_XY, ENTRANCE_XY, HOME_XY)


def test_only_the_north_park_branch_plants_a_long_dwell():
    truth = build_population_truth()

    park = [walk for walk in truth.walks if walk.branch == "north_park"]
    ordinary = [walk for walk in truth.walks if walk.branch != "north_park"]
    assert len(park) == 4
    assert all(len(walk.behavior.holds) == 1 for walk in park)
    assert all(walk.behavior.holds[0].duration_s >= 180 for walk in park)
    assert all(not walk.behavior.holds for walk in ordinary)


def test_population_truth_is_reproducible_and_seed_keeps_the_declared_mix():
    first = build_population_truth(seed=17)
    repeated = build_population_truth(seed=17)
    changed = build_population_truth(seed=18)

    assert first.to_dict() == repeated.to_dict()
    assert first.to_dict() != changed.to_dict()
    assert first.branch_counts == changed.branch_counts == BRANCH_COUNTS


def test_observation_returns_no_latent_route_or_branch_field():
    observation = observe_population(build_population_truth())

    assert {field.name for field in fields(observation)} == {
        "generator_version",
        "run_id",
        "walks",
    }
    assert {field.name for field in fields(observation.walks[0])} == {
        "observed",
        "computed",
        "sheet",
    }
    assert all(not hasattr(sheet, "branch") for sheet in observation.sheets)
    encoded = repr(observation)
    assert all(branch not in encoded for branch in BRANCH_COUNTS)


def test_same_truth_reproduces_observed_fixes_and_cellophane():
    truth = build_population_truth(seed=23)
    small_truth = replace(truth, walks=truth.walks[:2])

    first = observe_population(small_truth)
    repeated = observe_population(small_truth)

    assert first.run_id == repeated.run_id
    assert first.sheets == repeated.sheets
    assert [walk.observed.to_export() for walk in first.walks] == [
        walk.observed.to_export() for walk in repeated.walks
    ]


def test_all_observed_walks_start_and_finish_at_the_same_home():
    observation = observe_population(build_population_truth())
    endpoints = {
        (
            walk.observed.fixes[0].lat,
            walk.observed.fixes[0].lng,
            walk.observed.fixes[-1].lat,
            walk.observed.fixes[-1].lng,
        )
        for walk in observation.walks
    }

    assert len(endpoints) == 1
    start_lat, start_lng, end_lat, end_lng = endpoints.pop()
    assert (start_lat, start_lng) == (end_lat, end_lng)


def test_every_sheet_preserves_its_own_canonical_segment_time_mass():
    observation = observe_population(build_population_truth())

    assert len(observation.sheets) == 30
    assert len({sheet.walk_id for sheet in observation.sheets}) == 30
    assert len({frozenset(sheet.occupancy) for sheet in observation.sheets}) >= 6
    for walk in observation.walks:
        assert math.isclose(
            walk.accepted_segment_s,
            math.fsum(walk.sheet.occupancy.values()),
            abs_tol=1e-8,
        )
