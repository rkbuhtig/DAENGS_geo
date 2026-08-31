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
UTILIZATION_METRICS: frozenset[str] = frozenset({"time_utilization", "walk_utilization"})
DEFAULT_MASS_LEVELS: tuple[float, ...] = (0.5, 0.8, 0.95)


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


@dataclass(frozen=True)
class MassRegion:
    """한 이용 분포에서 상위 밀도 셀로 회수한 목표 질량 영역."""

    target_mass: float
    achieved_mass: float
    cutoff_value: float | None
    cells: frozenset[Cell]

    def __post_init__(self) -> None:
        if not math.isfinite(self.target_mass) or not 0 < self.target_mass <= 1:
            raise ValueError("target_mass는 0보다 크고 1 이하여야 한다")
        if not math.isfinite(self.achieved_mass) or not 0 <= self.achieved_mass <= 1 + 1e-9:
            raise ValueError("achieved_mass는 0 이상 1 이하여야 한다")
        if self.cells and self.cutoff_value is None:
            raise ValueError("비어 있지 않은 질량 영역에는 cutoff_value가 필요하다")
        if self.cutoff_value is not None and (
            not math.isfinite(self.cutoff_value) or self.cutoff_value < 0
        ):
            raise ValueError("cutoff_value는 유한한 0 이상이어야 한다")


@dataclass(frozen=True)
class MassRegionSet:
    """분포 field 영수증과 50·80·95% 영역을 함께 보존한다."""

    field: SpatialField
    regions: tuple[MassRegion, ...]

    def __post_init__(self) -> None:
        if self.field.metric not in UTILIZATION_METRICS:
            raise ValueError("질량 영역은 time_utilization 또는 walk_utilization만 지원한다")
        targets = tuple(region.target_mass for region in self.regions)
        if tuple(sorted(set(targets))) != targets:
            raise ValueError("질량 영역 target은 중복 없이 오름차순이어야 한다")
        for smaller, larger in zip(self.regions, self.regions[1:], strict=False):
            if not smaller.cells <= larger.cells:
                raise ValueError("질량 영역은 target이 커질수록 포함 관계여야 한다")


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
    numerators: dict[Cell, float] = {}
    contributing = 0
    for sheet in chosen:
        sheet_contributes = False
        for cell, amount in sheet.occupancy.items():
            if not _qualified(sheet, cell, threshold):
                continue
            numerators[cell] = numerators.get(cell, 0.0) + amount
            sheet_contributes = sheet_contributes or amount > 0
        contributing += sheet_contributes
    numerators = {cell: value for cell, value in numerators.items() if value > 0}
    return _field(
        spec=spec,
        metric="total_time",
        values=dict(numerators),
        numerators=numerators,
        denominator=None,
        selected=len(chosen),
        total=len(pool),
        contributing=contributing,
        min_peak=threshold,
        unit="s",
        normalization="none",
    )


def visit_rate_field(sheets: Iterable[Cellophane], spec: LayerSpec) -> SpatialField:
    """셀마다 선택된 산책 중 `peak >= min_peak`인 산책 비율."""
    _require_metric(spec, "visit_rate")
    pool, chosen = _selection(sheets, spec)
    threshold = spec.aggregation.min_peak
    counts: dict[Cell, float] = {}
    for sheet in chosen:
        for cell in sheet.occupancy:
            if _qualified(sheet, cell, threshold):
                counts[cell] = counts.get(cell, 0.0) + 1.0
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
    contributing = 0
    for sheet in chosen:
        sheet_contributes = False
        for cell, amount in sheet.occupancy.items():
            if not _qualified(sheet, cell, threshold):
                continue
            numerators[cell] = numerators.get(cell, 0.0) + amount
            denominators[cell] = denominators.get(cell, 0.0) + 1.0
            sheet_contributes = sheet_contributes or amount > 0
        contributing += sheet_contributes
    numerators = {cell: value for cell, value in numerators.items() if value > 0}
    denominators = {cell: denominators[cell] for cell in numerators}
    values = {cell: numerators[cell] / denominators[cell] for cell in numerators}
    return _field(
        spec=spec,
        metric="conditional_dwell",
        values=values,
        numerators=numerators,
        denominator=denominators,
        selected=len(chosen),
        total=len(pool),
        contributing=contributing,
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
    numerators: dict[Cell, float] = {}
    contributing = 0
    for sheet in chosen:
        mass = math.fsum(sheet.occupancy.values())
        contributing += mass > 0
        for cell, amount in sheet.occupancy.items():
            numerators[cell] = numerators.get(cell, 0.0) + amount
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
        contributing=contributing,
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
    numerators: dict[Cell, float] = {}
    contributing = 0
    for sheet in chosen:
        mass = math.fsum(sheet.occupancy.values())
        if mass <= 0:
            continue
        contributing += 1
        for cell, amount in sheet.occupancy.items():
            numerators[cell] = numerators.get(cell, 0.0) + amount / mass
    numerators = {cell: value for cell, value in numerators.items() if value > 0}
    denominator = float(contributing)
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
        contributing=contributing,
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


def highest_mass_regions(
    field: SpatialField,
    levels: tuple[float, ...] = DEFAULT_MASS_LEVELS,
) -> MassRegionSet:
    """값이 큰 셀부터 누적한 질량 영역. cutoff 동률 셀은 모두 포함한다.

    동률을 셀 id 순서로 잘라 목표치에 억지로 맞추면 같은 밀도의 공간 중 일부만 임의로
    선택된다. 따라서 목표를 넘더라도 cutoff와 값이 같은 셀은 한꺼번에 포함하고 실제 회수
    질량을 `achieved_mass`로 돌려준다.
    """
    if field.metric not in UTILIZATION_METRICS:
        raise ValueError("질량 영역은 time_utilization 또는 walk_utilization만 지원한다")
    if not levels or any(not math.isfinite(level) or not 0 < level <= 1 for level in levels):
        raise ValueError("질량 영역 level은 0보다 크고 1 이하인 유한한 값이어야 한다")
    if tuple(sorted(set(levels))) != levels:
        raise ValueError("질량 영역 level은 중복 없이 오름차순이어야 한다")

    total_mass = math.fsum(field.values.values())
    if field.values and not math.isclose(total_mass, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError(f"이용 분포의 총질량은 1이어야 한다: {total_mass}")
    if not field.values:
        return MassRegionSet(
            field,
            tuple(MassRegion(level, 0.0, None, frozenset()) for level in levels),
        )

    ranked = sorted(field.values.items(), key=lambda item: (-item[1], item[0]))
    included: set[Cell] = set()
    index = 0
    regions = []
    for level in levels:
        achieved = math.fsum(field.values[cell] for cell in included)
        cutoff = ranked[index - 1][1] if index else None
        while achieved < level and index < len(ranked):
            cutoff = ranked[index][1]
            while index < len(ranked) and ranked[index][1] == cutoff:
                included.add(ranked[index][0])
                index += 1
            achieved = math.fsum(field.values[cell] for cell in included)
        regions.append(MassRegion(level, achieved, cutoff, frozenset(included)))
    return MassRegionSet(field, tuple(regions))
