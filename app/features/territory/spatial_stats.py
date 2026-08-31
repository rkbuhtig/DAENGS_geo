"""산책별 셀로판 z축을 질문에 따라 축약하는 공간 통계층.

`paint.py` 는 산책 한 번을 `Cellophane` 한 장으로 만든다. 이 모듈은 장을 미리 접어 저장하지
않고, `LayerSpec` 이 고른 같은 계산 세대의 장을 조회 시점에 읽는다.

    total_time          선택된 산책의 관측 시간 질량 합
    visit_rate          선택된 산책 중 셀에 나타난 산책 비율
    conditional_dwell   나타난 산책당 평균 관측 시간 질량
    time_utilization    전체 관측 시간에서 셀이 차지하는 비중
    walk_utilization    산책마다 합 1로 만든 뒤 동등 가중한 비중

같은 값 dict 하나만 반환하지 않는다. 분자·분모·표본 수·Paint 세대를 같이 들고 가야
`5/7`과 `17/24`, 총 시간과 방문률, 긴 산책 가중과 산책 동등 가중을 화면이 혼동하지 않는다.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from app.features.territory.layers import LayerSpec, select
from app.features.territory.paint import Cellophane
from app.geo.cells import Cell

type SpatialMetric = Literal[
    "total_time",
    "visit_rate",
    "conditional_dwell",
    "time_utilization",
    "walk_utilization",
]
type FieldDenominator = float | dict[Cell, float] | None

SPATIAL_METRICS: frozenset[str] = frozenset(
    {
        "total_time",
        "visit_rate",
        "conditional_dwell",
        "time_utilization",
        "walk_utilization",
    }
)


@dataclass(frozen=True)
class SpatialField:
    """셀별 통계값과 그 값을 재현·설명하는 계산 영수증.

    `numerators`와 `denominator`는 metric에 따라 단위가 다르다.

    - `total_time`: 분자는 초, 분모 없음
    - `visit_rate`: 분자는 산책 수, 공통 분모는 선택된 산책 수
    - `conditional_dwell`: 분자는 초, 셀별 분모는 나타난 산책 수
    - `time_utilization`: 분자는 초, 공통 분모는 전체 시간 질량
    - `walk_utilization`: 분자는 산책별 정규화 비중의 합, 공통 분모는 기여 산책 수

    `selected`는 selector와 Paint 세대에 걸린 모든 장 수다. `contributing`은 metric의 분모에
    실제로 들어간 장 수다. 빈 장은 visit rate에서는 미방문 표본이지만 walk utilization에서는
    합 1로 정규화할 수 없어 기여 표본에서 빠진다.
    """

    spec: LayerSpec
    metric: SpatialMetric
    values: dict[Cell, float]
    numerators: dict[Cell, float]
    denominator: FieldDenominator
    selected: int
    total: int
    contributing: int
    paint_fp: str
    min_peak: float
    unit: str
    normalization: str

    def __post_init__(self) -> None:
        if self.metric not in SPATIAL_METRICS:
            raise ValueError(f"지원하지 않는 공간 통계 metric: {self.metric}")
        if self.selected < 0 or self.total < 0 or self.contributing < 0:
            raise ValueError("표본 수는 0 이상이어야 한다")
        if self.selected > self.total or self.contributing > self.selected:
            raise ValueError("기여 표본 수 <= 선택 표본 수 <= 전체 표본 수여야 한다")
        if self.paint_fp != self.spec.projection.paint_fp:
            raise ValueError("통계 결과의 paint_fp가 spec과 다르다")
        if not math.isfinite(self.min_peak) or not 0 <= self.min_peak <= 1:
            raise ValueError("min_peak는 0 이상 1 이하의 유한한 값이어야 한다")
        if set(self.values) != set(self.numerators):
            raise ValueError("values와 numerators의 셀 집합이 다르다")
        if any(not math.isfinite(value) or value < 0 for value in self.values.values()):
            raise ValueError("공간 통계값은 유한한 0 이상이어야 한다")
        if any(not math.isfinite(value) or value < 0 for value in self.numerators.values()):
            raise ValueError("공간 통계 분자는 유한한 0 이상이어야 한다")
        if isinstance(self.denominator, dict):
            if set(self.denominator) != set(self.values):
                raise ValueError("셀별 denominator와 values의 셀 집합이 다르다")
            if any(not math.isfinite(value) or value <= 0 for value in self.denominator.values()):
                raise ValueError("셀별 denominator는 유한한 양수여야 한다")
        elif self.denominator is not None:
            if not math.isfinite(self.denominator) or self.denominator < 0:
                raise ValueError("공통 denominator는 유한한 0 이상이어야 한다")


def _require_metric(spec: LayerSpec, expected: SpatialMetric) -> None:
    actual = spec.aggregation.metric
    if actual != expected:
        raise ValueError(f"{expected} 계산에 metric={actual!r} spec을 사용할 수 없다")
    threshold = spec.aggregation.min_peak
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("min_peak는 0 이상 1 이하의 유한한 값이어야 한다")


def _selection(
    sheets: Iterable[Cellophane], spec: LayerSpec
) -> tuple[list[Cellophane], list[Cellophane]]:
    pool = list(sheets)
    return pool, select(pool, spec)


def _cells(sheets: Iterable[Cellophane]) -> list[Cell]:
    return sorted({cell for sheet in sheets for cell in sheet.occupancy})


def _qualified(sheet: Cellophane, cell: Cell, min_peak: float) -> bool:
    # `min_peak=0`이어도 이 장에 아예 없는 셀은 방문이 아니다. `0 >= 0`만 검사하면 빈 장과
    # 다른 경로의 장까지 방문 분모에 들어가 모든 칠해진 셀의 방문률이 100%가 된다.
    return cell in sheet.occupancy and sheet.peak.get(cell, 0.0) >= min_peak


def _field(
    *,
    spec: LayerSpec,
    metric: SpatialMetric,
    values: dict[Cell, float],
    numerators: dict[Cell, float],
    denominator: FieldDenominator,
    selected: int,
    total: int,
    contributing: int,
    min_peak: float,
    unit: str,
    normalization: str,
) -> SpatialField:
    return SpatialField(
        spec=spec,
        metric=metric,
        values=values,
        numerators=numerators,
        denominator=denominator,
        selected=selected,
        total=total,
        contributing=contributing,
        paint_fp=spec.projection.paint_fp,
        min_peak=min_peak,
        unit=unit,
        normalization=normalization,
    )


def total_time_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """셀마다 `min_peak` 조건을 만족한 장의 관측 시간 질량 합."""
    _require_metric(spec, "total_time")
    pool, chosen = _selection(sheets, spec)
    threshold = spec.aggregation.min_peak
    numerators = {
        cell: math.fsum(
            sheet.occupancy.get(cell, 0.0) for sheet in chosen if _qualified(sheet, cell, threshold)
        )
        for cell in _cells(chosen)
    }
    numerators = {cell: value for cell, value in numerators.items() if value > 0}
    return _field(
        spec=spec,
        metric="total_time",
        values=dict(numerators),
        numerators=numerators,
        denominator=None,
        selected=len(chosen),
        total=len(pool),
        contributing=sum(
            1
            for sheet in chosen
            if any(
                amount > 0 and _qualified(sheet, cell, threshold)
                for cell, amount in sheet.occupancy.items()
            )
        ),
        min_peak=threshold,
        unit="s",
        normalization="none",
    )


def visit_rate_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """셀마다 선택된 산책 중 `peak >= min_peak`인 산책 비율."""
    _require_metric(spec, "visit_rate")
    pool, chosen = _selection(sheets, spec)
    threshold = spec.aggregation.min_peak
    counts = {
        cell: float(sum(_qualified(sheet, cell, threshold) for sheet in chosen))
        for cell in _cells(chosen)
    }
    counts = {cell: count for cell, count in counts.items() if count > 0}
    denominator = float(len(chosen))
    values = {cell: count / denominator for cell, count in counts.items()} if denominator else {}
    return _field(
        spec=spec,
        metric="visit_rate",
        values=values,
        numerators=counts,
        denominator=denominator,
        selected=len(chosen),
        total=len(pool),
        contributing=len(chosen),
        min_peak=threshold,
        unit="ratio",
        normalization="selected_walks",
    )


def conditional_dwell_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """셀마다 나타난 산책에 한정한 평균 관측 시간 질량."""
    _require_metric(spec, "conditional_dwell")
    pool, chosen = _selection(sheets, spec)
    threshold = spec.aggregation.min_peak
    numerators: dict[Cell, float] = {}
    denominators: dict[Cell, float] = {}
    for cell in _cells(chosen):
        qualified = [sheet for sheet in chosen if _qualified(sheet, cell, threshold)]
        if not qualified:
            continue
        amount = math.fsum(sheet.occupancy.get(cell, 0.0) for sheet in qualified)
        if amount <= 0:
            continue
        numerators[cell] = amount
        denominators[cell] = float(len(qualified))
    values = {cell: numerators[cell] / denominators[cell] for cell in numerators}
    return _field(
        spec=spec,
        metric="conditional_dwell",
        values=values,
        numerators=numerators,
        denominator=denominators,
        selected=len(chosen),
        total=len(pool),
        contributing=sum(
            1
            for sheet in chosen
            if any(
                amount > 0 and _qualified(sheet, cell, threshold)
                for cell, amount in sheet.occupancy.items()
            )
        ),
        min_peak=threshold,
        unit="s/visited_walk",
        normalization="visited_walks_per_cell",
    )


def time_utilization_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """전체 선택 산책의 raw 관측 시간 질량에서 각 셀이 차지하는 비중."""
    _require_metric(spec, "time_utilization")
    if spec.aggregation.min_peak != 0:
        raise ValueError("time_utilization은 질량을 자르지 않는 min_peak=0만 지원한다")
    pool, chosen = _selection(sheets, spec)
    sheet_masses = [math.fsum(sheet.occupancy.values()) for sheet in chosen]
    numerators = {
        cell: math.fsum(sheet.occupancy.get(cell, 0.0) for sheet in chosen)
        for cell in _cells(chosen)
    }
    numerators = {cell: value for cell, value in numerators.items() if value > 0}
    denominator = math.fsum(numerators.values())
    values = (
        {cell: value / denominator for cell, value in numerators.items()} if denominator else {}
    )
    return _field(
        spec=spec,
        metric="time_utilization",
        values=values,
        numerators=numerators,
        denominator=denominator,
        selected=len(chosen),
        total=len(pool),
        contributing=sum(mass > 0 for mass in sheet_masses),
        min_peak=0.0,
        unit="share",
        normalization="total_observed_time",
    )


def walk_utilization_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """각 산책을 합 1로 정규화한 뒤 기여 산책을 동등 가중한 공간 비중."""
    _require_metric(spec, "walk_utilization")
    if spec.aggregation.min_peak != 0:
        raise ValueError("walk_utilization은 질량을 자르지 않는 min_peak=0만 지원한다")
    pool, chosen = _selection(sheets, spec)
    with_mass = [
        (sheet, math.fsum(sheet.occupancy.values())) for sheet in chosen if sheet.occupancy
    ]
    with_mass = [(sheet, mass) for sheet, mass in with_mass if mass > 0]
    numerators = {
        cell: math.fsum(sheet.occupancy.get(cell, 0.0) / mass for sheet, mass in with_mass)
        for cell in _cells(sheet for sheet, _ in with_mass)
    }
    numerators = {cell: value for cell, value in numerators.items() if value > 0}
    denominator = float(len(with_mass))
    values = (
        {cell: value / denominator for cell, value in numerators.items()} if denominator else {}
    )
    return _field(
        spec=spec,
        metric="walk_utilization",
        values=values,
        numerators=numerators,
        denominator=denominator,
        selected=len(chosen),
        total=len(pool),
        contributing=len(with_mass),
        min_peak=0.0,
        unit="share",
        normalization="equal_contributing_walks",
    )


def spatial_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """`spec.aggregation.metric`에 맞는 공간 통계를 계산한다."""
    metric = spec.aggregation.metric
    dispatch = {
        "total_time": total_time_field,
        "visit_rate": visit_rate_field,
        "conditional_dwell": conditional_dwell_field,
        "time_utilization": time_utilization_field,
        "walk_utilization": walk_utilization_field,
    }
    calculate = dispatch.get(metric)
    if calculate is None:
        raise ValueError(
            f"공간 통계 metric은 {sorted(SPATIAL_METRICS)} 중 하나여야 한다: {metric!r}"
        )
    return calculate(sheets, spec)
