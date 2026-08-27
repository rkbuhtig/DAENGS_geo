"""체류를 읽는 장치 — **국소 적분이고, 산책 수로 나눈다.**

갈래는 [repeated-dwell-area](../../../docs/explorations/walk/repeated-dwell-area.md).
파이프라인의 Instruments 단이고, 여기서 근거를 만들지도 고르지도 않는다.

## 왜 셀 하나로 안 읽나

[질량 보존 측정](../../../docs/research/2026-08-27-mass-conserving-kernel.md)이 잘랐다.
같은 체류를 촘촘한 격자는 잘게 나눠 담으므로 **셀 하나의 값은 격자에 따라 달라진다**
(같은 120 초가 12.8 / 49.8 / 51.5).

    셀은 계산 격자고, 뜻은 field 에 있다.

"어느 hex 셀이 진한가" 를 제품 개념으로 삼으면 원래 구상(연속 행동장)에서 벗어난다.

## 그래도 **절대값은 아직 격자에 흔들린다** — 그래서 대비로 읽는다

적분하면 셀 배치의 우연은 사라지지만 격자 밀도는 안 사라진다. 지금 칠하기 kernel 에
정규화가 없어서다 — 같은 120 초 체류가 15 단위에서 산책당 77.4, 8 단위에서 420.1 로 읽힌다.
질량 보존 측정이 그 결함을 쟀지만 **코드는 아직 안 고쳤다**(새 세대라 별도 결정이다).

그래서 이 층이 내는 판단 재료는 절대값이 아니라 **경로 기준선 대비 몇 배냐**(`contrast`)다.
비율에서는 격자 밀도 인자가 분자·분모에서 상쇄된다 — 같은 체류가 3.15 대 4.42 로,
절대값의 5.4 배 차이가 1.4 배로 줄어든다.

    per_walk    절대 체류량. 격자가 바뀌면 못 견준다
    contrast    경로 전형 대비 배수. 격자가 달라도 대체로 견줄 수 있다

kernel 이 질량 보존으로 바뀌면 절대값도 견줄 수 있게 된다 — 그때 이 문단을 지운다.

## 왜 산책 수로 나누나

같은 측정이 이것도 잘랐다. **총량으로 견주면 빈도가 체류로 위장한다** — 5 회 그냥 지나가면
2 분 머문 한 번보다 총량이 크다(5×33 = 165 대 120+33 = 153). 당연하다, 5 회분 시간이니까.

산책당으로 나누면 어느 격자에서나 체류가 5 배 안팎으로 이긴다. `rate_field` 가
`walks / selected` 로 하던 규율이 dwell 축에도 그대로 필요하다.

## 읽기 반경은 셀 중심 간격보다 커야 한다

15 단위(간격 20.6m)에서 10m 로 읽으면 판정이 흔들리고 20m 는 안정된다. 격자가 못 담는
해상도로 물으면 답이 격자 배치에 좌우된다.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median

from app.features.territory.layers import LayerSpec, render, select
from app.features.territory.paint import Cellophane
from app.geo.cells import Cell, cell_size_m, hex_center_latlng

EARTH_R = 6_371_000.0

# 읽기 반경이 셀 중심 간격의 몇 배는 돼야 하나. 육각 격자의 중심 간격은 `반지름 × √3` 이다.
MIN_RADIUS_IN_SPACINGS = 1.0


@dataclass(frozen=True)
class DwellReading:
    """어떤 자리 둘레의 체류 읽기. **분자·분모를 늘 달고 다닌다.**

    `VisitRate` 와 같은 규율이다 — 비율만 들고 다니면 `2/3` 인지 `200/300` 인지 모른다.
    """

    centre: tuple[float, float]      # lat, lng
    radius_m: float
    mass: float                      # 이 반경 안에 쌓인 물감 총량
    walks: int                       # 이 반경을 밟은 산책 수 (support)
    selected: int                    # 조건에 걸린 산책 수 (분모)
    total: int                       # 조건을 걸기 전 전체 장 수

    @property
    def per_walk(self) -> float | None:
        """**dwell 축의 값.** 조건에 걸린 산책이 없으면 0 이 아니라 계산 불가다."""
        return self.mass / self.selected if self.selected else None

    @property
    def visit_rate(self) -> float | None:
        """**presence 축의 값.** 같은 자리를 두 축으로 읽는다 — 서로 대신 못 한다."""
        return self.walks / self.selected if self.selected else None


def metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """등장방형 근사. 동네 규모에서 오차는 cm 급이다."""
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot(math.radians(b[1] - a[1]) * EARTH_R * math.cos(lat),
                      math.radians(b[0] - a[0]) * EARTH_R)


def cell_spacing_m(radius_u: float, lat: float) -> float:
    """육각 격자의 중심 간 거리. 읽기 반경의 하한을 정하는 값이다."""
    return cell_size_m(radius_u, lat) * math.sqrt(3)


def _cells_within(cells: Iterable[Cell], centre: tuple[float, float],
                  radius_m: float, radius_u: float) -> set[Cell]:
    return {c for c in cells
            if metres_between(hex_center_latlng(*c, radius_u), centre) <= radius_m}


def read_at(sheets: Iterable[Cellophane], spec: LayerSpec,
            centre: tuple[float, float], radius_m: float) -> DwellReading:
    """자리 하나를 읽는다 — 둘레 `radius_m` 안의 체류 질량과 그것을 만든 산책 수.

    **장을 하나씩 본다.** 겹친 canvas 만으로는 support 를 정확히 못 센다 — 칸별 `walks` 를
    더하면 같은 산책을 여러 번 세고, 최댓값을 쓰면 반경 안을 스친 산책을 빠뜨린다.
    `region_visit_rate` 가 장을 하나씩 보는 것과 같은 이유다.
    """
    pool = list(sheets)
    chosen = select(pool, spec)
    radius_u = spec.projection.radius_u
    min_peak = spec.aggregation.min_peak

    mass, touched = 0.0, 0
    for sheet in chosen:
        near = _cells_within(sheet.occupancy, centre, radius_m, radius_u)
        share = sum(sheet.occupancy[c] for c in near
                    if sheet.peak.get(c, 0.0) >= min_peak)
        if share > 0:
            mass += share
            touched += 1
    return DwellReading(centre=centre, radius_m=radius_m, mass=mass,
                        walks=touched, selected=len(chosen), total=len(pool))


def route_baseline(sheets: Iterable[Cellophane], spec: LayerSpec,
                   radius_m: float) -> float | None:
    """경로 전체의 **전형적인** 산책당 체류. 우세를 재는 기준선이다.

    칠해진 칸마다 둘레를 적분하고 그 **중앙값**을 쓴다. 평균이 아닌 이유는 체류 봉우리
    자체가 평균을 끌어올려서, 봉우리를 봉우리와 견주게 되기 때문이다.

    **중앙값도 완전히 면역은 아니다.** 체류가 산책 시간의 큰 몫을 차지하면 봉우리 둘레
    칸이 칠해진 칸의 상당수가 되어 중앙값도 따라 오른다. 짧은 산책에 긴 정지 하나를 심으면
    기준선이 두 배가 된다 — 그때는 대비가 실제보다 작게 나온다(보수적인 방향이라 거짓
    양성을 늘리지는 않는다).

    겹친 canvas 로 계산한다 — 여기서는 support 가 아니라 질량만 필요하고, 칸마다 장을
    다시 훑으면 O(칸 × 장 × 칸) 이라 못 쓴다.
    """
    layer = render(sheets, spec)
    if not layer.selected or not layer.canvas:
        return None
    radius_u = spec.projection.radius_u
    centres = {c: hex_center_latlng(*c, radius_u) for c in layer.canvas}
    readings = []
    for centre in centres.values():
        near = _cells_within(centres, centre, radius_m, radius_u)
        readings.append(sum(layer.canvas[c].occupancy for c in near) / layer.selected)
    return median(readings)


def contrast(reading: DwellReading, baseline: float | None) -> float | None:
    """이 자리가 경로의 전형보다 몇 배 진한가. **문턱은 여기서 안 정한다.**

    몇 배부터 "반복 체류 영역" 인지는 상수로 고를 값이 아니라 **대조군에서 얻을 값**이다 —
    체류를 하나도 안 심은 자료에서 이 지표가 얼마나 나오는지가 거짓 양성의 바닥이고,
    문턱은 그 바닥 위로 정해진다 (회수 실험이 ε 를 A 페르소나에서 얻은 것과 같은 방법).

    그 대조군 측정은 아직 안 했다. 그래서 여기는 값만 낸다.
    """
    per_walk = reading.per_walk
    if per_walk is None or not baseline:
        return None
    return per_walk / baseline


def radius_floor(spec: LayerSpec, lat: float) -> float:
    """이 격자에서 물어도 되는 최소 읽기 반경. 아래로 물으면 답이 격자 배치에 좌우된다."""
    return cell_spacing_m(spec.projection.radius_u, lat) * MIN_RADIUS_IN_SPACINGS
