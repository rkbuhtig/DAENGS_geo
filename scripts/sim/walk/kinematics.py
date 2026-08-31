"""거리축 행동을 시간축 실제 동선으로 적분한다."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from itertools import pairwise

from scripts.sim.walk.model import BehaviorPlan
from scripts.sim.walk.route import RouteGeometry


@dataclass(frozen=True)
class TimelineKnot:
    elapsed_s: float
    progress_m: float


@dataclass(frozen=True)
class MotionSample:
    elapsed_s: float
    progress_m: float
    east_m: float
    north_m: float
    target_speed_mps: float
    forward_speed_mps: float
    ground_speed_mps: float
    latent_state: str

    def to_dict(self) -> dict[str, object]:
        return {
            "elapsed_s": round(self.elapsed_s, 3),
            "progress_m": round(self.progress_m, 3),
            "east_m": round(self.east_m, 3),
            "north_m": round(self.north_m, 3),
            "target_speed_mps": round(self.target_speed_mps, 4),
            "forward_speed_mps": round(self.forward_speed_mps, 4),
            "ground_speed_mps": round(self.ground_speed_mps, 4),
            "latent_state": self.latent_state,
        }


@dataclass(frozen=True)
class MotionTruth:
    """GPS 이전의 실제 운동. route는 호 길이로 매개화돼 forward와 ground 속도가 같다."""

    behavior: BehaviorPlan
    route: RouteGeometry
    timeline: tuple[TimelineKnot, ...]

    @property
    def duration_s(self) -> float:
        return self.timeline[-1].elapsed_s

    def sample_at(self, elapsed_s: float) -> MotionSample:
        if not math.isfinite(elapsed_s) or not 0 <= elapsed_s <= self.duration_s:
            raise ValueError("elapsed_s is outside motion duration")
        if elapsed_s == self.duration_s:
            progress = self.behavior.length_m
            target_speed = self.behavior.speed_at(progress)
            left, right = self.timeline[-2], self.timeline[-1]
            speed = (
                0.0 if right.progress_m == left.progress_m
                else (right.progress_m - left.progress_m) / (right.elapsed_s - left.elapsed_s)
            )
            state = self.behavior.state_at(progress)
        else:
            times = [knot.elapsed_s for knot in self.timeline]
            index = max(0, bisect.bisect_right(times, elapsed_s) - 1)
            left, right = self.timeline[index], self.timeline[index + 1]
            if right.progress_m == left.progress_m:
                progress, speed, state = left.progress_m, 0.0, "hold"
                target_speed = self.behavior.speed_at(progress)
            else:
                fraction = (elapsed_s - left.elapsed_s) / (right.elapsed_s - left.elapsed_s)
                progress = left.progress_m + (right.progress_m - left.progress_m) * fraction
                target_speed = self.behavior.speed_at(progress)
                speed = (right.progress_m - left.progress_m) / (
                    right.elapsed_s - left.elapsed_s
                )
                state = self.behavior.state_at(progress)
        east, north = self.route.point_at(progress)
        return MotionSample(
            elapsed_s, progress, east, north, target_speed, speed, speed, state
        )

    def samples(self, interval_s: float) -> tuple[MotionSample, ...]:
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("interval_s must be finite and positive")
        count = math.floor(self.duration_s / interval_s)
        times = [index * interval_s for index in range(count + 1)]
        if not math.isclose(times[-1], self.duration_s, abs_tol=1e-9):
            times.append(self.duration_s)
        return tuple(self.sample_at(time) for time in times)


def _spatial_positions(plan: BehaviorPlan, step_m: float) -> list[float]:
    count = math.floor(plan.length_m / step_m)
    positions = {index * step_m for index in range(count + 1)}
    positions.update((0.0, plan.length_m))
    positions.update(hold.progress_m for hold in plan.holds)
    for motif in plan.slow_motifs:
        positions.update((max(0.0, motif.start_m), motif.centre_m, min(plan.length_m, motif.end_m)))
    return sorted(positions)


def integrate_motion(
    behavior: BehaviorPlan,
    route: RouteGeometry,
    *,
    integration_step_m: float = 0.5,
) -> MotionTruth:
    """`dt/ds = 1/v(s)`를 사다리꼴 적분하고 hold를 같은 진행거리의 시간축으로 삽입한다."""
    if not math.isclose(behavior.length_m, route.length_m, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("behavior and route lengths must match")
    if not math.isfinite(integration_step_m) or integration_step_m <= 0:
        raise ValueError("integration_step_m must be finite and positive")

    holds: dict[float, float] = {}
    for event in behavior.holds:
        holds[event.progress_m] = holds.get(event.progress_m, 0.0) + event.duration_s

    positions = _spatial_positions(behavior, integration_step_m)
    elapsed = 0.0
    timeline = [TimelineKnot(0.0, 0.0)]
    if 0.0 in holds:
        elapsed += holds[0.0]
        timeline.append(TimelineKnot(elapsed, 0.0))

    for left, right in pairwise(positions):
        distance = right - left
        inverse_speed = 0.5 * (
            1.0 / behavior.speed_at(left) + 1.0 / behavior.speed_at(right)
        )
        elapsed += distance * inverse_speed
        timeline.append(TimelineKnot(elapsed, right))
        if right in holds:
            elapsed += holds[right]
            timeline.append(TimelineKnot(elapsed, right))
    return MotionTruth(behavior, route, tuple(timeline))
