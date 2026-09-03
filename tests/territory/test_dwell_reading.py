"""체류 읽기 계약. `app/features/territory/dwell.py`.

M0·M0.5 가 낸 규칙 둘이 지켜지는지, 그리고 **측정 계약이 실제로 잠기는지** 본다.

    국소 적분으로 읽는다      셀 하나 값은 격자에 따라 달라진다
    산책 수로 나눈다          총량으로 견주면 빈도가 체류로 위장한다
    반경 하한을 거절한다      정의가 조건으로 걸었으면 코드가 막아야 한다
    문맥이 다르면 못 나눈다   여름 봉우리를 겨울 기준선으로 나누지 않는다
    값 셋을 갈라 낸다         `mass/selected` 는 등장 × 체류라 순수 dwell 이 아니다

그리고 **의미를 안 붙인다.** 여기 나오는 것은 "이 자리 둘레의 체류" 까지고, "냄새 스팟"
이니 "좋아하는 곳" 이니는 없다.
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
from app.features.territory.paint import NARROW_STEP, paint_sheet, paint_spec
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix

EARTH_R = 6_371_000.0
LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 7, 1, 9, tzinfo=UTC)
SPEED_MPS = 1.2
LEG_M = 120.0
COARSE, FINE = 15.0, 8.0
READ_M = 25.0                     # 두 격자 다 하한(20.6m / 11.0m)을 넘는 반경


def _at(x_m: float, wobble: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    east, north = x_m + wobble[0], wobble[1]
    return (LAT + math.degrees(north / EARTH_R),
            LNG + math.degrees(east / (EARTH_R * math.cos(math.radians(LAT)))))


STOP_AT = _at(LEG_M / 2)
AWAY_AT = _at(LEG_M / 6)          # 경로 위지만 멈춘 자리에서 먼 곳


def _spec(radius_u: float, min_peak: float = 0.0, **tags) -> LayerSpec:
    return LayerSpec(selector=Selector.of(**tags),
                     aggregation=Aggregation(metric="walks", min_peak=min_peak),
                     projection=Projection.from_paint_spec(
                         paint_spec(radius_u, NARROW_STEP)))


def _sheet(walk_id: str, stop_s: int, radius_u: float, *, at: datetime = START,
           jitter_m: float = 0.0, seed: int = 7, reach_stop: bool = True):
    """동쪽 120m 를 1.2m/s 로, 한가운데서 `stop_s` 초 서 있는 산책 한 번.

    `reach_stop=False` 면 절반 못 미쳐 돌아선다 — 멈춘 자리를 아예 안 밟는 산책이다.
    """
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

    far = LEG_M / 2 if reach_stop else 20.0
    steps = int(far / SPEED_MPS)
    for i in range(steps + 1):
        push(i * SPEED_MPS)
    if reach_stop:
        for _ in range(stop_s):
            push(LEG_M / 2)
        for i in range(1, steps + 1):
            push(LEG_M / 2 + i * SPEED_MPS)
    else:
        for i in range(1, steps + 1):
            push(far - i * SPEED_MPS)

    segs = compute_facts(
        "w", "d", at, fixes[-1].at + timedelta(seconds=1), fixes
    ).trail.segments
    return paint_sheet(walk_id, at, segs, radius_u, NARROW_STEP)


def _days(count: int, stop_s: int, radius_u: float, *, start: int = 0, **kw):
    return [_sheet(f"w{start + i}", stop_s, radius_u,
                   at=START + timedelta(days=start + i), seed=start + i, **kw)
            for i in range(count)]


# ---- 분자·분모와 측정 문맥을 달고 다닌다 -------------------------------------------------


def test_a_reading_carries_its_numerator_denominator_and_context():
    """비율만 들고 다니면 `2/3` 인지 `200/300` 인지 모른다 — `VisitRate` 와 같은 규율."""
    spec = _spec(FINE)
    reading = read_at(_days(10, stop_s=60, radius_u=FINE), spec, STOP_AT, READ_M)
    assert (reading.walks, reading.selected, reading.total) == (10, 10, 10)
    assert reading.mass > 0 and reading.radius_m == READ_M
    assert reading.spec_fingerprint == spec.fingerprint()


def test_a_baseline_carries_its_context_too():
    """기준선이 `float` 하나면 무엇으로 잰 값인지 사라진다 — 대비의 분모가 되는 값인데."""
    spec = _spec(FINE)
    base = route_baseline(_days(5, stop_s=60, radius_u=FINE), spec, READ_M)
    assert base is not None
    assert base.radius_m == READ_M and base.selected == 5
    assert base.spec_fingerprint == spec.fingerprint()


def test_no_selected_walks_reads_as_unknown_not_zero():
    """조건에 걸린 산책이 없으면 0 이 아니라 계산 불가다 (`VisitRate.rate` 와 같다)."""
    future = LayerSpec(
        selector=Selector.of(since=datetime(2030, 1, 1, tzinfo=UTC).date()),
        aggregation=Aggregation(metric="walks"),
        projection=Projection.from_paint_spec(paint_spec(FINE, NARROW_STEP)))
    sheets = _days(5, stop_s=60, radius_u=FINE)
    reading = read_at(sheets, future, STOP_AT, READ_M)
    assert reading.selected == 0
    assert reading.visit_rate is None and reading.expected_dwell_per_walk is None
    assert reading.dwell_per_visit is None
    assert route_baseline(sheets, future, READ_M) is None


# ---- 반경 하한을 실제로 거절한다 ---------------------------------------------------------


def test_a_radius_below_the_grid_spacing_is_refused():
    """**정의가 조건으로 걸었으면 코드가 막아야 한다.**

    처음엔 `radius_floor()` 가 숫자만 돌려주고 아무것도 안 막았다. 그러면 격자가 못 담는
    해상도로 물어도 정상 측정값처럼 나오고, 정의의 조건 3 이 장식이 된다.
    """
    spec = _spec(COARSE)                        # 셀 중심 간격 20.6m
    sheets = _days(5, stop_s=60, radius_u=COARSE)
    with pytest.raises(ValueError, match="격자가 못 담는다"):
        read_at(sheets, spec, STOP_AT, 10.0)
    with pytest.raises(ValueError, match="격자가 못 담는다"):
        route_baseline(sheets, spec, 10.0)

    assert read_at(sheets, spec, STOP_AT, 21.0).mass > 0    # 하한 위는 통과한다


def test_the_floor_follows_the_grid():
    assert radius_floor(_spec(COARSE), LAT) > radius_floor(_spec(FINE), LAT)
    assert 19.0 < radius_floor(_spec(COARSE), LAT) < 22.0


# ---- 문맥이 다르면 못 나눈다 --------------------------------------------------------------


def test_contrast_refuses_a_baseline_from_a_different_spec():
    """여름 봉우리를 겨울 기준선으로 나누지 않는다 — 값만 남고 문맥이 사라지는 병."""
    sheets = _days(10, stop_s=120, radius_u=FINE)
    reading = read_at(sheets, _spec(FINE), STOP_AT, READ_M)
    other = route_baseline(sheets, _spec(FINE, min_peak=0.9), READ_M)
    with pytest.raises(ValueError, match="spec 이 다르다"):
        contrast(reading, other)


def test_contrast_refuses_a_baseline_from_a_different_radius():
    sheets = _days(10, stop_s=120, radius_u=FINE)
    spec = _spec(FINE)
    with pytest.raises(ValueError, match="반경"):
        contrast(read_at(sheets, spec, STOP_AT, READ_M),
                 route_baseline(sheets, spec, 40.0))


def test_contrast_is_unknown_when_there_is_no_baseline():
    assert contrast(read_at(_days(3, 60, FINE), _spec(FINE), STOP_AT, READ_M),
                    None) is None


# ---- 값 셋을 갈라 낸다 --------------------------------------------------------------------


def test_expected_dwell_is_the_product_of_the_other_two():
    """**`mass / selected` 는 순수 dwell 축이 아니다.** 등장 × 갔을 때 체류다.

    처음엔 이걸 "dwell 축", `walks / selected` 를 "presence 축" 이라 부르고 둘을
    분리했다고 적었는데 **앞이 뒤를 이미 품고 있었다.**
    """
    reading = read_at(_days(10, stop_s=120, radius_u=FINE), _spec(FINE), STOP_AT, READ_M)
    assert reading.expected_dwell_per_walk == pytest.approx(
        reading.visit_rate * reading.dwell_per_visit)


def test_the_same_expected_dwell_can_hide_two_different_stories():
    """**갈라 내야 하는 이유.** 자주 조금 대 가끔 오래.

        매번 가서 짧게 머문다      등장 높음 · 갔을 때 체류 낮음
        가끔 가는데 오래 머문다    등장 낮음 · 갔을 때 체류 높음

    아주 다른 이야기인데 곱만 보면 구별이 흐려진다.
    """
    often = _days(10, stop_s=30, radius_u=FINE)
    rarely = (_days(2, stop_s=150, radius_u=FINE)
              + _days(8, stop_s=0, radius_u=FINE, start=2, reach_stop=False))

    a = read_at(often, _spec(FINE), STOP_AT, READ_M)
    b = read_at(rarely, _spec(FINE), STOP_AT, READ_M)
    assert a.visit_rate > b.visit_rate, "등장으로는 앞이 커야 한다"
    assert b.dwell_per_visit > a.dwell_per_visit, "갔을 때 체류로는 뒤가 커야 한다"


# ---- 규칙 1 — v2 질량 보존 뒤에는 격자가 값의 뜻을 바꾸지 않는다 --------------------------


def test_mass_conserving_dwell_is_stable_across_grid_resolutions():
    """**격자는 위치 해상도를 바꾸지만 occupancy 의 시간 의미는 바꾸지 않는다.**

    원형 읽기 경계에 걸친 셀 중심과 배분 오차 때문에 완전히 같지는 않다. 하지만 v1 처럼
    셀 밀도에 비례해 몇 배씩 불어나지는 않아야 한다. 대비 역시 같은 허용 범위에서 안정적이다.
    """
    absolute, relative = {}, {}
    for radius_u in (COARSE, FINE):
        sheets, spec = _days(5, stop_s=120, radius_u=radius_u), _spec(radius_u)
        reading = read_at(sheets, spec, STOP_AT, READ_M)
        absolute[radius_u] = reading.expected_dwell_per_walk
        relative[radius_u] = contrast(reading, route_baseline(sheets, spec, READ_M))

    swing = max(absolute.values()) / min(absolute.values())
    steady = max(relative.values()) / min(relative.values())
    assert swing < 1.1, f"격자가 occupancy 의 시간 의미를 바꾼다: {absolute}"
    assert steady < 1.1, f"격자에 따라 체류 대비가 지나치게 달라진다: {relative}"


# ---- 규칙 2 — 산책 수로 나눈다 ------------------------------------------------------------


def test_dividing_by_walks_stops_frequency_masquerading_as_dwell():
    """**총량으로 견주면 빈도가 체류로 위장한다.**"""
    lingered = _days(5, stop_s=120, radius_u=FINE)
    passed = _days(30, stop_s=0, radius_u=FINE)

    a = read_at(lingered, _spec(FINE), STOP_AT, READ_M)
    b = read_at(passed, _spec(FINE), STOP_AT, READ_M)
    assert b.mass > a.mass, "총량 함정이 사라졌다 — 이 테스트의 전제가 바뀐 것이다"
    assert a.expected_dwell_per_walk > b.expected_dwell_per_walk * 2
    assert a.dwell_per_visit > b.dwell_per_visit * 2


# ---- 기준선과 대비 ------------------------------------------------------------------------


def test_the_baseline_uses_the_median_so_the_peak_does_not_set_it():
    """봉우리가 기준선을 정하면 봉우리를 봉우리와 견주게 된다.

    중앙값은 평균보다 봉우리에 덜 끌린다. **면역은 아니다** — 체류가 산책 시간의 큰 몫을
    차지하면 중앙값도 따라 오르고, 그때는 대비가 실제보다 **작게** 나온다. 거짓 양성을
    늘리지 않는 보수적 방향이라 그대로 둔다.
    """
    from statistics import mean, median

    from app.features.territory.dwell import _cells_within
    from app.features.territory.layers import render
    from app.geo.cells import hex_center_latlng

    sheets, spec = _days(5, stop_s=240, radius_u=FINE), _spec(FINE)
    layer = render(sheets, spec)
    centres = {c: hex_center_latlng(*c, FINE) for c in layer.canvas}
    readings = [sum(layer.canvas[c].occupancy
                    for c in _cells_within(centres, centre, READ_M, FINE)) / layer.selected
                for centre in centres.values()]

    got = route_baseline(sheets, spec, READ_M)
    assert got.value == pytest.approx(median(readings))
    assert got.value < mean(readings), "중앙값이 평균보다 작아야 봉우리에 덜 끌린 것이다"


def test_a_stop_stands_out_against_the_route_baseline():
    """**이 파일의 핵심.** 멈춘 자리가 경로의 전형보다 뚜렷하게 진하다."""
    sheets, spec = _days(10, stop_s=120, radius_u=FINE), _spec(FINE)
    base = route_baseline(sheets, spec, READ_M)

    at_stop = contrast(read_at(sheets, spec, STOP_AT, READ_M), base)
    elsewhere = contrast(read_at(sheets, spec, AWAY_AT, READ_M), base)
    assert at_stop > elsewhere * 2, f"멈춘 자리 {at_stop:.1f} 대 경로 위 {elsewhere:.1f}"
    assert at_stop > 2.0


def test_a_walk_with_no_stop_has_no_standout_place():
    """멈춤을 안 심으면 어디도 안 튀어야 한다 — **거짓 양성의 바닥**을 보는 자리다.

    문턱을 상수로 안 고르는 이유가 여기 있다. 몇 배부터 "반복 체류" 인지는 이런 대조
    자료에서 얻을 값이고, 그 측정(M3)은 아직 안 했다.
    """
    sheets, spec = _days(10, stop_s=0, radius_u=FINE), _spec(FINE)
    base = route_baseline(sheets, spec, READ_M)
    for where in (STOP_AT, AWAY_AT):
        assert contrast(read_at(sheets, spec, where, READ_M), base) < 2.0


@pytest.mark.parametrize("radius_u", [COARSE, FINE])
def test_jitter_does_not_erase_the_standout(radius_u):
    """σ=8m 지터를 넣어도 멈춘 자리가 경로의 전형보다 진하게 남는가."""
    sheets = _days(10, stop_s=120, radius_u=radius_u, jitter_m=8.0)
    spec = _spec(radius_u)
    assert contrast(read_at(sheets, spec, STOP_AT, READ_M),
                    route_baseline(sheets, spec, READ_M)) > 2.0


def test_metres_between_is_symmetric_and_zero_at_home():
    assert metres_between(STOP_AT, STOP_AT) == 0.0
    assert metres_between(STOP_AT, AWAY_AT) == pytest.approx(
        metres_between(AWAY_AT, STOP_AT))
    assert metres_between(_at(0.0), _at(100.0)) == pytest.approx(100.0, abs=0.5)
