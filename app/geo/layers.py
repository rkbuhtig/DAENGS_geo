"""조건으로 산책을 골라 겹친 결과 — 셀로판 질의층. 순수함수.

`paint.py` 가 산책 한 번을 장으로 만들면, 여기가 **어떤 장을 어떻게 겹칠지**를 정한다.
지도는 저장된 진실이 아니라 이 질의의 결과다.

    LayerSpec
    ├─ selector     무슨 산책을 고르나   period · tags
    ├─ aggregation  어떻게 합치나        metric · min_peak
    └─ projection   어떻게 공간에 놓나   grid · brush

세 구획을 가르는 이유는 취향이 아니다. 하나로 뭉치면 "여름 지도" 라고만 적힌 그림이
6 개월 뒤 붓을 바꿨을 때 **말없이 다른 그림**이 된다. 결과가 늘 spec 을 달고 다녀야
LLM 이 "여름 밤에 이쪽을 많이 다니셨네요" 라고 했을 때 무슨 조건·집계였는지 따라갈 수 있다
(`calculation_version` · `occurrence_version` · 결정 #65 의 mapping version 과 같은 이유).

## 태그는 여기서 파생한다

산책이 들고 있는 것은 `started_at` 뿐이다. 계절·시간대·요일은 **관측값에서 뽑는다** —
원천에 박아 두면 나중에 "7월에만 나타난 변화" 가 "여름" 에 흡수돼 사라진다(결정 #65 §4 의
원천 사실 / 파생 태그 분리와 같은 규율).

## 두 종류의 연산을 섞지 않는다

    존재(support)   A ∪ B · A ∩ B · A − B      "간 적 있나"
    값(rate)        rate(A) − rate(B)          "얼마나 자주 갔나"

존재 연산만으로는 편향을 못 본다 — 여름 90% · 겨울 10% 로 가는 칸은 `A − B` 에서 사라진다.
둘 다 support 에 있기 때문이다. 정작 보고 싶은 건 그 80%p 차이다.

`rate` 는 **고른 산책 수로 나눈 값**이다. 그래서 여름 90 회와 겨울 18 회를 견줄 수 있다.
`Layer.selected` 가 늘 붙어 다니는 이유이기도 하다 — 비율은 분모 없이 읽으면 안 된다.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from app.geo.cells import GRID_VERSION, Cell
from app.geo.paint import Cellophane, Paint, stack

LAYER_SPEC_VERSION = 1

# 질의층이 정하는 시간대. 생성기의 시각 분포와 **독립**이어야 파생이 검증 대상이 된다.
TIME_BANDS: tuple[tuple[str, int, int], ...] = (
    ("night", 21, 24),
    ("dawn", 0, 5),
    ("morning", 5, 11),
    ("day", 11, 17),
    ("evening", 17, 21),
)
SEASON_OF_MONTH = {
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
    12: "winter", 1: "winter", 2: "winter",
}


def derive_tags(started_at: datetime) -> dict[str, str]:
    """관측된 시각 하나에서 뽑는 파생 태그. 결정론 — 같은 시각은 같은 태그다.

    `night` 를 21~24 로만 두고 0~5 를 `dawn` 으로 가르는 이유: 자정을 넘겨 걷는 산책과
    새벽 산책은 다른 행동인데 한 이름으로 묶으면 그 구분이 데이터에서 사라진다.
    """
    hour = started_at.hour
    band = next((name for name, low, high in TIME_BANDS if low <= hour < high), "night")
    return {
        "season": SEASON_OF_MONTH[started_at.month],
        "time_band": band,
        "day_type": "weekend" if started_at.weekday() >= 5 else "weekday",
        "month": f"{started_at.month:02d}",
        "quarter": f"Q{(started_at.month - 1) // 3 + 1}",
    }


@dataclass(frozen=True)
class Selector:
    """무슨 산책을 고르나. `tags` 는 전부 만족해야 한다(AND)."""

    tags: tuple[tuple[str, str], ...] = ()
    since: date | None = None
    until: date | None = None

    @classmethod
    def of(cls, since: date | None = None, until: date | None = None, **tags) -> "Selector":
        return cls(tags=tuple(sorted(tags.items())), since=since, until=until)

    def matches(self, started_at: datetime) -> bool:
        if self.since and started_at.date() < self.since:
            return False
        if self.until and started_at.date() > self.until:
            return False
        derived = derive_tags(started_at)
        return all(derived.get(key) == value for key, value in self.tags)

    @property
    def label(self) -> str:
        parts = [f"{k}={v}" for k, v in self.tags]
        if self.since or self.until:
            parts.append(f"{self.since or '…'}~{self.until or '…'}")
        return " ∩ ".join(parts) or "전체"


@dataclass(frozen=True)
class Aggregation:
    """어떻게 합치나.

    `min_peak` 은 **기본 0** 이다. 등급 문턱은 데이터가 생긴 뒤 정하기로 해 놓고 selection
    단계에서 문턱을 하나 박으면 자기모순이다. 노브는 남기되 실험은 0 으로 돈다.
    """

    metric: str = "walks"               # walks | occupancy | peak
    min_peak: float = 0.0


@dataclass(frozen=True)
class Projection:
    """어떻게 공간에 놓나. `radius_u` 는 격자 **단위**다 (`cells.py`).

    `profile_fp` 가 붓의 실제 세대다 — 이름(`brush`)은 사람이 읽는 것이고 동일성은 지문이
    정한다(`paint.BrushProfile.fingerprint`). 지문이 spec 에 없으면 `LayerSpec.fingerprint()`
    가 곡선 변경을 못 잡아서, 화면에 띄운 spec 지문만 보고는 어느 세대의 붓이었는지 알 수 없다.
    """

    radius_u: float
    brush: str
    profile_fp: str
    grid_version: str = GRID_VERSION


@dataclass(frozen=True)
class LayerSpec:
    selector: Selector
    aggregation: Aggregation
    projection: Projection
    spec_version: int = LAYER_SPEC_VERSION

    def fingerprint(self) -> str:
        """같은 spec 은 같은 지문. 재현성 확인과 캐시 키에 쓴다."""
        blob = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    @property
    def label(self) -> str:
        return (f"{self.selector.label} · {self.aggregation.metric} · "
                f"{self.projection.brush}({self.projection.profile_fp[:6]})"
                f"@{self.projection.radius_u:.0f}u")


@dataclass(frozen=True)
class Layer:
    """질의 결과. **spec 과 분모를 늘 달고 다닌다.**"""

    spec: LayerSpec
    canvas: dict[Cell, Paint]
    selected: int
    total: int
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def support(self) -> set[Cell]:
        return set(self.canvas)


def select(sheets: Iterable[Cellophane], spec: LayerSpec) -> list[Cellophane]:
    """조건에 맞는 장만. 장의 격자·붓이 spec 과 다르면 **섞지 않는다.**

    다른 격자의 장을 겹치면 조용히 틀린 그림이 나온다 — 셀 id 가 같은 자리를 뜻하지 않는다.
    격자는 `grid_version` 까지 본다: radius 와 붓 이름이 같아도 격자 수학이 바뀌었으면
    (q, r) 이 다른 자리다.

    붓은 **지문으로** 고른다. spec 이 세대를 명시하므로 이름이 같고 곡선이 다른 장은 그냥
    다른 장이다. 다만 이름은 맞는데 그 세대가 하나도 없으면 **조용히 빈 지도를 주지 않고
    에러다** — 데이터가 다른 세대뿐이라는 사실을 호출자가 알아야 한다.
    """
    named = [
        sheet for sheet in sheets
        if sheet.radius_u == spec.projection.radius_u
        and sheet.grid_version == spec.projection.grid_version
        and sheet.profile == spec.projection.brush
    ]
    same_curve = [s for s in named if s.profile_fp == spec.projection.profile_fp]
    if named and not same_curve:
        raise ValueError(
            f"붓 '{spec.projection.brush}' 의 지문 {spec.projection.profile_fp} 인 장이 없다. "
            f"있는 지문: {sorted({s.profile_fp for s in named})} — 같은 이름으로 감쇠를 바꾼 "
            f"장만 남아 있다"
        )
    return [sheet for sheet in same_curve if spec.selector.matches(sheet.at)]


def render(sheets: Iterable[Cellophane], spec: LayerSpec, note: str = "") -> Layer:
    """spec 하나 → 지도 한 장. 이 함수 밖에서 canvas 를 만들지 않는다."""
    pool = list(sheets)
    chosen = select(pool, spec)
    canvas = stack(chosen, min_peak=spec.aggregation.min_peak)
    return Layer(spec=spec, canvas=canvas, selected=len(chosen), total=len(pool), note=note)


# ---- 값 연산 -------------------------------------------------------------------------


def rate_field(layer: Layer) -> dict[Cell, float]:
    """칸마다 '고른 산책 중 몇 %가 여기를 칠했나'. 분모가 다른 두 층을 견주는 유일한 방법."""
    if not layer.selected:
        return {}
    return {cell: paint.walks / layer.selected for cell, paint in layer.canvas.items()}


def value_field(layer: Layer) -> dict[Cell, float]:
    """`aggregation.metric` 이 고른 값. `walks` 는 비율로 낸다 — 분모를 흘리지 않으려고."""
    metric = layer.spec.aggregation.metric
    if metric == "walks":
        return rate_field(layer)
    return {cell: getattr(paint, metric) for cell, paint in layer.canvas.items()}


def rate_diff(a: Layer, b: Layer) -> dict[Cell, float]:
    """visit_rate(A) − visit_rate(B). 양수면 A 쪽이 우세한 칸이다.

    이름이 `diff` 가 아닌 이유: 이것은 **방문률의 차**이지 일반 값의 차가 아니다.
    occupancy(체류 시간)와 peak(최대 근접도)는 단위가 달라 같은 빼기로 일반화되는 값이
    아니고, 그걸 하나의 `diff` 로 감추면 metric 을 무시하는 함수가 일반 연산인 척 하게 된다.

    존재 연산(`a.support - b.support`)과 다르다 — 여름 90% · 겨울 10% 인 칸은 존재로는
    양쪽에 다 있어 사라지지만 여기서는 +0.8 로 남는다.
    """
    fa, fb = rate_field(a), rate_field(b)
    return {cell: fa.get(cell, 0.0) - fb.get(cell, 0.0) for cell in set(fa) | set(fb)}


def normalized_distance(a: Layer, b: Layer) -> float:
    """정규화 L1 거리 — 두 방문률 분포를 각각 합 1 로 만든 뒤 |차| 를 **합산**한다.

    평균이 아니라 합이다. 0 = 동일, 2 = 완전히 분리(겹치는 칸이 하나도 없음).
    "거의 같다" 를 눈으로 판정하지 않으려고 둔다(A 페르소나 검증).
    복잡한 통계는 안 쓴다 — 나중에 그 통계 자체를 설명해야 한다.
    """
    fa, fb = rate_field(a), rate_field(b)
    sa, sb = sum(fa.values()), sum(fb.values())
    if not sa or not sb:
        return 1.0 if (sa or sb) else 0.0
    cells = set(fa) | set(fb)
    return sum(abs(fa.get(c, 0.0) / sa - fb.get(c, 0.0) / sb) for c in cells)


def mass_in(field_values: dict[Cell, float], region: set[Cell], positive_only: bool = True) -> float:
    """값의 총량 중 `region` 안에 든 비율. 평가기가 회수율을 잴 때 쓴다."""
    items = field_values.items()
    if positive_only:
        items = [(c, v) for c, v in items if v > 0]
    total = sum(v for _, v in items)
    if not total:
        return 0.0
    return sum(v for c, v in items if c in region) / total
