"""육각 셀 격자 — 앱·서버·적재가 공유하는 하나의 공간 ID 체계. 순수함수.

`app/ingest/anchors.py` 가 앵커를 솎을 때 쓰던 수학을 여기로 올린다. 같은 개념의 해석은
한 곳이어야 한다(결정 #52). Android `LocalHexCellIndexer` 도 같은 투영·축좌표를 쓰므로
셀 id 는 세 곳에서 같은 값이다.

**육각인 이유**: 사각 격자는 이웃이 변(G)과 대각(1.41G) 두 거리라 방향마다 간격이 다르다.
육각은 이웃 6개가 등거리다.

## 셀이 격자 실험이 아니라 저장층인 이유

결정 #57 이 `walk_fix`(연속 궤적)를 finish 직후 purge 한다. 그래서 **좌표가 사라진 뒤에도
공간 질문에 답하려면** 좌표가 아닌 무언가가 남아야 한다. 셀 방문 기록이 그 손실 압축이다 —
"어느 셀에 얼마나" 만 남기면 뒤에 생긴 면도 셀 집합으로 근사되고, 물감도 셀에 쌓인다
(`app/geo/region.py` · `app/geo/paint.py`).

반지름이 곧 다이얼이다. 작을수록 정밀하고 좌표에 가깝다(28m 셀 id 는 사실상 좌표다).
어느 반지름에서 근사가 GPS 지터보다 작아지는지는 재야 하는 값이지 고르는 값이 아니다 —
`scripts/spike_region_fidelity.py`, `docs/research/2026-08-26-region-cell-fidelity.md`.

**무엇을 영구히 남길지는 아직 안 정했다** — 단순화 궤적과 산책별 셀 맵이 후보다
(`docs/explorations/walk/territory-paint.md` §A). 실사용 업로드는 #57·#58 이 막고 있어
지금 고를 필요가 없다.
"""

import math
from collections.abc import Iterable

EARTH_R = 6_378_137.0

# anchors.py 가 앵커를 솎은 반지름. 셀 간격 ≈ 199m.
ANCHOR_RADIUS_M = 115.0

Cell = tuple[int, int]


def mercator(lat: float, lng: float) -> tuple[float, float]:
    lat = max(-85.0, min(85.0, lat))
    return (
        EARTH_R * math.radians(lng),
        EARTH_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


def inverse_mercator(x: float, y: float) -> tuple[float, float]:
    return (
        math.degrees(2 * math.atan(math.exp(y / EARTH_R)) - math.pi / 2),
        math.degrees(x / EARTH_R),
    )


def _round_axial(q: float, r: float) -> Cell:
    x, z = q, r
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return rx, rz


def hex_cell(lat: float, lng: float, radius_m: float = ANCHOR_RADIUS_M) -> Cell:
    """좌표 → 셀 축좌표. 결정론 — 같은 좌표는 언제나 같은 셀이다."""
    x, y = mercator(lat, lng)
    return _round_axial(
        (math.sqrt(3) / 3 * x - y / 3) / radius_m,
        (2 / 3 * y) / radius_m,
    )


def hex_center(q: int, r: int, radius_m: float = ANCHOR_RADIUS_M) -> tuple[float, float]:
    """셀 → 투영 평면(미터) 중심. anchors.py 가 '중심 우선' 선별에 쓰는 값이다."""
    return (radius_m * math.sqrt(3) * (q + r / 2), radius_m * 1.5 * r)


def hex_center_latlng(q: int, r: int, radius_m: float = ANCHOR_RADIUS_M) -> tuple[float, float]:
    x, y = hex_center(q, r, radius_m)
    return inverse_mercator(x, y)


def hex_boundary_latlng(
    q: int, r: int, radius_m: float = ANCHOR_RADIUS_M
) -> list[tuple[float, float]]:
    """셀 6꼭짓점. Android PolygonOverlay 가 요구하는 시계방향이다."""
    cx, cy = hex_center(q, r, radius_m)
    ring = []
    for index in range(6):
        angle = math.radians(30.0 - 60.0 * index)
        ring.append(
            inverse_mercator(cx + radius_m * math.cos(angle), cy + radius_m * math.sin(angle))
        )
    return ring


def cell_id(cell: Cell, radius_m: float = ANCHOR_RADIUS_M) -> str:
    """반지름이 id 에 들어간다 — 반지름이 다르면 다른 격자고, 섞이면 안 된다."""
    return f"hex:{round(radius_m)}:{cell[0]}:{cell[1]}"


def hex_sample_points(
    q: int, r: int, radius_m: float, rings: int = 3
) -> Iterable[tuple[float, float]]:
    """셀 내부 표본점(투영 미터). 면적 교차를 적분 대신 표본으로 근사할 때 쓴다."""
    cx, cy = hex_center(q, r, radius_m)
    yield (cx, cy)
    for ring in range(1, rings + 1):
        # 육각 안에 확실히 들어가는 내접원 비율. sqrt(3)/2 가 내접원/외접원.
        rho = radius_m * (math.sqrt(3) / 2) * (ring / (rings + 0.5))
        count = 6 * ring
        for index in range(count):
            angle = 2 * math.pi * index / count
            yield (cx + rho * math.cos(angle), cy + rho * math.sin(angle))
