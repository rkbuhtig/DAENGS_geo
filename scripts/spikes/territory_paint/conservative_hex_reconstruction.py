"""Cellophane Hex를 평가용 연속 raster로 보수적으로 복원한다.

이 모듈의 출력은 저장 형식이나 새 통계 원판이 아니다. 산책별 Cellophane의 시간 질량과
방문 support를 공통 측정 raster로 옮긴 뒤 기존 통계 정의를 다시 적용하기 위한 일회성
렌더 입력이다.

두 복원법을 같은 계약 아래 둔다.

``piecewise``
    각 셀 질량을 그 셀에 속한 pixel에 균등 분배한다. raw Hex 기준선이다.
``local_blend``
    각 셀 질량을 같은 연결요소 안의 가까운 pixel에 compact kernel로 분배한다. source cell
    하나마다 weight를 다시 합 1로 맞추므로 시간 질량이 보존되고 빈 gap으로 새지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from app.features.territory.paint import Cellophane
from app.geo.cells import Cell, hex_boundary_latlng, hex_cell, hex_center_latlng, metres_per_unit
from scripts.spikes.territory_paint.continuous_hex_comparison import Pixel, RasterSpec

ReconstructionMethod = Literal["piecewise", "local_blend"]

_NEIGHBOURS: tuple[Cell, ...] = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


@dataclass(frozen=True)
class ReconstructionSpec:
    """평가용 복원 계약.

    ``blend_reach_cells``는 Hex 외접 반지름 배수다. 1.75이면 인접 셀 중심까지 닿지만
    활성 셀 연결요소와 원래 support mask로 잘리므로 빈 공간이나 다른 섬으로 번지지 않는다.
    """

    radius_u: float
    method: ReconstructionMethod = "local_blend"
    blend_reach_cells: float = 1.75

    def __post_init__(self) -> None:
        if not math.isfinite(self.radius_u) or self.radius_u <= 0:
            raise ValueError("radius_u는 유한한 양수여야 한다")
        if self.method not in {"piecewise", "local_blend"}:
            raise ValueError(f"지원하지 않는 복원법: {self.method!r}")
        if not math.isfinite(self.blend_reach_cells) or self.blend_reach_cells <= 0:
            raise ValueError("blend_reach_cells는 유한한 양수여야 한다")


@dataclass(frozen=True)
class ReconstructedRasterSheet:
    """한 Cellophane을 공통 raster로 옮긴 결과와 검산 영수증."""

    walk_id: str
    occupancy: dict[Pixel, float]
    peak: dict[Pixel, float]
    source_cell_count: int
    support_pixel_count: int
    connected_components: int
    source_mass_s: float
    support_evaluations: int
    weight_evaluations: int
    method: ReconstructionMethod

    @property
    def mass_s(self) -> float:
        return math.fsum(self.occupancy.values())

    @property
    def source_segment_s(self) -> float:
        # raster_metric_fields가 continuous RasterSheet와 같은 읽기 표면을 사용할 수 있게 한다.
        return self.source_mass_s


def _connected_components(cells: set[Cell]) -> tuple[dict[Cell, int], int]:
    labels: dict[Cell, int] = {}
    component = 0
    for root in sorted(cells):
        if root in labels:
            continue
        pending = [root]
        labels[root] = component
        while pending:
            q, r = pending.pop()
            for dq, dr in _NEIGHBOURS:
                neighbour = (q + dq, r + dr)
                if neighbour in cells and neighbour not in labels:
                    labels[neighbour] = component
                    pending.append(neighbour)
        component += 1
    return labels, component


def _support_pixels(
    cells: set[Cell],
    radius_u: float,
    raster: RasterSpec,
) -> tuple[dict[Cell, tuple[Pixel, ...]], dict[Pixel, Cell], int]:
    """pixel 중심이 활성 Hex에 속하는 support mask를 만든다."""
    if not cells:
        return {}, {}, 0
    by_cell: dict[Cell, list[Pixel]] = {cell: [] for cell in cells}
    owner_by_pixel: dict[Pixel, Cell] = {}
    evaluations = 0
    # 전체 cell bbox를 훑으면 서로 먼 두 섬이나 outlier 하나만으로 비용이 거리 제곱에 비례한다.
    # 각 Hex의 작은 bbox만 훑으면 비용은 활성 셀 수와 셀 면적에만 비례한다.
    for cell in sorted(cells):
        corners = [
            raster.pixel_at(lat, lng)
            for lat, lng in hex_boundary_latlng(*cell, radius_u)
        ]
        min_x = min(pixel[0] for pixel in corners) - 1
        max_x = max(pixel[0] for pixel in corners) + 1
        min_y = min(pixel[1] for pixel in corners) - 1
        max_y = max(pixel[1] for pixel in corners) + 1
        for pixel_x in range(min_x, max_x + 1):
            for pixel_y in range(min_y, max_y + 1):
                pixel = (pixel_x, pixel_y)
                evaluations += 1
                if hex_cell(*raster.centre_latlng(pixel), radius_u) == cell:
                    by_cell[cell].append(pixel)
                    owner_by_pixel[pixel] = cell

    # pixel이 Hex보다 거친 극단적인 evaluator 설정에서도 셀 질량을 잃지 않는다.
    for cell, pixels in by_cell.items():
        if pixels:
            continue
        centre_pixel = raster.pixel_at(*hex_center_latlng(*cell, radius_u))
        existing = owner_by_pixel.get(centre_pixel)
        if existing is not None and existing != cell:
            raise ValueError("raster가 너무 거칠어 서로 다른 활성 셀이 한 pixel로 접혔다")
        pixels.append(centre_pixel)
        owner_by_pixel[centre_pixel] = cell
    return (
        {cell: tuple(sorted(pixels)) for cell, pixels in by_cell.items()},
        owner_by_pixel,
        evaluations,
    )


def _compact_weight(distance_m: float, reach_m: float) -> float:
    """경계에서 값과 기울기가 0이 되는 compact smoothstep kernel."""
    if distance_m >= reach_m:
        return 0.0
    unit = max(0.0, 1.0 - distance_m / reach_m)
    return unit * unit * (3.0 - 2.0 * unit)


def reconstruct_cellophane(
    sheet: Cellophane,
    raster: RasterSpec,
    spec: ReconstructionSpec,
) -> ReconstructedRasterSheet:
    """한 장을 support·연결성·시간 질량을 보존해 raster로 옮긴다."""
    if not math.isclose(sheet.radius_u, spec.radius_u, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("Cellophane과 reconstruction radius_u가 다르다")
    active = {cell for cell, amount in sheet.occupancy.items() if amount > 0}
    source_mass = math.fsum(sheet.occupancy[cell] for cell in active)
    if not active:
        return ReconstructedRasterSheet(
            walk_id=sheet.walk_id,
            occupancy={},
            peak={},
            source_cell_count=0,
            support_pixel_count=0,
            connected_components=0,
            source_mass_s=0.0,
            support_evaluations=0,
            weight_evaluations=0,
            method=spec.method,
        )

    component_by_cell, component_count = _connected_components(active)
    pixels_by_cell, owner_by_pixel, support_evaluations = _support_pixels(
        active, spec.radius_u, raster
    )

    occupancy: dict[Pixel, float] = {}
    peak: dict[Pixel, float] = {}
    evaluations = 0
    reach_m = spec.blend_reach_cells * spec.radius_u * metres_per_unit(raster.origin_lat)
    for cell in sorted(active):
        if spec.method == "piecewise":
            candidates = pixels_by_cell[cell]
            weighted = [(pixel, 1.0) for pixel in candidates]
            evaluations += len(candidates)
        else:
            centre_east, centre_north = raster.local_xy(*hex_center_latlng(*cell, spec.radius_u))
            weighted = []
            home_x = math.floor(centre_east / raster.pixel_m)
            home_y = math.floor(centre_north / raster.pixel_m)
            margin = math.ceil(reach_m / raster.pixel_m) + 1
            for pixel_x in range(home_x - margin, home_x + margin + 1):
                for pixel_y in range(home_y - margin, home_y + margin + 1):
                    pixel = (pixel_x, pixel_y)
                    owner = owner_by_pixel.get(pixel)
                    if owner is None or component_by_cell[owner] != component_by_cell[cell]:
                        continue
                    evaluations += 1
                    east, north = raster.centre_xy(pixel)
                    weight = _compact_weight(
                        math.hypot(east - centre_east, north - centre_north), reach_m
                    )
                    if weight > 0:
                        weighted.append((pixel, weight))
            if not weighted:
                weighted = [(pixel, 1.0) for pixel in pixels_by_cell[cell]]

        weight_sum = math.fsum(weight for _, weight in weighted)
        amount = sheet.occupancy[cell]
        cell_peak = sheet.peak.get(cell, 0.0)
        for pixel, weight in weighted:
            share = weight / weight_sum
            occupancy[pixel] = occupancy.get(pixel, 0.0) + amount * share
            # peak는 합산하지 않는다. 렌더/검산용으로 가장 강한 source evidence만 남긴다.
            peak[pixel] = max(peak.get(pixel, 0.0), cell_peak * min(1.0, weight))

    result = ReconstructedRasterSheet(
        walk_id=sheet.walk_id,
        occupancy=occupancy,
        peak=peak,
        source_cell_count=len(active),
        support_pixel_count=len(owner_by_pixel),
        connected_components=component_count,
        source_mass_s=source_mass,
        support_evaluations=support_evaluations,
        weight_evaluations=evaluations,
        method=spec.method,
    )
    if set(result.occupancy) - set(owner_by_pixel):
        raise RuntimeError("복원값이 원래 Hex support 밖으로 누출됐다")
    if not math.isclose(result.mass_s, source_mass, rel_tol=1e-12, abs_tol=1e-8):
        raise RuntimeError("복원 raster가 Cellophane 시간 질량을 보존하지 못했다")
    return result


def reconstruct_cellophanes(
    sheets: tuple[Cellophane, ...],
    raster: RasterSpec,
    spec: ReconstructionSpec,
) -> tuple[ReconstructedRasterSheet, ...]:
    """통계 의미를 보존하기 위해 산책별로 복원한다."""
    return tuple(reconstruct_cellophane(sheet, raster, spec) for sheet in sheets)
