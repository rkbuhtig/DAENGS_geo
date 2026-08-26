"""움직이는 점이 붓이 되어 지도를 칠한다. 순수함수 — DB·시계·난수 없음.

산책 점에 반경을 주면(그림판 브러시 굵기) 지나간 자리가 칠해진다. 칠한 것이 쌓이면
**자주 가는 영역이 저절로 진해진다.** 면을 그리지도, 궤적이 닫히지도 않아도 된다.

## 왜 이 모양인가 — 앞의 두 시도가 왜 접혔나

**면을 그리게 하기**: 사용자가 폴리곤을 그리고 궤적이 그 안에 얼마나 있었나를 쟀다
(`region.py`). 되긴 하는데 사용자가 먼저 그려야 하고, 셀이 면보다 5배는 작아야 답이 맞았다
(2026-08-26 측정).

**궤적이 면을 만들게 하기**: 산책은 집에서 나가 집으로 오니 고리일 것이라 봤다. 실제
도로망에서 확인하니 **아니었다** — 아파트 단지 길이 대부분 막다른 가지라 사람은 나갔던
길로 되돌아온다. 왕복 선은 넓이가 0 이다.

붓은 둘 다 필요 없다. **선에 두께를 주면 그게 면이다.** 그리고 두께는 우리가 정한다.

## 반경이 둘인 것에 주의

    brush_m      "지나갔으니 칠한다" 고 볼 반경. 제품이 정하는 값이다
    cell_radius  칠한 것을 저장하는 격자 해상도. 저장·프라이버시가 정하는 값이다

둘을 같은 숫자로 두면 안 된다. 붓이 셀보다 작으면 한 걸음이 셀 하나를 통째로 칠해
그림이 실제보다 뭉툭해지고, 붓이 셀보다 훨씬 크면 저장이 커진다.

## 집이 가장 진해진다

모든 산책이 현관에서 시작해 현관에서 끝난다. 그래서 **누적 그림에서 제일 밝은 칸은
반드시 집이다.** 결정 #57 이 `MotionEventOccurrence` 에 대해 지적한 것과 같은 구조인데,
칠하기는 그것을 그림으로 만들어 한눈에 보이게 한다. 이 그림을 남에게 보이는 기능은
그 사실을 먼저 처리해야 한다 (`home_bias` 로 얼마나 튀는지 잰다).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.features.walk.facts import Segment
from app.geo.cells import Cell, hex_cell, hex_center, mercator

# 이웃 셀 중심 사이 거리 = sqrt(3) × 반지름 (육각 격자)
NEIGHBOUR_FACTOR = math.sqrt(3)


@dataclass
class Paint:
    """셀 한 칸에 쌓인 물감.

    숫자가 셋인 이유는 **하나로는 근접과 빈도가 구별되지 않기 때문**이다.

        occupancy  물감 총량. 가까이 오래 있을수록 큰다 (감쇠 반영)
        walks      이 칸에 물감이 조금이라도 묻은 산책 수 — 빈도
        peak       한 번의 산책에서 받은 최대 세기 — **가장 가까웠던 정도**

    `peak` 이 결정적이다. 늘 18m 옆으로 지나가는 칸은 24 번 칠해져도 peak 이 낮고, 한 번이라도
    밟은 칸은 peak 이 1.0 이다. "자주 가는 길목에 붙어 있어서 자주 가는 것처럼 보이는 곳"이
    여기서 갈린다.
    """

    cell: Cell
    occupancy: float = 0.0
    walks: int = 0
    peak: float = 0.0
    first_at: datetime | None = None
    last_at: datetime | None = None

    @property
    def id(self) -> str:
        return f"{self.cell[0]}:{self.cell[1]}"


@dataclass(frozen=True)
class BrushProfile:
    """붓 한 번의 단면 — 중심에서 멀어질수록 옅어진다.

    **밴드는 저장할 계측값이 아니라 도장의 모양이다.** 셀마다 밴드별 카운터를 따로 두는 안도
    있었는데(그러면 사후에 반지름을 다시 고를 수 있다 — #59 가 시설 밴드에 그렇게 했다),
    여기서는 접었다. 붓 굵기는 *측정 문턱*이 아니라 *표시 선택*이라 사후 변경의 값이
    시설 밴드만큼 크지 않고, 칸마다 숫자 하나면 충분하기 때문이다.

    **대신 감쇠는 칠하는 시점에 값에 굽힌다.** 원좌표는 purge 되므로(결정 #57) 나중에
    다른 곡선으로 다시 칠할 수 없다. 곡선을 바꾸면 그 뒤 산책부터 적용되고 과거는 옛
    곡선으로 남는다 — 그래서 `name` 을 값과 함께 남길 수 있게 이름을 붙여 둔다.

    `bands` 는 오름차순 반경, `weights` 는 각 반경에서의 세기다. `smooth=True` 면
    구간 사이를 선형 보간해 경계가 안 보이고, `False` 면 계단이라 등고선처럼 보인다.
    """

    name: str
    bands: tuple[float, ...]
    weights: tuple[float, ...]
    smooth: bool = False

    def __post_init__(self) -> None:
        if len(self.bands) != len(self.weights) or not self.bands:
            raise ValueError("bands 와 weights 는 길이가 같고 비어 있지 않아야 한다")
        if list(self.bands) != sorted(self.bands):
            raise ValueError("bands 는 오름차순이어야 한다")

    @property
    def reach_m(self) -> float:
        return self.bands[-1]

    def weight_at(self, distance: float) -> float:
        """중심에서 `distance` 만큼 떨어진 곳에 묻는 물감의 양. 밖이면 0."""
        if distance > self.bands[-1]:
            return 0.0
        if not self.smooth:
            for band, weight in zip(self.bands, self.weights, strict=True):
                if distance <= band:
                    return weight
            return 0.0
        previous_band, previous_weight = 0.0, self.weights[0]
        for band, weight in zip(self.bands, self.weights, strict=True):
            if distance <= band:
                span = band - previous_band
                if span <= 0:
                    return weight
                t = (distance - previous_band) / span
                return previous_weight + (weight - previous_weight) * t
            previous_band, previous_weight = band, weight
        return 0.0


# 이진 도장 — 감쇠 없음. 예전 동작이고, 감쇠와 비교하는 대조군으로 남긴다.
def flat(brush_m: float) -> BrushProfile:
    return BrushProfile(f"이진 {brush_m:.0f}m", (brush_m,), (1.0,))


# 보행로 폭 기준. 인도 2~4m, 왕복 2차선 8~10m — "밟음 / 같은 길 / 옆 블록".
NARROW_STEP = BrushProfile("계단 3·8·20", (3.0, 8.0, 20.0), (1.0, 0.45, 0.15))
NARROW_SMOOTH = BrushProfile("연속 3·8·20", (3.0, 8.0, 20.0), (1.0, 0.45, 0.15), smooth=True)
# encounter.py 가 시설 점 기준으로 쓰던 눈금. 비교용.
FACILITY_STEP = BrushProfile("계단 10·15·20", (10.0, 15.0, 20.0), (1.0, 0.5, 0.2))
FACILITY_SMOOTH = BrushProfile(
    "연속 10·15·20", (10.0, 15.0, 20.0), (1.0, 0.5, 0.2), smooth=True
)


def brush_stamp(
    lat: float, lng: float, cell_radius: float, profile: BrushProfile
) -> list[tuple[Cell, float]]:
    """점 하나가 남기는 자국 — (셀, 물감량) 목록.

    셀 중심까지의 **연속 거리**로 물감을 정한다. "반경 N 붓이 이 칸을 덮었나" 를 세 번 묻는
    것과 다르다: 그렇게 하면 셀이 밴드보다 클 때 세 밴드가 같은 칸을 칠해 구별이 사라진다.
    거리로 재면 셀 크기는 값을 어디에 보관할지만 정하고 답의 해상도는 정하지 않는다.

    붓이 셀보다 작아도 **최소 한 칸**은 칠한다 — 지나갔는데 아무것도 안 남으면 구멍이 뚫린다.
    """
    home = hex_cell(lat, lng, cell_radius)
    reach = math.ceil(profile.reach_m / (NEIGHBOUR_FACTOR * cell_radius)) + 1
    x, y = mercator(lat, lng)
    out: list[tuple[Cell, float]] = []
    for dq in range(-reach, reach + 1):
        for dr in range(max(-reach, -dq - reach), min(reach, -dq + reach) + 1):
            cell = (home[0] + dq, home[1] + dr)
            cx, cy = hex_center(*cell, cell_radius)
            weight = profile.weight_at(math.hypot(cx - x, cy - y))
            if weight > 0:
                out.append((cell, weight))
    return out or [(home, profile.weights[0])]


def paint_walk(
    segments: list[Segment], cell_radius: float, profile: BrushProfile, step_m: float = 0.0
) -> dict[Cell, float]:
    """산책 한 번 → 셀별 물감량.

    세그먼트를 잘라 각 조각의 시간을 그 지점의 자국에 묻힌다. 한 조각이 여러 칸에 묻으면
    시간을 **나누지 않고 각 칸에 세기만큼 준다** — 물감은 시간의 분배가 아니라 "그 칸
    근처에 있었던 정도" 라서다.

    **그래서 칸 값을 다 더하면 산책 시간보다 크다.** 시간 예산이 아니라 점유량이다.
    """
    step = step_m or max(min(cell_radius, profile.bands[0]) / 2.0, 1.5)
    painted: dict[Cell, float] = {}
    for seg in segments:
        pieces = max(1, math.ceil(seg.dist / step))
        share = seg.dt / pieces
        for index in range(pieces):
            frac = (index + 0.5) / pieces
            lat = seg.a.lat + (seg.b.lat - seg.a.lat) * frac
            lng = seg.a.lng + (seg.b.lng - seg.a.lng) * frac
            for cell, weight in brush_stamp(lat, lng, cell_radius, profile):
                painted[cell] = painted.get(cell, 0.0) + share * weight
    return painted


def accumulate(
    walks: list[tuple[dict[Cell, float], datetime]],
    peaks: list[dict[Cell, float]] | None = None,
) -> dict[Cell, Paint]:
    """여러 산책의 물감을 겹친다. `walks` 는 (셀별 물감, 그 산책 시각).

    `peaks` 는 산책별 셀 최대 세기 — `paint_walk_peaks` 가 준다. 없으면 `peak` 은 0 이다.
    """
    canvas: dict[Cell, Paint] = {}
    for index, (painted, at) in enumerate(walks):
        peak_map = peaks[index] if peaks else {}
        for cell, amount in painted.items():
            paint = canvas.get(cell)
            if paint is None:
                paint = canvas[cell] = Paint(cell=cell)
            paint.occupancy += amount
            paint.walks += 1
            paint.peak = max(paint.peak, peak_map.get(cell, 0.0))
            paint.first_at = at if paint.first_at is None else min(paint.first_at, at)
            paint.last_at = at if paint.last_at is None else max(paint.last_at, at)
    return canvas


def paint_walk_peaks(
    segments: list[Segment], cell_radius: float, profile: BrushProfile, step_m: float = 0.0
) -> dict[Cell, float]:
    """산책 한 번에서 각 칸이 받은 **최대 세기**. 누적이 아니라 최댓값이다.

    누적(`paint_walk`)은 "오래 있었나"를, 이건 "얼마나 가까이 왔나"를 답한다. 옆으로만
    스쳐도 오래 걸으면 누적은 커지지만 최대 세기는 낮게 남는다.
    """
    step = step_m or max(min(cell_radius, profile.bands[0]) / 2.0, 1.5)
    peaks: dict[Cell, float] = {}
    for seg in segments:
        pieces = max(1, math.ceil(seg.dist / step))
        for index in range(pieces):
            frac = (index + 0.5) / pieces
            lat = seg.a.lat + (seg.b.lat - seg.a.lat) * frac
            lng = seg.a.lng + (seg.b.lng - seg.a.lng) * frac
            for cell, weight in brush_stamp(lat, lng, cell_radius, profile):
                if weight > peaks.get(cell, 0.0):
                    peaks[cell] = weight
    return peaks


@dataclass
class CanvasStats:
    """칠한 지도 한 장의 성질. 계약이 아니라 판단 재료다."""

    cells: int = 0
    area_m2: float = 0.0
    total_occupancy: float = 0.0
    max_walks: int = 0
    core_cells: int = 0                 # 전체 산책의 절반 이상에서 칠해진 칸
    trodden_cells: int = 0              # peak 이 높은 칸 — 실제로 밟은 곳
    fringe_cells: int = 0               # 자주 칠해졌지만 peak 이 낮은 칸 — 옆을 지난 곳
    home_bias: float = 0.0              # 최다 방문 칸 ÷ 중앙값 — 집이 얼마나 튀나
    walks_hist: list[int] = field(default_factory=list)


def canvas_stats(canvas: dict[Cell, Paint], cell_radius: float, walk_count: int) -> CanvasStats:
    if not canvas:
        return CanvasStats()
    hex_area = 1.5 * math.sqrt(3) * cell_radius**2
    counts = sorted(p.walks for p in canvas.values())
    middle = counts[len(counts) // 2]
    often = max(1, walk_count / 2)
    return CanvasStats(
        cells=len(canvas),
        area_m2=len(canvas) * hex_area,
        total_occupancy=sum(p.occupancy for p in canvas.values()),
        max_walks=counts[-1],
        core_cells=sum(1 for c in counts if c >= often),
        trodden_cells=sum(1 for p in canvas.values() if p.peak >= 0.9),
        # 자주 칠해졌는데 한 번도 가까이 안 간 칸. 이 수가 크면 "옆동네가 내 영역인 척" 한다
        fringe_cells=sum(1 for p in canvas.values() if p.walks >= often and p.peak < 0.5),
        home_bias=counts[-1] / middle if middle else 0.0,
        walks_hist=counts,
    )


def shift_times(base: datetime, day: int, hour: int = 8) -> datetime:
    """스파이크 편의 — 산책 n 번째 날의 시각. 난수 없이 결정론으로 벌린다."""
    return base + timedelta(days=day, hours=hour)
