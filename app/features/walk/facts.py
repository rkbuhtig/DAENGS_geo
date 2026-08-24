"""WalkFix 열 → WalkFacts. 순수함수 — DB·시계·난수 없음, 같은 입력은 같은 사실.

계산 정책은 Android `WalkCalculationPolicy` v1 을 미러링한다
(android/.../walk/WalkFactsRecorder.kt). 값이 다르면 앱 미리보기와 서버 확정치가
어긋난다 — 바꿀 땐 양쪽을 같이 바꾸고 버전을 올린다.

분류 규칙 (연속한 수용 점 쌍마다):
  dt <= 0            → out_of_order 거부. 시각 역행을 이동으로 만들지 않는다
  dist > 200m        → jump. 구간 단절 — 시간·거리 어디에도 안 쌓는다 (GPS 튐/차량)
  speed >= 0.5 m/s   → moving:  moving_s += dt, moving_distance += dist
  speed <  0.5 m/s   → 정지 후보: 원 distance 에만 쌓인다 (지터 포함 참고값)
정지 후보가 10초 이상 이어지면 stop 하나다. "정지"까지만 — 이유는 붙이지 않는다.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.features.walk.models import WalkFacts, WalkFix

CALCULATION_VERSION = 1          # Android WalkCalculationPolicy.version 과 짝
MOVING_SPEED_MPS = 0.5
MIN_STOP_S = 10.0
MAX_ACCURACY_M = 50.0
MAX_JUMP_M = 200.0
MAX_SAMPLES = 20_000


@dataclass
class FixQuality:
    """수신 원본이 사실이 되기까지 어디서 얼마나 걸러졌나. 계약 밖 — 운영·디버깅용."""

    received: int = 0
    accepted: int = 0
    rejected_low_accuracy: int = 0
    rejected_out_of_order: int = 0
    unknown_accuracy: int = 0
    jump_breaks: int = 0
    dropped_at_capacity: int = 0

    def to_dict(self) -> dict:
        return dict(vars(self))


@dataclass
class ComputedFacts:
    facts: WalkFacts
    quality: FixQuality = field(default_factory=FixQuality)


def _haversine_m(a: WalkFix, b: WalkFix) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def compute_facts(
    session_id: str,
    dog_id: str,
    started_at: datetime,
    ended_at: datetime,
    fixes: list[WalkFix],
) -> ComputedFacts:
    """fixes 는 (at, 수신순) 정렬로 들어온다. 점이 2개 미만이면 전부 0 인 사실이 나온다."""
    q = FixQuality(received=len(fixes))

    accepted: list[WalkFix] = []
    for f in fixes:
        if len(accepted) >= MAX_SAMPLES:
            q.dropped_at_capacity += 1
            continue
        if f.accuracy_m is None:
            q.unknown_accuracy += 1      # 모름은 거부 사유가 아니다 — 세되 받는다
        elif f.accuracy_m > MAX_ACCURACY_M:
            q.rejected_low_accuracy += 1
            continue
        accepted.append(f)
    q.accepted = len(accepted)

    duration = 0.0
    distance = 0.0
    moving_s = 0.0
    moving_distance = 0.0
    stop_count = 0
    stop_s = 0.0
    still_run = 0.0                      # 진행 중인 정지 후보 구간의 누적 초

    def close_still_run() -> None:
        nonlocal stop_count, stop_s, still_run
        if still_run >= MIN_STOP_S:
            stop_count += 1
            stop_s += still_run
        still_run = 0.0

    prev: WalkFix | None = None
    for cur in accepted:
        if prev is None:
            prev = cur
            continue
        dt = (cur.at - prev.at).total_seconds()
        if dt <= 0:
            q.rejected_out_of_order += 1
            continue                     # prev 유지 — 역행 점은 없던 것으로
        dist = _haversine_m(prev, cur)
        if dist > MAX_JUMP_M:
            q.jump_breaks += 1
            close_still_run()            # 단절 너머로 정지 구간을 잇지 않는다
            prev = cur
            continue
        duration += dt
        distance += dist
        if dist / dt >= MOVING_SPEED_MPS:
            close_still_run()
            moving_s += dt
            moving_distance += dist
        else:
            still_run += dt
        prev = cur
    close_still_run()

    moving_distance = min(moving_distance, distance)
    facts = WalkFacts(
        session_id=session_id,
        dog_id=dog_id,
        # UTC 정규화 — 같은 순간의 +09:00 표기와 Z 표기가 다른 사실처럼 보이면 안 된다.
        # 멱등 재요청은 저장본과 바이트까지 같은 응답을 받는다.
        started_at=started_at.astimezone(UTC),
        ended_at=ended_at.astimezone(UTC),
        duration_s=round(duration),
        distance_m=round(distance),
        moving_distance_m=round(moving_distance),
        moving_s=round(moving_s),
        stop_count=stop_count,
        stop_s=min(round(stop_s), max(round(duration) - round(moving_s), 0)),
        avg_speed_mps=round(moving_distance / moving_s, 3) if moving_s > 0 else None,
        fix_count=len(accepted),
    )
    return ComputedFacts(facts=facts, quality=q)
