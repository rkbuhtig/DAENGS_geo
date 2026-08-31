"""셀로판 z축 실험용 30회 산책의 evaluator-only latent truth.

제품 집계기는 이 모듈을 읽지 않는다. 여기에는 생성기가 심은 경로군과 긴 체류가 들어 있고,
`population.py`가 이를 GPS 관측으로 바꾼 뒤에는 branch 이름이 Cellophane에 전달되지 않는다.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from scripts.sim.walk.model import BehaviorPlan, HoldEvent, behavior_preset
from scripts.sim.walk.route import Point, RouteGeometry

POPULATION_GENERATOR_VERSION = 1
DEFAULT_POPULATION_SEED = 731_905
POPULATION_START = datetime(2026, 1, 1, 9, tzinfo=UTC)
HOME_XY: Point = (0.0, 0.0)
ENTRANCE_XY: Point = (0.0, 40.0)
JUNCTION_XY: Point = (0.0, 100.0)

BranchName = Literal["east_loop", "south_outback", "north_park", "exploration"]
BRANCH_COUNTS: dict[BranchName, int] = {
    "east_loop": 14,
    "south_outback": 9,
    "north_park": 4,
    "exploration": 3,
}


@dataclass(frozen=True)
class PopulationWalkTruth:
    """한 산책에 심은 원인. 관측 결과나 제품 입력 계약이 아니다."""

    walk_id: str
    started_at: datetime
    branch: BranchName
    variant: int
    route: RouteGeometry
    behavior: BehaviorPlan
    behavior_seed: int

    def to_dict(self) -> dict[str, object]:
        return {
            "walk_id": self.walk_id,
            "started_at": self.started_at.isoformat(),
            "branch": self.branch,
            "variant": self.variant,
            "route": self.route.to_dict(),
            "behavior": self.behavior.to_dict(),
            "behavior_seed": self.behavior_seed,
        }


@dataclass(frozen=True)
class PopulationTruth:
    """생성기만 아는 30회 모집단. 평가기는 derived 결과와 사후 비교할 때만 읽는다."""

    generator_version: int
    seed: int
    walks: tuple[PopulationWalkTruth, ...]

    @property
    def branch_counts(self) -> dict[str, int]:
        return dict(Counter(walk.branch for walk in self.walks))

    def to_dict(self) -> dict[str, object]:
        return {
            "generator_version": self.generator_version,
            "seed": self.seed,
            "branch_counts": self.branch_counts,
            "walks": [walk.to_dict() for walk in self.walks],
        }


def _closed_route(name: str, branch_points: tuple[Point, ...]) -> RouteGeometry:
    points = (HOME_XY, ENTRANCE_XY, JUNCTION_XY, *branch_points, JUNCTION_XY, ENTRANCE_XY, HOME_XY)
    return RouteGeometry.from_points(name, points)


def _route(branch: BranchName, variant: int) -> RouteGeometry:
    if branch == "east_loop":
        return _closed_route(
            branch,
            ((110.0, 100.0), (210.0, 155.0), (245.0, 55.0), (135.0, 20.0)),
        )
    if branch == "south_outback":
        return _closed_route(
            branch,
            ((55.0, 25.0), (95.0, -75.0), (35.0, -165.0), (95.0, -75.0), (55.0, 25.0)),
        )
    if branch == "north_park":
        return _closed_route(
            branch,
            ((0.0, 210.0), (60.0, 300.0), (0.0, 365.0), (-60.0, 300.0), (0.0, 210.0)),
        )
    exploration_branches: tuple[tuple[Point, ...], ...] = (
        ((-90.0, 155.0), (-195.0, 225.0), (-120.0, 315.0), (-35.0, 205.0)),
        ((85.0, 185.0), (175.0, 285.0), (95.0, 390.0), (20.0, 245.0)),
        ((-80.0, 35.0), (-170.0, -45.0), (-245.0, 20.0), (-125.0, 80.0)),
    )
    return _closed_route(branch, exploration_branches[variant])


def _behavior(
    branch: BranchName, route: RouteGeometry, behavior_seed: int, variant: int
) -> BehaviorPlan:
    if branch != "north_park":
        return behavior_preset("steady", route.length_m, behavior_seed)
    # 북쪽 공원의 의도적인 긴 체류만 다른 경로군과 다르다. 위치는 공원 루프의 가장 먼 점이다.
    park_progress_m = route.cumulative_m[5]
    return BehaviorPlan(
        name="stop-heavy",
        length_m=route.length_m,
        base_speed_mps=1.28,
        holds=(HoldEvent(park_progress_m, 180.0 + 15.0 * variant),),
    )


def build_population_truth(seed: int = DEFAULT_POPULATION_SEED) -> PopulationTruth:
    """정확한 14/9/4/3 구성을 유지하되 날짜 배치는 seed로 결정한다."""
    schedule: list[tuple[BranchName, int]] = []
    for branch, count in BRANCH_COUNTS.items():
        schedule.extend((branch, variant) for variant in range(count))
    random.Random(seed).shuffle(schedule)

    walks = []
    for index, (branch, occurrence) in enumerate(schedule):
        variant = occurrence % 3 if branch == "exploration" else occurrence
        route = _route(branch, variant)
        behavior_seed = seed * 100 + index
        walks.append(
            PopulationWalkTruth(
                walk_id=f"population-{index:02d}",
                started_at=POPULATION_START + timedelta(days=index),
                branch=branch,
                variant=variant,
                route=route,
                behavior=_behavior(branch, route, behavior_seed, occurrence),
                behavior_seed=behavior_seed,
            )
        )
    return PopulationTruth(POPULATION_GENERATOR_VERSION, seed, tuple(walks))
