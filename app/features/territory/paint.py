"""움직이는 점이 붓이 되어 지도를 칠한다. 순수함수 — DB·시계·난수 없음.

산책 점에 반경을 주면(그림판 브러시 굵기) 지나간 자리가 칠해진다. 칠한 것이 쌓이면
**자주 가는 영역이 저절로 진해진다.** 면을 그리지도, 궤적이 닫히지도 않아도 된다.

## 왜 이 모양인가 — 앞의 두 시도가 왜 접혔나

**면을 그리게 하기**: 사용자가 폴리곤을 그리고 궤적이 그 안에 얼마나 있었나를 쟀다
(`region.py`). 되긴 하는데 사용자가 먼저 그려야 하고, 셀이 면보다 4~5배는 작아야 답이 맞았다
(2026-08-26 측정).

**궤적이 면을 만들게 하기**: 산책은 집에서 나가 집으로 오니 고리일 것이라 봤다. 실제
도로망에서 확인하니 **아니었다** — 아파트 단지 길이 대부분 막다른 가지라 사람은 나갔던
길로 되돌아온다. 왕복 선은 넓이가 0 이다.

붓은 둘 다 필요 없다. **선에 두께를 주면 그게 면이다.** 그리고 두께는 우리가 정한다.

## 반경이 둘이고, 단위가 다르다

    brush_m   "지나갔으니 칠한다" 고 볼 반경. **실제 지상 미터.** 제품이 정한다
    radius_u  칠한 것을 저장하는 격자 해상도. **격자 단위.** 저장·프라이버시가 정한다

둘을 같은 숫자로 두면 안 된다. 붓이 셀보다 작으면 한 걸음이 셀 하나를 통째로 칠해
그림이 실제보다 뭉툭해지고, 붓이 셀보다 훨씬 크면 저장이 커진다.

**단위도 다르다.** 격자는 Web Mercator 라 위도 37.5° 에서 1 단위가 실제 0.79m 다.
`brush_stamp` 이 거리를 견줄 때 `metres_per_unit` 으로 되돌리는 이유이고, 넓이를 말할 때
`cells.cell_area_m2` 를 거치는 이유다.

## 집이 가장 진해진다

모든 산책이 현관에서 시작해 현관에서 끝난다. 그래서 **누적 그림에서 제일 밝은 칸은
반드시 집이다.** 결정 #57 이 `MotionEventOccurrence` 에 대해 지적한 것과 같은 구조인데,
칠하기는 그것을 그림으로 만들어 한눈에 보이게 한다. 이 그림을 남에게 보이는 기능은
그 사실을 먼저 처리해야 한다 (`home_bias` 로 얼마나 튀는지 잰다).
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.features.walk.facts import Segment
from app.geo.cells import (
    GRID_VERSION,
    Cell,
    cell_area_m2,
    hex_cell,
    hex_center_latlng,
    mercator,
    metres_per_unit,
)

# 이웃 셀 중심 사이 거리 = sqrt(3) × 반지름 (육각 격자)
NEIGHBOUR_FACTOR = math.sqrt(3)

# 칠하기 계산 세대. v1 은 stamp 가 닿은 모든 셀에 시간을 각각 복제했고, v2 는 stamp 안에서
# 가중치 합을 1 로 정규화해 segment 시간을 보존한다. 원좌표 purge 뒤에는 다시 칠할 수 없으므로
# 계산법 변경은 마이그레이션이 아니라 새 세대다.
PAINT_VERSION = 2


@dataclass
class Paint:
    """셀 한 칸의 **질의 결과**. 저장물이 아니라 `stack()` 이 그때그때 만든 값이다.

        occupancy  물감 총량. 가까이 오래 있을수록 큰다 (감쇠 반영)
        walks      문턱 이상으로 이 칸을 칠한 산책 수 — 빈도
        peak       그중 가장 강했던 세기

    `walks` 가 문턱에 달려 있다는 것이 핵심이다. 문턱 없이 세면 늘 12m 옆으로 지나간 49 회와
    한 번 밟은 1 회가 같은 빈도가 된다 — "자주 가는 길목에 붙어 있어서 자주 가는 것처럼
    보이는 곳" 이 거기서 생긴다.
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
class PaintSpec:
    """셀로판 한 장을 재현하는 계산 조건.

    `profile_name` 은 표시용이라 지문에서 빠진다. 동일성은 실제 곡선의 `profile_fp` 가
    담당한다. `sample_step_m` 도 공간 배분을 바꾸므로 버전만으로 숨기지 않고 실제 resolved
    값을 넣는다.
    """

    paint_version: int
    grid_version: str
    radius_u: float
    profile_name: str
    profile_fp: str
    sample_step_m: float

    def __post_init__(self) -> None:
        # JSON 은 같은 수인 8 과 8.0 을 다르게 직렬화한다. 호출자가 어느 표기를 썼는지로
        # 계산 세대가 갈리지 않도록 지문을 만들기 전에 연속량을 한 표현으로 고정한다.
        object.__setattr__(self, "radius_u", float(self.radius_u))
        object.__setattr__(self, "sample_step_m", float(self.sample_step_m))
        if self.paint_version < 1:
            raise ValueError("paint_version 은 양수여야 한다")
        if not self.grid_version or not self.profile_name or not self.profile_fp:
            raise ValueError("grid/profile identity 는 비어 있을 수 없다")
        if not math.isfinite(self.radius_u) or self.radius_u <= 0:
            raise ValueError("radius_u 는 유한한 양수여야 한다")
        if not math.isfinite(self.sample_step_m) or self.sample_step_m <= 0:
            raise ValueError("sample_step_m 은 유한한 양수여야 한다")

    @property
    def fingerprint(self) -> str:
        """표시 이름을 제외한 계산 의미의 지문."""
        blob = json.dumps(
            {
                "grid_version": self.grid_version,
                "paint_version": self.paint_version,
                "profile_fp": self.profile_fp,
                "radius_u": self.radius_u,
                "sample_step_m": self.sample_step_m,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Cellophane:
    """산책 한 번의 셀 맵 — **셀로판 한 장**.

    이것이 저장 단위 후보다. 조건(계절·시간대)으로 장을 골라 겹치면 그 조건에서의 행동이
    지도로 나온다. 장을 미리 접어 한 장으로 만들면 되돌릴 수 없다 (`stack` 참고).

    `radius_u` 와 `profile` 을 같이 들고 다니는 이유: 격자나 붓이 바뀌면 다른 장이다.
    섞어서 겹치면 조용히 틀린 그림이 된다.
    """

    walk_id: str
    at: datetime
    radius_u: float
    profile: str
    occupancy: dict[Cell, float]
    peak: dict[Cell, float]
    # 기본값이 없다. v1 캐시가 v2 장으로 조용히 복원되는 것보다 명확히 실패하고 다시
    # 칠하는 편이 안전하다.
    paint_version: int
    grid_version: str
    profile_fp: str
    sample_step_m: float
    paint_fp: str

    @property
    def spec(self) -> PaintSpec:
        return PaintSpec(
            paint_version=self.paint_version,
            grid_version=self.grid_version,
            radius_u=self.radius_u,
            profile_name=self.profile,
            profile_fp=self.profile_fp,
            sample_step_m=self.sample_step_m,
        )

    def __post_init__(self) -> None:
        spec = self.spec
        object.__setattr__(self, "radius_u", spec.radius_u)
        object.__setattr__(self, "sample_step_m", spec.sample_step_m)
        expected = spec.fingerprint
        if self.paint_fp != expected:
            raise ValueError(
                f"paint_fp 가 계산 조건과 다르다: expected={expected}, actual={self.paint_fp}"
            )


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
    _pairs: tuple = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.bands) != len(self.weights) or not self.bands:
            raise ValueError("bands 와 weights 는 길이가 같고 비어 있지 않아야 한다")
        if any(not math.isfinite(band) or band <= 0 for band in self.bands):
            raise ValueError("bands 는 유한한 양수여야 한다")
        if any(a >= b for a, b in zip(self.bands, self.bands[1:], strict=False)):
            raise ValueError("bands 는 엄격한 오름차순이어야 한다")
        if any(not math.isfinite(weight) or not 0 <= weight <= 1 for weight in self.weights):
            raise ValueError("weights 는 0 이상 1 이하의 유한한 값이어야 한다")
        if self.weights[0] <= 0:
            raise ValueError("중심 weight 는 0보다 커야 한다")
        if any(a < b for a, b in zip(self.weights, self.weights[1:], strict=False)):
            raise ValueError("weights 는 중심에서 바깥으로 비증가해야 한다")
        # (반경, 세기) 쌍을 미리 묶는다. weight_at 은 점 하나마다 수십 번 불리는 자리라
        # 매번 zip 을 만들면 그것만으로 시간이 간다.
        object.__setattr__(self, "_pairs", tuple(zip(self.bands, self.weights, strict=True)))

    @property
    def reach_m(self) -> float:
        return self.bands[-1]

    @property
    def fingerprint(self) -> str:
        """감쇠 곡선의 지문 — bands · weights · smooth. 이름과 달리 **바꾸면 반드시 바뀐다.**

        이름은 표시용이고 지문이 동일성이다. 같은 이름으로 곡선을 바꾸면 spec 상 같은 붓처럼
        보이는 문제를 여기서 막는다 — "이름을 꼭 바꾼다" 는 규율에 기대지 않는다.
        """
        blob = f"{self.bands}|{self.weights}|{self.smooth}"
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def weight_at(self, distance: float) -> float:
        """중심에서 `distance` 만큼 떨어진 곳에 묻는 물감의 양. 밖이면 0."""
        pairs = self._pairs
        if distance > pairs[-1][0]:
            return 0.0
        if not self.smooth:
            for band, weight in pairs:
                if distance <= band:
                    return weight
            return 0.0
        previous_band, previous_weight = 0.0, pairs[0][1]
        for band, weight in pairs:
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


def paint_spec(
    radius_u: float,
    profile: BrushProfile,
    step_m: float = 0.0,
) -> PaintSpec:
    """호출 인자에서 실제 계산 조건을 한 번만 결정한다.

    현재 제품 경로는 아직 없으므로 실험은 `step_m` 을 바꿀 수 있다. 대신 어떤 값으로
    칠했든 resolved 값과 지문이 장에 남는다. 나중에 canonical 제품 경로를 열 때는 이 인자를
    노출하지 않고 결정된 spec 하나만 사용한다.
    """
    if not math.isfinite(step_m) or step_m < 0:
        raise ValueError("step_m 은 0 이상의 유한한 값이어야 한다")
    resolved_step = step_m or max(min(radius_u, profile.bands[0]) / 2.0, 1.5)
    return PaintSpec(
        paint_version=PAINT_VERSION,
        grid_version=GRID_VERSION,
        radius_u=radius_u,
        profile_name=profile.name,
        profile_fp=profile.fingerprint,
        sample_step_m=resolved_step,
    )


def brush_stamp(
    lat: float, lng: float, radius_u: float, profile: BrushProfile
) -> list[tuple[Cell, float]]:
    """점 하나가 남기는 자국 — (셀, 물감량) 목록.

    셀 중심까지의 **연속 거리**로 물감을 정한다. "반경 N 붓이 이 칸을 덮었나" 를 세 번 묻는
    것과 다르다: 그렇게 하면 셀이 밴드보다 클 때 세 밴드가 같은 칸을 칠해 구별이 사라진다.
    거리로 재면 셀 크기는 값을 어디에 보관할지만 정하고 답의 해상도는 정하지 않는다.

    **거리는 실제 지상 미터다.** 격자 좌표는 Web Mercator 라 위도만큼 늘어나 있으므로
    `metres_per_unit` 로 되돌린 뒤 밴드와 견준다 — 이걸 안 하면 `3·8·20` 밴드가 위도
    37.5° 에서 실제 2.4·6.3·15.9m 로 동작한다.

    붓이 셀보다 작아도 **최소 한 칸**은 칠한다 — 지나갔는데 아무것도 안 남으면 구멍이 뚫린다.
    """
    home_q, home_r = hex_cell(lat, lng, radius_u)
    scale = metres_per_unit(lat)                      # 단위 → 미터
    reach_u = profile.reach_m / scale
    reach = math.ceil(reach_u / (NEIGHBOUR_FACTOR * radius_u)) + 1
    x, y = mercator(lat, lng)
    # hex_center 를 안쪽 루프에서 부르지 않고 선형 관계를 펼친다. 점 하나마다 수십 칸을
    # 훑는 자리라 함수 호출 하나가 전체 시간을 지배한다.
    span = radius_u * NEIGHBOUR_FACTOR
    rise = radius_u * 1.5
    limit_sq = reach_u * reach_u
    weight_at = profile.weight_at
    out: list[tuple[Cell, float]] = []
    for dq in range(-reach, reach + 1):
        q = home_q + dq
        for dr in range(max(-reach, -dq - reach), min(reach, -dq + reach) + 1):
            r = home_r + dr
            dx = span * (q + r * 0.5) - x
            dy = rise * r - y
            d_sq = dx * dx + dy * dy
            if d_sq > limit_sq:                       # 도달 밖 — 제곱으로 먼저 자른다
                continue
            weight = weight_at(math.sqrt(d_sq) * scale)
            if weight > 0:
                out.append(((q, r), weight))
    return out or [((home_q, home_r), profile.weights[0])]


def paint_sheet(
    walk_id: str,
    at: datetime,
    segments: list[Segment],
    radius_u: float,
    profile: BrushProfile,
    step_m: float = 0.0,
) -> "Cellophane":
    """산책 한 번 → 셀로판 한 장. 물감과 최대 세기를 **같이** 만든다.

    한 번 훑으면서 둘 다 뽑는 이유는 서로 다른 질문에 답하기 때문이다 — 물감은 "얼마나
    오래", 최대 세기는 "얼마나 가까이". 옆으로만 스쳐도 오래 걸으면 물감은 커지지만 세기는
    낮게 남는다.
    """
    spec = paint_spec(radius_u, profile, step_m)
    step = spec.sample_step_m
    occupancy: dict[Cell, float] = {}
    peak: dict[Cell, float] = {}
    for seg in segments:
        pieces = max(1, math.ceil(seg.dist / step))
        share = seg.dt / pieces
        for index in range(pieces):
            frac = (index + 0.5) / pieces
            lat = seg.a.lat + (seg.b.lat - seg.a.lat) * frac
            lng = seg.a.lng + (seg.b.lng - seg.a.lng) * frac
            stamp = brush_stamp(lat, lng, radius_u, profile)
            total_weight = math.fsum(weight for _, weight in stamp)
            if total_weight <= 0:  # BrushProfile 계약과 brush_stamp fallback 이 지키는 불변식
                raise RuntimeError("brush stamp has no positive mass")
            for cell, raw_weight in stamp:
                # occupancy 는 셀에 배분된 **관측 시간 질량(초)** 이다. 실제 육각형 안 체류
                # 시간은 아니지만, stamp 전체 합은 정확히 `share` 여야 한다.
                occupancy[cell] = (
                    occupancy.get(cell, 0.0) + share * raw_weight / total_weight
                )
                # peak 는 "얼마나 가까이 왔나"라 kernel 정규화의 영향을 받지 않는다.
                if raw_weight > peak.get(cell, 0.0):
                    peak[cell] = raw_weight
    return Cellophane(walk_id=walk_id, at=at, radius_u=radius_u, profile=profile.name,
                      occupancy=occupancy, peak=peak,
                      paint_version=spec.paint_version, grid_version=spec.grid_version,
                      profile_fp=spec.profile_fp, sample_step_m=spec.sample_step_m,
                      paint_fp=spec.fingerprint)


def stack(sheets: list[Cellophane], min_peak: float = 0.0) -> dict[Cell, Paint]:
    """셀로판 여러 장을 겹친다. **집계는 질의이지 저장이 아니다.**

    `min_peak` 미만으로만 스친 산책은 그 칸에서 **세지 않는다.** 문턱이 인자인 것이 핵심이다:

        직접 통과 1 회(peak 1.0) + 12m 옆 통과 49 회(peak 0.15)

    를 장별로 들고 있으면 `min_peak=0.9` 로 "밟은 건 1 회" 를 답할 수 있다. 장을 미리 접어
    칸마다 최대값 하나로 만들면 `walks=50 · peak=1.0` 이 되어 "50 번 다 밟았다" 와 구별되지
    않는다 — 이 설계가 막으려던 바로 그 혼동이 집계 단계에서 되살아난다.

    그래서 원본은 장으로 남기고, 문턱은 물을 때마다 고른다.
    """
    identities = {sheet.paint_fp for sheet in sheets}
    if len(identities) > 1:
        raise ValueError(
            "서로 다른 paint 세대의 셀로판은 겹칠 수 없다: "
            f"{sorted(identities)}"
        )

    canvas: dict[Cell, Paint] = {}
    for sheet in sheets:
        for cell, amount in sheet.occupancy.items():
            weight = sheet.peak.get(cell, 0.0)
            if weight < min_peak:
                continue
            paint = canvas.get(cell)
            if paint is None:
                paint = canvas[cell] = Paint(cell=cell)
            paint.occupancy += amount
            paint.walks += 1
            paint.peak = max(paint.peak, weight)
            paint.first_at = sheet.at if paint.first_at is None else min(paint.first_at, sheet.at)
            paint.last_at = sheet.at if paint.last_at is None else max(paint.last_at, sheet.at)
    return canvas


def peak_counts(sheets: list[Cellophane], cell: Cell) -> list[float]:
    """한 칸이 장마다 받은 최대 세기 목록. 문턱을 정하기 전에 분포를 보는 용도."""
    return sorted((s.peak.get(cell, 0.0) for s in sheets), reverse=True)


@dataclass
class CanvasStats:
    """겹친 결과 한 장의 성질. 계약이 아니라 판단 재료다."""

    cells: int = 0
    area_m2: float = 0.0
    total_occupancy: float = 0.0
    max_walks: int = 0
    core_cells: int = 0                 # 전체 산책의 절반 이상에서 칠해진 칸
    # 심 밴드 안까지 들어온 칸. **"밟았다" 가 아니다** — GPS 오차가 심보다 크면 심 안에
    # 찍혔다는 것이 실제로 그 자리에 있었다는 뜻이 못 된다. 이름이 주장을 넘지 않게 둔다.
    core_hit_cells: int = 0
    fringe_cells: int = 0               # 자주 칠해졌지만 세기가 낮은 칸 — 옆을 지난 곳
    home_bias: float = 0.0              # 최다 방문 칸 ÷ 중앙값 — 집이 얼마나 튀나
    walks_hist: list[int] = field(default_factory=list)


def canvas_stats(canvas: dict[Cell, Paint], radius_u: float, walk_count: int) -> CanvasStats:
    """넓이는 **실제 지상 면적**이다. 위도는 칸들의 중앙값에서 얻는다."""
    if not canvas:
        return CanvasStats()
    lats = sorted(hex_center_latlng(*p.cell, radius_u)[0] for p in canvas.values())
    lat = lats[len(lats) // 2]
    hex_area = cell_area_m2(radius_u, lat)
    counts = sorted(p.walks for p in canvas.values())
    middle = counts[len(counts) // 2]
    often = max(1, walk_count / 2)
    return CanvasStats(
        cells=len(canvas),
        area_m2=len(canvas) * hex_area,
        total_occupancy=sum(p.occupancy for p in canvas.values()),
        max_walks=counts[-1],
        core_cells=sum(1 for c in counts if c >= often),
        core_hit_cells=sum(1 for p in canvas.values() if p.peak >= 0.9),
        # 자주 칠해졌는데 한 번도 가까이 안 간 칸. 이 수가 크면 "옆동네가 내 영역인 척" 한다
        fringe_cells=sum(1 for p in canvas.values() if p.walks >= often and p.peak < 0.5),
        home_bias=counts[-1] / middle if middle else 0.0,
        walks_hist=counts,
    )


def shift_times(base: datetime, day: int, hour: int = 8) -> datetime:
    """스파이크 편의 — 산책 n 번째 날의 시각. 난수 없이 결정론으로 벌린다."""
    return base + timedelta(days=day, hours=hour)
