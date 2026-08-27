"""체류 읽기 계약. `app/features/territory/dwell.py`.

M0·M0.5 가 낸 규칙 둘이 여기서 지켜지는지 본다.

    국소 적분으로 읽는다   셀 하나 값은 격자에 따라 달라지지만 둘레 적분은 안 달라진다
    산책 수로 나눈다       총량으로 견주면 빈도가 체류로 위장한다

그리고 **의미를 안 붙인다.** 여기 나오는 것은 "이 자리 둘레의 산책당 체류" 까지고,
"냄새 스팟" 이니 "좋아하는 곳" 이니는 없다.
"""

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.features.territory.dwell import (
    contrast,
    metres_between,
    radius_floor,
    read_at,
    route_baseline,
)
from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import NARROW_STEP, paint_sheet
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix

EARTH_R = 6_371_000.0
LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 7, 1, 9, tzinfo=UTC)
SPEED_MPS = 1.2
LEG_M = 120.0
COARSE, FINE = 15.0, 8.0


def _at(x_m: float, wobble: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    east, north = x_m + wobble[0], wobble[1]
    return (LAT + math.degrees(north / EARTH_R),
            LNG + math.degrees(east / (EARTH_R * math.cos(math.radians(LAT)))))


STOP_AT = _at(LEG_M / 2)
AWAY_AT = _at(LEG_M / 6)          # 경로 위지만 멈춘 자리에서 먼 곳


def _spec(radius_u: float, min_peak: float = 0.0) -> LayerSpec:
    return LayerSpec(selector=Selector.of(),
                     aggregation=Aggregation(metric="walks", min_peak=min_peak),
                     projection=Projection(radius_u=radius_u, brush=NARROW_STEP.name,
                                           profile_fp=NARROW_STEP.fingerprint))


def _sheet(walk_id: str, stop_s: int, radius_u: float, *, at: datetime = START,
           jitter_m: float = 0.0, seed: int = 7):
    """동쪽 120m 를 1.2m/s 로, 한가운데서 `stop_s` 초 서 있는 산책 한 번."""
    import random
    rng = random.Random(seed)
    fixes: list[WalkFix] = []
    seconds = 0.0

    def push(x_m: float) -> None:
        nonlocal seconds
        wobble = ((rng.gauss(0, jitter_m), rng.gauss(0, jitter_m)) if jitter_m
                  else (0.0, 0.0))
        lat, lng = _at(x_m, wobble)
        fixes.append(WalkFix(client_seq=len(fixes), chain_index=0,
                             at=at + timedelta(seconds=seconds),
                             lat=lat, lng=lng, accuracy_m=5.0, is_mock=False))
        seconds += 1.0

    steps = int((LEG_M / 2) / SPEED_MPS)
    for i in range(steps + 1):
        push(i * SPEED_MPS)
    for _ in range(stop_s):
        push(LEG_M / 2)
    for i in range(1, steps + 1):
        push(LEG_M / 2 + i * SPEED_MPS)

    segs = compute_facts("w", "d", at, fixes[-1].at + timedelta(seconds=1), fixes).segments
    return paint_sheet(walk_id, at, segs, radius_u, NARROW_STEP)


def _days(count: int, stop_s: int, radius_u: float, **kw):
    return [_sheet(f"w{i}", stop_s, radius_u, at=START + timedelta(days=i), seed=i, **kw)
            for i in range(count)]


# ---- 분자·분모를 달고 다닌다 ------------------------------------------------------------


def test_a_reading_carries_its_numerator_and_denominator():
    """비율만 들고 다니면 `2/3` 인지 `200/300` 인지 모른다 — `VisitRate` 와 같은 규율."""
    sheets = _days(10, stop_s=60, radius_u=FINE)
    reading = read_at(sheets, _spec(FINE), STOP_AT, 20.0)
    assert (reading.walks, reading.selected, reading.total) == (10, 10, 10)
    assert reading.mass > 0 and reading.per_walk == reading.mass / 10
    assert reading.radius_m == 20.0 and reading.centre == STOP_AT


def test_no_selected_walks_reads_as_unknown_not_zero():
    """조건에 걸린 산책이 없으면 0 이 아니라 계산 불가다 (`VisitRate.rate` 와 같다)."""
    future = LayerSpec(
        selector=Selector.of(since=datetime(2030, 1, 1, tzinfo=UTC).date()),
        aggregation=Aggregation(metric="walks"),
        projection=Projection(radius_u=FINE, brush=NARROW_STEP.name,
                              profile_fp=NARROW_STEP.fingerprint))
    reading = read_at(_days(5, stop_s=60, radius_u=FINE), future, STOP_AT, 20.0)
    assert reading.selected == 0
    assert reading.per_walk is None and reading.visit_rate is None


# ---- 규칙 1 — 국소 적분은 격자에 안 흔들린다 --------------------------------------------


def test_absolute_dwell_still_swings_with_the_grid_but_contrast_does_not():
    """**절대값은 아직 못 견준다. 그래서 대비로 읽는다.**

    적분하면 셀 배치의 우연은 사라지지만 격자 밀도는 안 사라진다 — 지금 칠하기 kernel 에
    정규화가 없어서다(질량 보존 측정이 잰 결함, 코드는 아직 안 고쳤다).

    그런데 비율에서는 그 인자가 분자·분모에서 상쇄된다. 그래서 이 층이 내는 판단 재료는
    `per_walk` 가 아니라 `contrast` 다.
    """
    absolute, relative = {}, {}
    for radius_u in (COARSE, FINE):
        sheets, spec = _days(5, stop_s=120, radius_u=radius_u), _spec(radius_u)
        reading = read_at(sheets, spec, STOP_AT, 25.0)
        absolute[radius_u] = reading.per_walk
        relative[radius_u] = contrast(reading, route_baseline(sheets, spec, 25.0))

    swing = max(absolute.values()) / min(absolute.values())
    steady = max(relative.values()) / min(relative.values())
    assert swing > 3.0, f"절대값이 안 흔들린다 — kernel 이 바뀐 것이다: {absolute}"
    assert steady < 1.8, f"대비까지 흔들린다: {relative}"
    assert steady < swing / 2, "대비가 절대값보다 안정적이어야 한다"


def test_reading_below_the_grid_spacing_is_refused_by_the_floor():
    """격자가 못 담는 해상도로 물으면 답이 격자 배치에 좌우된다 — 하한을 계산해 준다."""
    floor_coarse = radius_floor(_spec(COARSE), LAT)
    floor_fine = radius_floor(_spec(FINE), LAT)
    assert floor_coarse > floor_fine
    assert 19.0 < floor_coarse < 22.0, f"15 단위 간격이 20.6m 근처여야 한다: {floor_coarse}"


# ---- 규칙 2 — 산책 수로 나눈다 ----------------------------------------------------------


def test_dividing_by_walks_stops_frequency_masquerading_as_dwell():
    """**총량으로 견주면 빈도가 체류로 위장한다.**

    2 분 머문 5 회 대 그냥 지나간 20 회. 총량은 통과 쪽이 클 수 있지만 산책당은 아니다.
    """
    lingered = _days(5, stop_s=120, radius_u=FINE)
    passed = _days(30, stop_s=0, radius_u=FINE)

    a = read_at(lingered, _spec(FINE), STOP_AT, 25.0)
    b = read_at(passed, _spec(FINE), STOP_AT, 25.0)
    assert b.mass > a.mass, "총량 함정이 사라졌다 — 이 테스트의 전제가 바뀐 것이다"
    assert a.per_walk > b.per_walk * 2, (
        f"산책당 {a.per_walk:.1f} 대 {b.per_walk:.1f}")


def test_presence_and_dwell_are_read_separately():
    """같은 자리를 두 축으로 읽는다 — 서로 대신 못 한다."""
    lingered = _days(5, stop_s=120, radius_u=FINE)
    passed = _days(20, stop_s=0, radius_u=FINE)
    a = read_at(lingered, _spec(FINE), STOP_AT, 25.0)
    b = read_at(passed, _spec(FINE), STOP_AT, 25.0)

    assert b.visit_rate == a.visit_rate == 1.0      # 등장으로는 똑같이 매번 갔다
    assert a.per_walk > b.per_walk                  # 체류로는 갈린다


# ---- 기준선과 대비 ----------------------------------------------------------------------


def test_the_baseline_uses_the_median_so_the_peak_does_not_set_it():
    """봉우리가 기준선을 정하면 봉우리를 봉우리와 견주게 된다.

    중앙값은 평균보다 봉우리에 덜 끌린다. **면역은 아니다** — 체류가 산책 시간의 큰 몫을
    차지하면 봉우리 둘레 칸이 칠해진 칸의 상당수가 되어 중앙값도 따라 오른다. 그때는
    대비가 실제보다 **작게** 나오고, 그건 거짓 양성을 늘리지 않는 보수적인 방향이다.
    """
    from statistics import mean, median

    from app.features.territory.dwell import _cells_within
    from app.features.territory.layers import render
    from app.geo.cells import hex_center_latlng

    sheets, spec = _days(5, stop_s=240, radius_u=FINE), _spec(FINE)
    layer = render(sheets, spec)
    centres = {c: hex_center_latlng(*c, FINE) for c in layer.canvas}
    readings = [sum(layer.canvas[c].occupancy
                    for c in _cells_within(centres, centre, 25.0, FINE)) / layer.selected
                for centre in centres.values()]

    got = route_baseline(sheets, spec, 25.0)
    assert got == pytest.approx(median(readings))
    assert got < mean(readings), "중앙값이 평균보다 작아야 봉우리에 덜 끌린 것이다"


def test_a_stop_stands_out_against_the_route_baseline():
    """**이 파일의 핵심.** 멈춘 자리가 경로의 전형보다 뚜렷하게 진하다."""
    sheets = _days(10, stop_s=120, radius_u=FINE)
    spec = _spec(FINE)
    base = route_baseline(sheets, spec, 25.0)

    at_stop = contrast(read_at(sheets, spec, STOP_AT, 25.0), base)
    elsewhere = contrast(read_at(sheets, spec, AWAY_AT, 25.0), base)
    assert at_stop > elsewhere * 2, f"멈춘 자리 {at_stop:.1f} 대 경로 위 {elsewhere:.1f}"
    assert at_stop > 2.0


def test_a_walk_with_no_stop_has_no_standout_place():
    """멈춤을 안 심으면 어디도 튀지 않아야 한다 — **거짓 양성의 바닥**을 보는 자리다.

    문턱을 상수로 안 고르는 이유가 여기 있다. 몇 배부터 "반복 체류" 인지는 이런 대조
    자료에서 얻을 값이고, 그 측정(M3)은 아직 안 했다.
    """
    sheets = _days(10, stop_s=0, radius_u=FINE)
    spec = _spec(FINE)
    base = route_baseline(sheets, spec, 25.0)
    for where in (STOP_AT, AWAY_AT):
        assert contrast(read_at(sheets, spec, where, 25.0), base) < 2.0


def test_contrast_is_unknown_when_there_is_nothing_to_compare():
    assert contrast(read_at([], _spec(FINE), STOP_AT, 25.0), None) is None


# ---- 지터 --------------------------------------------------------------------------------


@pytest.mark.parametrize("radius_u", [COARSE, FINE])
def test_jitter_does_not_erase_the_standout(radius_u):
    """σ=8m 지터를 넣어도 멈춘 자리가 경로의 전형보다 진하게 남는가."""
    sheets = _days(10, stop_s=120, radius_u=radius_u, jitter_m=8.0)
    spec = _spec(radius_u)
    base = route_baseline(sheets, spec, 25.0)
    assert contrast(read_at(sheets, spec, STOP_AT, 25.0), base) > 2.0


def test_metres_between_is_symmetric_and_zero_at_home():
    assert metres_between(STOP_AT, STOP_AT) == 0.0
    assert metres_between(STOP_AT, AWAY_AT) == pytest.approx(
        metres_between(AWAY_AT, STOP_AT))
    assert metres_between(_at(0.0), _at(100.0)) == pytest.approx(100.0, abs=0.5)
