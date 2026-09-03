"""CanonicalTrail에서 저장 후보 동선을 만들고 노출·왜곡을 함께 잰다.

제품 projector가 아니다. Decision #69의 저장 금지를 바꾸기 전에 숫자와 실패 모양을
보는 스파이크다. 특히 route-distance trim과 endpoint spatial mask를 같은 입력에서
비교한다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Literal

from app.features.walk.facts import CanonicalTrail, Segment
from app.geo.cells import EARTH_R

EndpointProtection = Literal["none", "path_trim", "spatial_mask"]


@dataclass(frozen=True)
class DiaryRouteProfile:
    id: str
    endpoint_protection: EndpointProtection
    endpoint_radius_m: float
    quantization_m: float
    simplification_m: float


@dataclass(frozen=True)
class _Point:
    x: float
    y: float
    elapsed_s: float
    chain_index: int


@dataclass(frozen=True)
class _Fragment:
    source_chain_index: int
    points: tuple[_Point, ...]


EXPERIMENT_PROFILES = (
    DiaryRouteProfile("canonical-detail", "none", 0.0, 0.0, 0.0),
    DiaryRouteProfile("trim-60m", "path_trim", 60.0, 0.0, 0.0),
    DiaryRouteProfile("zone-60m-q5-s5", "spatial_mask", 60.0, 5.0, 5.0),
    DiaryRouteProfile("zone-100m-q10-s8", "spatial_mask", 100.0, 10.0, 8.0),
)


def _to_local(lat: float, lng: float, origin_lat: float, origin_lng: float) -> tuple[float, float]:
    return (
        math.radians(lng - origin_lng) * EARTH_R * math.cos(math.radians(origin_lat)),
        math.radians(lat - origin_lat) * EARTH_R,
    )


def _to_lat_lng(x: float, y: float, origin_lat: float, origin_lng: float) -> tuple[float, float]:
    return (
        origin_lat + math.degrees(y / EARTH_R),
        origin_lng + math.degrees(x / (EARTH_R * math.cos(math.radians(origin_lat)))),
    )


def _same_fix(left, right) -> bool:
    return left.client_seq == right.client_seq and left.at == right.at


def _canonical_fragments(
    trail: CanonicalTrail, started_at: datetime
) -> tuple[tuple[_Fragment, ...], float, float]:
    if not trail.segments:
        return (), 0.0, 0.0
    origin = trail.segments[0].a
    fragments: list[_Fragment] = []
    current: list[_Point] = []
    current_chain = trail.segments[0].chain_index
    previous: Segment | None = None

    def point(fix, chain_index: int) -> _Point:
        x, y = _to_local(fix.lat, fix.lng, origin.lat, origin.lng)
        return _Point(x, y, (fix.at - started_at).total_seconds(), chain_index)

    for segment in trail.segments:
        continues = (
            previous is not None
            and segment.chain_index == current_chain
            and _same_fix(previous.b, segment.a)
        )
        if not continues:
            if len(current) >= 2:
                fragments.append(_Fragment(current_chain, tuple(current)))
            current_chain = segment.chain_index
            current = [point(segment.a, current_chain)]
        current.append(point(segment.b, current_chain))
        previous = segment
    if len(current) >= 2:
        fragments.append(_Fragment(current_chain, tuple(current)))
    return tuple(fragments), origin.lat, origin.lng


def _distance(a: _Point, b: _Point) -> float:
    return math.hypot(b.x - a.x, b.y - a.y)


def _length(fragment: _Fragment) -> float:
    return math.fsum(_distance(a, b) for a, b in zip(fragment.points, fragment.points[1:]))


def _interpolate(a: _Point, b: _Point, ratio: float) -> _Point:
    return _Point(
        x=a.x + (b.x - a.x) * ratio,
        y=a.y + (b.y - a.y) * ratio,
        elapsed_s=a.elapsed_s + (b.elapsed_s - a.elapsed_s) * ratio,
        chain_index=a.chain_index,
    )


def _trim_front(fragment: _Fragment, distance_m: float) -> _Fragment | None:
    remaining = distance_m
    points = fragment.points
    for index, (a, b) in enumerate(pairwise(points)):
        segment_m = _distance(a, b)
        if remaining < segment_m:
            first = _interpolate(a, b, remaining / segment_m) if segment_m else b
            return _Fragment(fragment.source_chain_index, (first, *points[index + 1 :]))
        remaining -= segment_m
    return None


def _trim_back(fragment: _Fragment, distance_m: float) -> _Fragment | None:
    reversed_fragment = _Fragment(
        fragment.source_chain_index, tuple(reversed(fragment.points))
    )
    trimmed = _trim_front(reversed_fragment, distance_m)
    if trimmed is None:
        return None
    return _Fragment(trimmed.source_chain_index, tuple(reversed(trimmed.points)))


def _path_trim(fragments: tuple[_Fragment, ...], distance_m: float) -> tuple[_Fragment, ...]:
    if not fragments or distance_m <= 0:
        return fragments

    remaining = distance_m
    front_trimmed: list[_Fragment] = []
    for index, fragment in enumerate(fragments):
        fragment_m = _length(fragment)
        if remaining >= fragment_m:
            remaining -= fragment_m
            continue
        trimmed = _trim_front(fragment, remaining)
        if trimmed is not None:
            front_trimmed = [trimmed, *fragments[index + 1 :]]
        break
    if not front_trimmed:
        return ()

    remaining = distance_m
    output: list[_Fragment] = []
    for index in range(len(front_trimmed) - 1, -1, -1):
        fragment = front_trimmed[index]
        fragment_m = _length(fragment)
        if remaining >= fragment_m:
            remaining -= fragment_m
            continue
        trimmed = _trim_back(fragment, remaining)
        if trimmed is not None:
            output = [*front_trimmed[:index], trimmed]
        break
    return tuple(item for item in output if len(item.points) >= 2)


def _quantize(fragments: tuple[_Fragment, ...], grid_m: float) -> tuple[_Fragment, ...]:
    if grid_m <= 0:
        return fragments
    output = []
    for fragment in fragments:
        points = []
        for point in fragment.points:
            snapped = _Point(
                round(point.x / grid_m) * grid_m,
                round(point.y / grid_m) * grid_m,
                point.elapsed_s,
                point.chain_index,
            )
            if not points or (snapped.x, snapped.y) != (points[-1].x, points[-1].y):
                points.append(snapped)
        if len(points) >= 2:
            output.append(_Fragment(fragment.source_chain_index, tuple(points)))
    return tuple(output)


def _point_segment_distance(point: _Point, a: _Point, b: _Point) -> float:
    dx, dy = b.x - a.x, b.y - a.y
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return _distance(point, a)
    ratio = max(0.0, min(1.0, ((point.x - a.x) * dx + (point.y - a.y) * dy) / denominator))
    projection = _interpolate(a, b, ratio)
    return _distance(point, projection)


def _simplify_points(points: tuple[_Point, ...], tolerance_m: float) -> tuple[_Point, ...]:
    if tolerance_m <= 0 or len(points) <= 2:
        return points
    first, last = points[0], points[-1]
    distances = [_point_segment_distance(point, first, last) for point in points[1:-1]]
    if not distances or max(distances) <= tolerance_m:
        return (first, last)
    split = distances.index(max(distances)) + 1
    left = _simplify_points(points[: split + 1], tolerance_m)
    right = _simplify_points(points[split:], tolerance_m)
    return (*left[:-1], *right)


def _simplify(fragments: tuple[_Fragment, ...], tolerance_m: float) -> tuple[_Fragment, ...]:
    return tuple(
        _Fragment(fragment.source_chain_index, _simplify_points(fragment.points, tolerance_m))
        for fragment in fragments
    )


def _inside_interval(
    a: _Point, b: _Point, centre: _Point, radius_m: float
) -> tuple[float, float] | None:
    dx, dy = b.x - a.x, b.y - a.y
    qa = dx * dx + dy * dy
    if qa == 0:
        return (0.0, 1.0) if _distance(a, centre) < radius_m else None
    px, py = a.x - centre.x, a.y - centre.y
    qb = 2 * (px * dx + py * dy)
    qc = px * px + py * py - radius_m * radius_m
    discriminant = qb * qb - 4 * qa * qc
    if discriminant <= 0:
        return (0.0, 1.0) if qc < 0 else None
    root = math.sqrt(discriminant)
    start = max(0.0, (-qb - root) / (2 * qa))
    end = min(1.0, (-qb + root) / (2 * qa))
    if start >= end:
        return None
    return start, end


def _outside_intervals(
    a: _Point, b: _Point, centres: tuple[_Point, ...], radius_m: float
) -> tuple[tuple[float, float], ...]:
    inside = sorted(
        interval
        for centre in centres
        if (interval := _inside_interval(a, b, centre, radius_m)) is not None
    )
    merged: list[list[float]] = []
    for start, end in inside:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    outside = []
    cursor = 0.0
    for start, end in merged:
        if cursor < start:
            outside.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < 1.0:
        outside.append((cursor, 1.0))
    return tuple(outside)


def _same_point(a: _Point, b: _Point) -> bool:
    return math.isclose(a.x, b.x, abs_tol=1e-7) and math.isclose(a.y, b.y, abs_tol=1e-7)


def _spatial_mask(
    fragments: tuple[_Fragment, ...], centres: tuple[_Point, ...], radius_m: float
) -> tuple[_Fragment, ...]:
    if radius_m <= 0:
        return fragments
    output: list[_Fragment] = []
    for fragment in fragments:
        current: list[_Point] = []
        for a, b in zip(fragment.points, fragment.points[1:]):
            intervals = _outside_intervals(a, b, centres, radius_m)
            for start, end in intervals:
                left, right = _interpolate(a, b, start), _interpolate(a, b, end)
                if current and _same_point(current[-1], left):
                    current.append(right)
                else:
                    if len(current) >= 2:
                        output.append(_Fragment(fragment.source_chain_index, tuple(current)))
                    current = [left, right]
            should_close = not intervals or intervals[-1][1] < 1.0
            if should_close and len(current) >= 2:
                output.append(_Fragment(fragment.source_chain_index, tuple(current)))
                current = []
        if len(current) >= 2:
            output.append(_Fragment(fragment.source_chain_index, tuple(current)))
    return tuple(output)


def _nearest_to_geometry(point: _Point, fragments: tuple[_Fragment, ...]) -> float | None:
    distances = [
        _point_segment_distance(point, a, b)
        for fragment in fragments
        for a, b in zip(fragment.points, fragment.points[1:])
    ]
    return min(distances) if distances else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _speed_thresholds(segments: tuple[Segment, ...]) -> tuple[float, float] | None:
    speeds = [segment.dist / segment.dt for segment in segments if segment.dt > 0]
    low, high = _percentile(speeds, 1 / 3), _percentile(speeds, 2 / 3)
    return (low, high) if low is not None and high is not None else None


def _speed_band(
    chain_index: int,
    elapsed_s: float,
    segments: tuple[Segment, ...],
    started_at: datetime,
    thresholds: tuple[float, float] | None,
) -> str:
    candidates = [segment for segment in segments if segment.chain_index == chain_index]
    if not candidates or thresholds is None:
        return "unknown"
    segment = min(
        candidates,
        key=lambda item: abs(
            (((item.a.at - started_at).total_seconds() + (item.b.at - started_at).total_seconds()) / 2)
            - elapsed_s
        ),
    )
    speed = segment.dist / segment.dt
    if speed <= thresholds[0]:
        return "relative_slow"
    if speed >= thresholds[1]:
        return "relative_fast"
    return "relative_mid"


def _serialize_fragments(
    fragments: tuple[_Fragment, ...],
    trail: CanonicalTrail,
    started_at: datetime,
    origin_lat: float,
    origin_lng: float,
) -> list[dict[str, object]]:
    thresholds = _speed_thresholds(trail.segments)
    rows = []
    for index, fragment in enumerate(fragments):
        points = []
        for point in fragment.points:
            lat, lng = _to_lat_lng(point.x, point.y, origin_lat, origin_lng)
            points.append(
                {"lat": round(lat, 7), "lng": round(lng, 7), "elapsed_s": round(point.elapsed_s, 1)}
            )
        bands = [
            _speed_band(
                fragment.source_chain_index,
                (a.elapsed_s + b.elapsed_s) / 2,
                trail.segments,
                started_at,
                thresholds,
            )
            for a, b in zip(fragment.points, fragment.points[1:])
        ]
        rows.append(
            {
                "fragment_index": index,
                "source_chain_index": fragment.source_chain_index,
                "points": points,
                "speed_bands": bands,
            }
        )
    return rows


def project_candidate(
    trail: CanonicalTrail, started_at: datetime, profile: DiaryRouteProfile
) -> dict[str, object]:
    canonical, origin_lat, origin_lng = _canonical_fragments(trail, started_at)
    if not canonical:
        return {
            "format": "walk-diary-route-candidate-v1",
            "status": "unavailable",
            "reason": "no_continuous_segments",
            "profile": vars(profile),
            "fragments": [],
            "metrics": {},
        }

    start, end = canonical[0].points[0], canonical[-1].points[-1]
    fragments = _quantize(canonical, profile.quantization_m)
    fragments = _simplify(fragments, profile.simplification_m)
    if profile.endpoint_protection == "path_trim":
        fragments = _path_trim(fragments, profile.endpoint_radius_m)
    elif profile.endpoint_protection == "spatial_mask":
        fragments = _spatial_mask(fragments, (start, end), profile.endpoint_radius_m)

    serialized = _serialize_fragments(fragments, trail, started_at, origin_lat, origin_lng)
    route_body = {"fragments": serialized}
    canonical_points = [point for fragment in canonical for point in fragment.points]
    fidelity_points = canonical_points
    if profile.endpoint_protection == "spatial_mask":
        fidelity_points = [
            point
            for point in canonical_points
            if _distance(point, start) >= profile.endpoint_radius_m
            and _distance(point, end) >= profile.endpoint_radius_m
        ]
    errors = [
        distance
        for point in fidelity_points
        if (distance := _nearest_to_geometry(point, fragments)) is not None
    ]
    canonical_length = math.fsum(_length(fragment) for fragment in canonical)
    output_length = math.fsum(_length(fragment) for fragment in fragments)
    start_exposure = _nearest_to_geometry(start, fragments)
    end_exposure = _nearest_to_geometry(end, fragments)
    metrics = {
        "canonical_vertex_count": len(canonical_points),
        "output_vertex_count": sum(len(fragment.points) for fragment in fragments),
        "encoded_json_bytes": len(
            json.dumps(route_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ),
        "retained_distance_pct": round(output_length / canonical_length * 100, 1)
        if canonical_length
        else 0.0,
        "fidelity_p95_m": round(_percentile(errors, 0.95) or 0.0, 2),
        "fidelity_max_m": round(max(errors), 2) if errors else None,
        "nearest_geometry_to_start_m": round(start_exposure, 2)
        if start_exposure is not None
        else None,
        "nearest_geometry_to_end_m": round(end_exposure, 2) if end_exposure is not None else None,
        "visible_fragment_count": len(fragments),
        "speed_band_change_count": sum(
            left != right
            for row in serialized
            for left, right in zip(row["speed_bands"], row["speed_bands"][1:])
        ),
    }
    return {
        "format": "walk-diary-route-candidate-v1",
        "status": "available" if fragments else "unavailable",
        "reason": None if fragments else "endpoint_protection_removed_entire_route",
        "profile": vars(profile),
        "fragments": serialized,
        "metrics": metrics,
    }


def build_diary_route_experiment(
    trail: CanonicalTrail, started_at: datetime
) -> dict[str, object]:
    candidates = [project_candidate(trail, started_at, profile) for profile in EXPERIMENT_PROFILES]
    canonical = candidates[0]
    return {
        "format": "walk-diary-route-experiment-v1",
        "semantics": {
            "scope": "single_session_diary_only",
            "persistence": "forbidden_experiment_only",
            "speed_bands": "session_relative_experiment_not_product_thresholds",
            "coordinates": "raw_sensitive_dev_payload",
        },
        "canonical_endpoint": {
            "start": canonical["fragments"][0]["points"][0] if canonical["fragments"] else None,
            "end": canonical["fragments"][-1]["points"][-1] if canonical["fragments"] else None,
        },
        "candidates": candidates,
    }
