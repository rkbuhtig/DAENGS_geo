"""사실 계산의 성질 고정 — 같은 입력은 같은 사실, 걸음/정지/거부의 경계.

전부 순수함수 테스트다. DB 없음. 좌표는 동해 원점에서 동쪽 미터로 만든다.
"""

import math
from datetime import UTC, datetime, timedelta

from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix

T0 = datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
ORIGIN = (37.4979, 130.9000)


def fix(t_s: float, east_m: float, *, accuracy: float | None = 10.0) -> WalkFix:
    lng = ORIGIN[1] + east_m / (111_320 * math.cos(math.radians(ORIGIN[0])))
    return WalkFix(at=T0 + timedelta(seconds=t_s), lat=ORIGIN[0], lng=lng,
                   accuracy_m=accuracy)


def walk_then_stop_then_walk() -> list[WalkFix]:
    """5초 간격. 0~60초 걷기(7m/5s=1.4m/s) → 60~90초 제자리 → 90~150초 걷기."""
    fixes = [fix(t, t / 5 * 7) for t in range(0, 65, 5)]            # 0..60s, 0..84m
    fixes += [fix(t, 84) for t in range(65, 90, 5)]                 # 정지
    fixes += [fix(t, 84 + (t - 90) / 5 * 7) for t in range(90, 155, 5)]
    return fixes


def compute(fixes: list[WalkFix], ended_s: float = 150):
    return compute_facts("s1", "halmae", T0, T0 + timedelta(seconds=ended_s), fixes)


def test_same_input_same_facts():
    a = compute(walk_then_stop_then_walk()).facts
    b = compute(walk_then_stop_then_walk()).facts
    assert a.model_dump() == b.model_dump()


def test_walk_stop_walk_boundaries():
    r = compute(walk_then_stop_then_walk())
    f = r.facts
    assert f.stop_count == 1
    assert f.stop_s >= 25                       # 60~90초 정지 (마지막 5초는 걷기 쌍에 걸침)
    assert f.moving_s + f.stop_s <= f.duration_s
    assert 150 <= f.moving_distance_m <= f.distance_m <= 180
    assert f.avg_speed_mps and 1.3 <= f.avg_speed_mps <= 1.5


def test_low_accuracy_is_rejected_unknown_is_not():
    fixes = [fix(0, 0), fix(5, 7, accuracy=80.0), fix(10, 14, accuracy=None), fix(15, 21)]
    r = compute(fixes, 15)
    assert r.quality.rejected_low_accuracy == 1
    assert r.quality.unknown_accuracy == 1
    assert r.facts.fix_count == 3               # 80m 짜리만 빠졌다


def test_jump_breaks_do_not_accumulate():
    fixes = [fix(0, 0), fix(5, 7), fix(10, 500), fix(15, 507)]      # 10초에 493m 튐
    r = compute(fixes, 15)
    assert r.quality.jump_breaks == 1
    assert r.facts.distance_m == 14             # 7m + (튐 제외) + 7m
    assert r.facts.duration_s == 10             # 튐 구간의 5초는 어디에도 없다


def test_time_going_backwards_is_rejected():
    fixes = [fix(0, 0), fix(5, 7)]
    fixes.append(WalkFix(at=fixes[1].at, lat=fixes[1].lat, lng=fixes[1].lng,
                         accuracy_m=10.0))      # 같은 시각 재전송
    r = compute(fixes, 10)
    assert r.quality.rejected_out_of_order == 1
    assert r.facts.distance_m == 7


def test_fewer_than_two_fixes_yields_zero_facts():
    r = compute([fix(0, 0)], 60)
    f = r.facts
    assert (f.duration_s, f.distance_m, f.moving_s, f.stop_count) == (0, 0, 0, 0)
    assert f.avg_speed_mps is None


def test_short_pause_is_not_a_stop():
    """10초 미만 정지 후보는 stop 이 아니다 — 신호 대기와 지터를 가르는 최소선."""
    fixes = [fix(0, 0), fix(5, 7), fix(10, 7), fix(15, 14)]         # 5초만 멈춤
    f = compute(fixes, 15).facts
    assert f.stop_count == 0
    assert f.moving_s + f.stop_s <= f.duration_s
