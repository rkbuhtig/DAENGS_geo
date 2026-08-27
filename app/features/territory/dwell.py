"""체류를 읽는 장치 — **국소 적분이고, 산책 수로 나눈다.**

갈래는 [repeated-dwell-area](../../../docs/explorations/walk/repeated-dwell-area.md).
파이프라인의 Instruments 단이고, 여기서 근거를 만들지도 고르지도 않는다.

## 왜 셀 하나로 안 읽나

[질량 보존 측정](../../../docs/research/2026-08-27-mass-conserving-kernel.md)이 잘랐다.
같은 체류를 촘촘한 격자는 잘게 나눠 담으므로 **셀 하나의 값은 격자에 따라 달라진다**
(같은 120 초가 12.8 / 49.8 / 51.5).

    셀은 계산 격자고, 뜻은 field 에 있다.

"어느 hex 셀이 진한가" 를 제품 개념으로 삼으면 원래 구상(연속 행동장)에서 벗어난다.

## 값이 셋인 이유 — 하나는 나머지 둘의 곱이다

처음엔 `mass / selected` 를 "dwell 축", `walks / selected` 를 "presence 축" 이라 부르고
**둘을 분리했다**고 적었다. **틀렸다.** 수식을 펴면 앞이 뒤를 이미 품고 있다.

    mass / selected  =  (walks / selected) × (mass / walks)
                     =    등장률          ×   갔을 때 체류

100 회 중 100 회 가서 매번 10 초 머문 자리와, 10 회만 가서 갈 때마다 100 초 머문 자리가
`mass / selected` 로는 **똑같이 10** 이다. 아주 다른 이야기인데.

그래서 셋을 다 낸다. 어느 것으로 판정할지는 **정의가 명시적으로 고른다.**

    visit_rate               walks / selected     얼마나 자주 등장했나
    dwell_per_visit          mass / walks         갔을 때 얼마나 머무나
    expected_dwell_per_walk  mass / selected      산책 하나당 기대 체류 (= 앞 둘의 곱)

## 대비로 읽는다 — 다만 세대를 넘어 견주지 않는다

정규화 없는 지금 kernel 에서는 적분해도 격자 밀도가 안 사라진다 — 같은 체류가 15 단위
산책당 77.4, 8 단위 420.1 이다. 비율에서는 그 인자가 크게 줄어든다(3.15 대 4.42).

**"격자가 달라도 견줄 수 있다" 고까지 말하지 않는다.** 40% 차이는 계약으로 쓰기엔 크고,
[#69] 세대 정책상 다른 격자·붓의 장은 애초에 안 섞는다. 대비의 쓸모는 **같은 세대 안에서
국소 봉우리를 경로 전형과 견주는 정규화**까지다.

## 측정 문맥을 잃지 않는다

읽기와 기준선이 **같은 조건·같은 반경·같은 세대**에서 나왔는지 `contrast` 가 검사한다.
값만 남고 "어떻게 잰 값인가" 가 사라지면 [evidence-layer] 원칙 2 를 이 층에서 어기는 것이다.
`#69` 가 `profile_fp` 를 그렇게 보존해 놓고 여기서 `float` 하나로 날릴 수는 없다.

## 읽기 반경은 셀 중심 간격보다 커야 한다 — 거절한다

15 단위(간격 20.6m)에서 10m 로 읽으면 판정이 흔들리고 20m 는 안정된다. 격자가 못 담는
해상도로 물으면 답이 격자 배치에 좌우되므로, **그런 질문은 값을 주지 않고 거절한다.**
정의가 조건으로 걸어 놓고 코드가 안 막으면 정의가 장식이 된다.

[evidence-layer]: ../../../docs/explorations/walk/evidence-layer.md
[#69]: ../../../docs/decisions/2026-08-26-walk-permanent-spatial-form.md
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
    """어떤 자리 둘레의 체류 읽기. **분자·분모와 측정 문맥을 늘 달고 다닌다.**

    `VisitRate` 와 같은 규율이다 — 비율만 들고 다니면 `2/3` 인지 `200/300` 인지 모른다.
    """

    centre: tuple[float, float]      # lat, lng
    radius_m: float
    mass: float                      # 이 반경 안에 쌓인 물감 총량
    walks: int                       # 이 반경을 밟은 산책 수 (support)
    selected: int                    # 조건에 걸린 산책 수 (분모)
    total: int                       # 조건을 걸기 전 전체 장 수
    spec_fingerprint: str            # 어느 조건·집계·세대에서 잰 값인가

    @property
    def visit_rate(self) -> float | None:
        """**등장.** 조건에 걸린 산책 중 몇 번이 이 반경을 밟았나."""
        return self.walks / self.selected if self.selected else None

    @property
    def dwell_per_visit(self) -> float | None:
        """**갔을 때 체류.** 등장을 뺀 순수 체류량 — 안 간 산책은 분모에 없다."""
        return self.mass / self.walks if self.walks else None

    @property
    def expected_dwell_per_walk(self) -> float | None:
        """**산책 하나당 기대 체류.** `visit_rate × dwell_per_visit` 이다.

        둘의 곱이라 "순수 dwell 축" 이 아니다. 공간 중요도로는 쓸모 있지만, 등장과 체류를
        가르고 싶으면 위 두 값을 따로 봐야 한다.
        """
        return self.mass / self.selected if self.selected else None


@dataclass(frozen=True)
class DwellBaseline:
    """경로 전형값. **자기 측정 문맥을 달고 다닌다** — 아무 값이나 대비의 분모가 되면 안 된다."""

    value: float
    radius_m: float
    selected: int
    total: int
    spec_fingerprint: str


def metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """등장방형 근사. 동네 규모에서 오차는 cm 급이다."""
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot(math.radians(b[1] - a[1]) * EARTH_R * math.cos(lat),
                      math.radians(b[0] - a[0]) * EARTH_R)


def cell_spacing_m(radius_u: float, lat: float) -> float:
    """육각 격자의 중심 간 거리. 읽기 반경의 하한을 정하는 값이다."""
    return cell_size_m(radius_u, lat) * math.sqrt(3)


def radius_floor(spec: LayerSpec, lat: float) -> float:
    """이 격자에서 물어도 되는 최소 읽기 반경. 아래로 물으면 답이 격자 배치에 좌우된다."""
    return cell_spacing_m(spec.projection.radius_u, lat) * MIN_RADIUS_IN_SPACINGS


def _check_radius(spec: LayerSpec, lat: float, radius_m: float) -> None:
    floor = radius_floor(spec, lat)
    if radius_m < floor:
        raise ValueError(
            f"읽기 반경 {radius_m:.1f}m 는 격자가 못 담는다 — "
            f"{spec.projection.radius_u:.0f} 단위의 셀 중심 간격은 {floor:.1f}m 다. "
            f"이보다 좁게 물으면 답이 격자 배치에 좌우된다")


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
    _check_radius(spec, centre[0], radius_m)
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
                        walks=touched, selected=len(chosen), total=len(pool),
                        spec_fingerprint=spec.fingerprint())


def route_baseline(sheets: Iterable[Cellophane], spec: LayerSpec,
                   radius_m: float) -> DwellBaseline | None:
    """경로 전체의 **전형적인** 산책당 기대 체류. 우세를 재는 기준선이다.

    칠해진 칸마다 둘레를 적분하고 그 **중앙값**을 쓴다. 평균이 아닌 이유는 체류 봉우리
    자체가 평균을 끌어올려서, 봉우리를 봉우리와 견주게 되기 때문이다.

    **중앙값도 완전히 면역은 아니다.** 체류가 산책 시간의 큰 몫을 차지하면 봉우리 둘레
    칸이 칠해진 칸의 상당수가 되어 중앙값도 따라 오른다. 짧은 산책에 긴 정지 하나를 심으면
    기준선이 두 배가 된다 — 그때는 대비가 실제보다 작게 나오고, 보수적인 방향이라 거짓
    양성을 늘리지는 않는다.

    **`expected_dwell_per_walk` 기준이다.** 겹친 canvas 로 계산해서 support 를 모르기
    때문이다 — 칸마다 장을 다시 훑으면 O(칸 × 장 × 칸) 이라 못 쓴다. 그래서 이 기준선과
    견줄 수 있는 것은 읽기의 `expected_dwell_per_walk` 뿐이고, `contrast` 가 그것을 쓴다.
    """
    pool = list(sheets)
    layer = render(pool, spec)
    if not layer.selected or not layer.canvas:
        return None
    radius_u = spec.projection.radius_u
    centres = {c: hex_center_latlng(*c, radius_u) for c in layer.canvas}
    _check_radius(spec, next(iter(centres.values()))[0], radius_m)
    readings = [
        sum(layer.canvas[c].occupancy
            for c in _cells_within(centres, centre, radius_m, radius_u)) / layer.selected
        for centre in centres.values()
    ]
    return DwellBaseline(value=median(readings), radius_m=radius_m,
                         selected=layer.selected, total=layer.total,
                         spec_fingerprint=spec.fingerprint())


def contrast(reading: DwellReading, baseline: DwellBaseline | None) -> float | None:
    """이 자리가 경로의 전형보다 몇 배 진한가. **문턱은 여기서 안 정한다.**

    몇 배부터 "반복 체류 영역" 인지는 상수로 고를 값이 아니라 **대조군에서 얻을 값**이다 —
    체류를 하나도 안 심은 자료에서 이 지표가 얼마나 나오는지가 거짓 양성의 바닥이고,
    문턱은 그 바닥 위로 정해진다 (회수 실험이 ε 를 A 페르소나에서 얻은 것과 같은 방법).
    그 대조군 측정은 아직 안 했다.

    **문맥이 다른 둘을 견주면 거절한다.** 조건·집계·세대가 다르거나 반경이 다르면 그 비는
    아무 뜻이 없다 — 여름 지도의 봉우리를 겨울 기준선으로 나누는 것을 코드가 막는다.
    """
    if baseline is None:
        return None
    if reading.spec_fingerprint != baseline.spec_fingerprint:
        raise ValueError(
            "읽기와 기준선의 spec 이 다르다 — 조건·집계·격자·붓 중 하나가 어긋났다. "
            f"{reading.spec_fingerprint} 대 {baseline.spec_fingerprint}")
    if reading.radius_m != baseline.radius_m:
        raise ValueError(
            f"읽기 반경 {reading.radius_m:.1f}m 와 기준선 반경 "
            f"{baseline.radius_m:.1f}m 가 다르다 — 다른 창으로 잰 값끼리 못 나눈다")

    expected = reading.expected_dwell_per_walk
    if expected is None or not baseline.value:
        return None
    return expected / baseline.value
