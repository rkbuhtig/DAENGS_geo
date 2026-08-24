"""세그먼트 열 × 시설 후보 → FacilityEncounter. 순수함수 — 기하값까지만.

"지나쳤다/봤다"는 만들지 않는다. 판정은 app/scene/judgment.py 가 이 사실 위에서
규칙표+버전으로 한다. 여기서는 게임 히트박스처럼 반지름별 원(10/30/50m)에 대해
체류 시간을 재는데, 틱은 GPS 점이고 원 경계 통과 시각은 선분 위에서 보간한다 —
체류가 점 간격보다 정밀해지는 이유다.

좌표 수학은 첫 세그먼트 기준 등장방형 투영(미터). 산책 반경(수 km)에서 오차는 cm 급.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import date

from app.features.walk.facts import Segment
from app.features.walk.models import FacilityEncounter, MotionEventOccurrence

BANDS_M = (10.0, 30.0, 50.0)
MAX_BAND_M = max(BANDS_M)


@dataclass(frozen=True)
class FacilityCandidate:
    """store 가 궤적 50m 버퍼로 추린 시설 한 곳. 존재 필터 없음 — 폐업도 관측 대상이다."""

    facility_source: str
    facility_ref: str
    kind: str
    lat: float
    lng: float
    place_active: bool | None
    as_of: date | None


def _projector(origin_lat: float, origin_lng: float):
    kx = 111_320.0 * math.cos(math.radians(origin_lat))
    ky = 111_320.0

    def project(lat: float, lng: float) -> tuple[float, float]:
        return ((lng - origin_lng) * kx, (lat - origin_lat) * ky)

    return project


def _inside_interval(ax, ay, bx, by, r: float) -> tuple[float, float] | None:
    """선분 P(t)=A+t(B-A), t∈[0,1] 가 원점 중심 반지름 r 원 안에 있는 t 구간."""
    dx, dy = bx - ax, by - ay
    a = dx * dx + dy * dy
    if a == 0:                                   # 제자리 — 점이 안이면 전체
        return (0.0, 1.0) if ax * ax + ay * ay <= r * r else None
    b = 2 * (ax * dx + ay * dy)
    c = ax * ax + ay * ay - r * r
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    lo, hi = max((-b - sq) / (2 * a), 0.0), min((-b + sq) / (2 * a), 1.0)
    return (lo, hi) if lo < hi else None


def _closest(ax, ay, bx, by) -> tuple[float, float]:
    """(원점까지 최단거리, 그때의 t)."""
    dx, dy = bx - ax, by - ay
    a = dx * dx + dy * dy
    t = 0.0 if a == 0 else min(max(-(ax * dx + ay * dy) / a, 0.0), 1.0)
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py), t


def compute_encounters(
    session_id: str,
    segments: list[Segment],
    events: list[MotionEventOccurrence],
    candidates: list[FacilityCandidate],
) -> list[FacilityEncounter]:
    if not segments or not candidates:
        return []
    project = _projector(segments[0].a.lat, segments[0].a.lng)

    found: list[FacilityEncounter] = []
    for cand in candidates:
        fx, fy = project(cand.lat, cand.lng)
        min_lateral = math.inf
        offset_at_min = 0.0
        dwell = dict.fromkeys(BANDS_M, 0.0)
        pass_count = 0
        was_inside_max = False
        accuracies: list[float] = []

        for seg in segments:
            ax, ay = project(seg.a.lat, seg.a.lng)
            bx, by = project(seg.b.lat, seg.b.lng)
            ax, ay, bx, by = ax - fx, ay - fy, bx - fx, by - fy

            d, t = _closest(ax, ay, bx, by)
            if d < min_lateral:
                min_lateral = d
                # 정지 구간(moving=False)에선 이동거리가 안 자라므로 offset 은 구간 시작값
                offset_at_min = seg.offset_m + (seg.dist * t if seg.moving else 0.0)

            for r in BANDS_M:
                iv = _inside_interval(ax, ay, bx, by, r)
                if iv:
                    dwell[r] += (iv[1] - iv[0]) * seg.dt
            iv_max = _inside_interval(ax, ay, bx, by, MAX_BAND_M)
            if iv_max and not was_inside_max:
                pass_count += 1
            was_inside_max = bool(iv_max) and iv_max[1] >= 1.0

            if math.hypot(bx, by) <= MAX_BAND_M and seg.b.accuracy_m is not None:
                accuracies.append(seg.b.accuracy_m)

        if min_lateral > MAX_BAND_M:
            continue

        overlap = dict.fromkeys(BANDS_M, False)
        stop_s_10 = 0
        for ev in events:
            ex, ey = project(ev.lat, ev.lng)
            d = math.hypot(ex - fx, ey - fy)
            for r in BANDS_M:
                if d <= r:
                    overlap[r] = True
            if d <= BANDS_M[0]:
                stop_s_10 += ev.duration_s

        found.append(FacilityEncounter(
            session_id=session_id,
            event_index=0,                       # 정렬 뒤 채운다
            facility_source=cand.facility_source,
            facility_ref=cand.facility_ref,
            kind=cand.kind,
            lat=cand.lat, lng=cand.lng,
            place_active=cand.place_active,
            as_of=cand.as_of,
            min_lateral_m=round(min_lateral, 1),
            offset_m=round(offset_at_min, 1),
            dwell_s_10m=round(dwell[10.0]),
            dwell_s_30m=round(dwell[30.0]),
            dwell_s_50m=round(dwell[50.0]),
            pass_count=pass_count,
            stop_overlap_10m=overlap[10.0],
            stop_overlap_30m=overlap[30.0],
            stop_overlap_50m=overlap[50.0],
            stop_s_10m=stop_s_10,
            accuracy_p50_m=round(statistics.median(accuracies), 2) if accuracies else None,
        ))

    found.sort(key=lambda e: (e.offset_m, e.min_lateral_m, e.facility_ref))
    return [e.model_copy(update={"event_index": i}) for i, e in enumerate(found)]
