"""멈춤이 물감이 되는가 — 행동장 구상의 **발밑 검증** (M0).

싸인펜 비유의 원래 문장은 "지나가면 칠해지고 **가만히 있으면 그 자리가 더 진해진다**" 였다.
그런데 지금까지 만든 읽기 장치(`region_visit_rate`)는 "한 번이라도 밟았나" 로 접어서
체류의 연속성을 버렸다. 다음 단계(반복 체류 영역 발견)는 그 버린 축 위에 서므로,
**바닥이 실제로 있는지부터 확인한다.**

## 읽어서 안 것 (아래에서 실제로 잰다)

- `compute_facts` 는 정지 중에도 Segment 를 만든다 — `moving=False` 로 표시만 하고
  버리지 않는다 (`facts.py` 의 `segments.append` 가 이동 판정 **앞**에 있다)
- `paint_sheet` 는 `moving` 을 안 본다. `share = seg.dt / pieces` 라 **시간이 쌓인다**

## 재서 안 것 — 답은 "된다, 그런데 격자가 정한다"

멈춤은 물감이 되고 체류 시간에 **비례**한다. 다만 그 대비가 격자 크기에 크게 좌우된다.

    60 초 멈춤이 경로 중앙값의 몇 배인가
        15 단위 격자(셀 11.9m)    4.3 배
         8 단위 격자(셀  6.3m)   22.7 배

그리고 성긴 격자에서는 **빈도가 체류를 이긴다** — 2 분 머문 한 번(25.8)보다 그냥 지나간
다섯 번(39.0)이 더 진하다. 촘촘한 격자에서는 뒤집힌다(131.6 대 60.2).

**즉 같은 `occupancy` 가 격자에 따라 "체류" 로도 "빈도" 로도 읽힌다.** #69 가 열어 둔
격자 선택에 이제 dwell 쪽 근거가 붙었고, 그 방향은 저장 비용과 반대다.

## 왜 이 파일이 세 축을 같이 보나

`walks`(등장) · `occupancy`(체류) · `peak`(근접)이 **정말 다른 축인지**를 여기서 판정한다.
하나가 나머지를 대신할 수 있으면 축을 셋으로 나눌 이유가 없다.
"""

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from app.features.territory.paint import NARROW_STEP, paint_sheet, stack
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from app.geo.cells import hex_center_latlng

EARTH_R = 6_371_000.0
LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 7, 1, 9, tzinfo=UTC)
SPEED_MPS = 1.2
LEG_M = 120.0

# 페르소나 실험이 쓰는 격자(셀 11.9m)와 그 절반(셀 6.3m). 둘을 같이 재는 것이 이 파일의 결론이다.
COARSE, FINE = 15.0, 8.0


def _at(x_m: float, wobble: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    """원점에서 동쪽으로 `x_m` 미터. `wobble` 은 (동, 북) 미터."""
    east, north = x_m + wobble[0], wobble[1]
    return (LAT + math.degrees(north / EARTH_R),
            LNG + math.degrees(east / (EARTH_R * math.cos(math.radians(LAT)))))


STOP_AT = _at(LEG_M / 2)


def _walk(stop_s: float, radius_u: float, *, jitter_m: float = 0.0, seed: int = 7):
    """동쪽으로 120m 를 1.2m/s 로 걷되, 한가운데서 `stop_s` 초 **서 있는다.**

    서 있는 동안에도 1Hz 로 fix 가 찍힌다 — 실제 수집이 그렇다. 그래서 정지는 "fix 가
    없는 구간" 이 아니라 **같은 자리에 fix 가 쌓이는 구간**이다.
    """
    rng = random.Random(seed)
    fixes: list[WalkFix] = []
    seconds = 0.0

    def push(x_m: float) -> None:
        nonlocal seconds
        wobble = ((rng.gauss(0, jitter_m), rng.gauss(0, jitter_m)) if jitter_m
                  else (0.0, 0.0))
        lat, lng = _at(x_m, wobble)
        fixes.append(WalkFix(client_seq=len(fixes), chain_index=0,
                             at=START + timedelta(seconds=seconds),
                             lat=lat, lng=lng, accuracy_m=5.0, is_mock=False))
        seconds += 1.0

    steps = int((LEG_M / 2) / SPEED_MPS)
    for i in range(steps + 1):
        push(i * SPEED_MPS)
    for _ in range(int(stop_s)):          # 같은 자리에 머문다
        push(LEG_M / 2)
    for i in range(1, steps + 1):
        push(LEG_M / 2 + i * SPEED_MPS)

    computed = compute_facts("w", "d", START, fixes[-1].at + timedelta(seconds=1), fixes)
    return computed, paint_sheet("w", START, computed.segments, radius_u, NARROW_STEP)


def _metres_from_stop(cell, radius_u: float) -> float:
    lat, lng = hex_center_latlng(*cell, radius_u)
    return math.hypot(
        math.radians(lng - STOP_AT[1]) * EARTH_R * math.cos(math.radians(LAT)),
        math.radians(lat - STOP_AT[0]) * EARTH_R)


def _at_stop(field: dict, radius_u: float, within_m: float = 20.0):
    """멈춘 자리 둘레에서 가장 진한 칸.

    **어느 칸인지 미리 정하지 않는다.** 처음엔 `hex_cell(멈춘 점)` 을 썼다가 헛짚었다 —
    그 칸의 **중심**이 멈춘 점에서 8.2m 떨어져 있어서 붓의 바깥 밴드(0.15)만 받았다.
    점을 담은 칸과 중심이 가장 가까운 칸은 다르다.
    """
    near = [c for c in field if _metres_from_stop(c, radius_u) <= within_m]
    assert near, "멈춘 자리 둘레에 칠해진 칸이 없다"
    return max(near, key=lambda c: field[c])


def _median(values) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


# ---- 1. 멈춤이 물감이 된다 --------------------------------------------------------------


def test_standing_still_still_makes_segments():
    """정지 구간이 Segment 로 남아야 칠할 것이 있다. `moving=False` 는 표시지 삭제가 아니다."""
    computed, _ = _walk(stop_s=60, radius_u=COARSE)
    still = [s for s in computed.segments if not s.moving]
    assert still, "정지 Segment 가 하나도 없다 — 어딘가에서 버리고 있다"
    assert sum(s.dt for s in still) >= 55, "정지 시간이 Segment 로 안 남았다"


@pytest.mark.parametrize("radius_u", [COARSE, FINE])
def test_a_stop_paints_more_than_walking_through(radius_u):
    """**이 파일의 핵심.** 같은 자리를 지나가기만 한 것보다 서 있었던 쪽이 진하다."""
    _, passing = _walk(stop_s=0, radius_u=radius_u)
    _, standing = _walk(stop_s=120, radius_u=radius_u)
    cell = _at_stop(standing.occupancy, radius_u)
    assert standing.occupancy[cell] > passing.occupancy.get(cell, 0.0) * 2, (
        f"멈춤이 물감을 안 쌓는다 (격자 {radius_u}): "
        f"통과 {passing.occupancy.get(cell, 0.0):.1f} 대 정지 {standing.occupancy[cell]:.1f}")


@pytest.mark.parametrize("radius_u", [COARSE, FINE])
def test_paint_grows_in_step_with_dwell_time(radius_u):
    """체류가 길수록 진하고, **비례한다.** 포화되면 긴 체류를 못 구별한다."""
    marks = []
    for stop_s in (0, 30, 60, 120):
        _, sheet = _walk(stop_s=stop_s, radius_u=radius_u)
        marks.append(sheet.occupancy[_at_stop(sheet.occupancy, radius_u)])
    assert marks == sorted(marks), f"체류가 길어지는데 물감이 안 는다: {marks}"
    first, second = marks[2] - marks[1], marks[3] - marks[2]   # 30→60, 60→120
    assert second > first, f"두 배 오래 있었는데 덜 늘었다: {marks}"


def test_the_extra_paint_lands_where_the_dog_stopped():
    """멈춤의 물감이 **그 자리에** 쌓여야 한다. 경로 전체로 번지면 위치 정보가 없다."""
    _, passing = _walk(stop_s=0, radius_u=FINE)
    _, standing = _walk(stop_s=240, radius_u=FINE)
    gained = {cell: standing.occupancy[cell] - passing.occupancy.get(cell, 0.0)
              for cell in standing.occupancy}
    grown = {c: v for c, v in gained.items() if v > 0}
    assert _metres_from_stop(max(grown, key=grown.get), FINE) <= 12.0

    near = sum(v for c, v in grown.items() if _metres_from_stop(c, FINE) <= 25.0)
    assert near / sum(grown.values()) > 0.9, "멈춤 물감이 25m 밖으로 번졌다"


# ---- 2. 지터가 집중을 뭉개나 ------------------------------------------------------------


@pytest.mark.parametrize("radius_u", [COARSE, FINE])
def test_jitter_blurs_the_stop_but_does_not_erase_it(radius_u):
    """σ=8m 지터를 넣어도 멈춘 자리가 경로보다 진하게 남는가.

    이게 무너지면 **한 산책의 멈춤은 못 읽는다** 는 뜻이고, 그러면 여러 장 겹치기가
    선택이 아니라 필수가 된다. 어느 쪽이든 다음 단계가 알아야 하는 사실이다.
    """
    _, sheet = _walk(stop_s=120, radius_u=radius_u, jitter_m=8.0)
    peak_near = sheet.occupancy[_at_stop(sheet.occupancy, radius_u)]
    passing = _median([v for c, v in sheet.occupancy.items()
                       if _metres_from_stop(c, radius_u) > 40.0])
    assert peak_near > passing * 2, (
        f"지터가 멈춤을 뭉갰다 (격자 {radius_u}): "
        f"근처 {peak_near:.1f} 대 경로 중앙 {passing:.1f}")


# ---- 3. 세 축이 정말 다른가 -------------------------------------------------------------


def test_peak_cannot_tell_a_stop_from_a_pass():
    """**축을 셋으로 나눈 이유.** `peak` 은 "얼마나 가까이" 라 체류를 구별 못 한다.

    지나가든 서 있든 그 칸에 가장 가까웠던 거리는 같으므로 `peak` 도 같다. 체류를 읽으려면
    `occupancy` 가 따로 있어야 하고, 하나로 접으면 안 된다 (dwell 문서 §11 이 적어 둔 것).
    """
    _, passing = _walk(stop_s=0, radius_u=FINE)
    _, standing = _walk(stop_s=120, radius_u=FINE)
    cell = _at_stop(standing.occupancy, FINE)
    assert passing.peak[cell] == standing.peak[cell], (
        "peak 이 체류에 반응한다 — 그러면 이 축의 뜻이 흐려진 것이다")
    assert standing.occupancy[cell] > passing.occupancy[cell]


# ---- 4. 격자가 "체류" 와 "빈도" 중 무엇으로 읽힐지를 정한다 ------------------------------


def test_dwell_contrast_depends_on_the_grid():
    """같은 60 초 멈춤이 격자에 따라 4 배로도 20 배로도 읽힌다.

    2026-08-27 실측 — 경로 중앙값 대비:

        15 단위(셀 11.9m)   4.3 배
         8 단위(셀  6.3m)  22.7 배

    성긴 격자에서 흐려지는 이유는 단순하다. 멈춘 점과 셀 중심 사이가 멀수록 붓의 바깥
    밴드만 받는데, 셀이 크면 그 거리가 커진다. **체류를 읽고 싶으면 격자가 붓 심 가까이
    가야 한다.**
    """
    contrast = {}
    for radius_u in (COARSE, FINE):
        _, sheet = _walk(stop_s=60, radius_u=radius_u)
        peak_near = sheet.occupancy[_at_stop(sheet.occupancy, radius_u)]
        route = _median([v for c, v in sheet.occupancy.items()
                         if _metres_from_stop(c, radius_u) > 40.0])
        contrast[radius_u] = peak_near / route

    assert contrast[FINE] > contrast[COARSE] * 3, (
        f"격자가 dwell 대비를 안 바꾼다: {contrast}")
    assert contrast[COARSE] > 2.0, "성긴 격자에서도 멈춤은 보여야 한다"


def test_on_a_coarse_grid_frequency_out_paints_dwell():
    """**성긴 격자에서는 빈도가 체류를 이긴다** — 그러면 `occupancy` 는 dwell 축이 아니다.

    2 분 머문 한 번 대 그냥 지나간 다섯 번:

        15 단위   25.8  대  39.0   → 통과가 이긴다
         8 단위  131.6  대  60.2   → 체류가 이긴다

    같은 값이 격자에 따라 다른 뜻이 된다. 반복 체류 영역을 찾으려면 이걸 먼저 정해야 하고,
    #69 가 열어 둔 격자 선택에 **dwell 쪽 근거**가 붙는 지점이다 — 방향은 저장 비용과 반대다.
    """
    verdicts = {}
    for radius_u in (COARSE, FINE):
        lingered = stack([_walk(stop_s=120, radius_u=radius_u)[1]])
        passed = stack([_walk(stop_s=0, radius_u=radius_u, seed=i)[1] for i in range(5)])
        long_cell = _at_stop({c: p.occupancy for c, p in lingered.items()}, radius_u)
        quick_cell = _at_stop({c: p.occupancy for c, p in passed.items()}, radius_u)
        assert lingered[long_cell].walks == 1 and passed[quick_cell].walks == 5
        verdicts[radius_u] = lingered[long_cell].occupancy > passed[quick_cell].occupancy

    assert verdicts[COARSE] is False, "성긴 격자에서 체류가 이겼다 — 측정이 바뀌었다"
    assert verdicts[FINE] is True, "촘촘한 격자에서도 체류가 졌다 — dwell field 가 안 선다"
