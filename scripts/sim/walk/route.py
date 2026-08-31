"""1차원 진행거리를 로컬 east/north 미터 좌표의 polyline에 투영한다."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

RouteName = Literal["straight", "s-curve", "loop", "out-and-back"]
Point = tuple[float, float]


def _distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


@dataclass(frozen=True)
class RouteGeometry:
    name: str
    points_xy: tuple[Point, ...]
    cumulative_m: tuple[float, ...]

    @classmethod
    def from_points(cls, name: str, points: tuple[Point, ...]) -> RouteGeometry:
        if len(points) < 2:
            raise ValueError("route needs at least two points")
        if any(not all(math.isfinite(axis) for axis in point) for point in points):
            raise ValueError("route coordinates must be finite")
        cumulative = [0.0]
        for a, b in pairwise(points):
            distance = _distance(a, b)
            if distance <= 0:
                raise ValueError("adjacent route points must be distinct")
            cumulative.append(cumulative[-1] + distance)
        return cls(name, points, tuple(cumulative))

    @property
    def length_m(self) -> float:
        return self.cumulative_m[-1]

    def point_at(self, progress_m: float) -> Point:
        if not math.isfinite(progress_m) or not 0 <= progress_m <= self.length_m:
            raise ValueError("progress_m is outside route length")
        if progress_m == self.length_m:
            return self.points_xy[-1]
        index = max(0, bisect.bisect_right(self.cumulative_m, progress_m) - 1)
        start, end = self.points_xy[index], self.points_xy[index + 1]
        segment_m = self.cumulative_m[index + 1] - self.cumulative_m[index]
        fraction = (progress_m - self.cumulative_m[index]) / segment_m
        return (
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        )

    def transformed(
        self, *, rotation_degrees: float = 0.0, east_m: float = 0.0, north_m: float = 0.0
    ) -> RouteGeometry:
        """길이는 바꾸지 않는 회전·이동. 비공간 통계 불변성 시험용이기도 하다."""
        angle = math.radians(rotation_degrees)
        cosine, sine = math.cos(angle), math.sin(angle)
        points = tuple(
            (
                x * cosine - y * sine + east_m,
                x * sine + y * cosine + north_m,
            )
            for x, y in self.points_xy
        )
        return RouteGeometry.from_points(self.name, points)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "length_m": round(self.length_m, 6),
            "points_xy": [[round(x, 6), round(y, 6)] for x, y in self.points_xy],
        }


def _scaled(name: str, points: tuple[Point, ...], target_length_m: float) -> RouteGeometry:
    raw = RouteGeometry.from_points(name, points)
    scale = target_length_m / raw.length_m
    return RouteGeometry.from_points(name, tuple((x * scale, y * scale) for x, y in points))


def route_preset(name: RouteName, length_m: float) -> RouteGeometry:
    if not math.isfinite(length_m) or length_m <= 0:
        raise ValueError("length_m must be finite and positive")
    if name == "straight":
        return RouteGeometry.from_points(name, ((0.0, 0.0), (length_m, 0.0)))
    if name == "s-curve":
        samples = 80
        points = tuple(
            (
                length_m * index / samples,
                length_m * 0.075 * math.sin(2 * math.pi * index / samples),
            )
            for index in range(samples + 1)
        )
        return _scaled(name, points, length_m)
    if name == "loop":
        samples = 96
        radius = length_m / (2 * math.pi)
        points = tuple(
            (
                radius * (math.cos(2 * math.pi * index / samples) - 1),
                radius * math.sin(2 * math.pi * index / samples),
            )
            for index in range(samples + 1)
        )
        return _scaled(name, points, length_m)
    if name == "out-and-back":
        return RouteGeometry.from_points(
            name, ((0.0, 0.0), (length_m / 2, 0.0), (0.0, 0.0))
        )
    raise ValueError(f"unknown route preset: {name}")
