"""엔진별 **실행 계획**. resolver 가 만들고, 엔진은 자기 계획만 받는다.

    find_places(plan.search)      검색은 journey 를 볼 방법이 없다
    snapshot(plan.journey)        경로는 target 을 볼 방법이 없다
    render(plan.view)

계획을 따로 두는 이유는 경계를 **구조로** 막기 위해서다. 조각을 여러 개 넘기면
(`find_places(target, derived)`) 결국 누군가 필요한 걸 하나 더 끌어다 쓰고, 그렇게
검색·경로·정렬이 각자 state·body·서버 시각·발화를 주워 먹으며 어긋났다.

**계획은 재료지 판정이 아니다.** '응급이니 차로 간다'를 여기서 확정하지 않는다 —
수단 우선순위와 억제 플래그까지만 싣고, 무엇을 고를지는 엔진이 정한다. 애초에 시설·경사는
경로를 받아봐야 아는 값이라 resolver 가 미리 판정할 수도 없다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.planning.state import Sort, WalkFacility
from app.profile.contract import DogProfile
from app.providers.base import Mode, WalkOption

Companion = str  # journey.models.Companion 과 같은 값. 순환 import 를 피한다


# ------------------------------------------------------------------ 검색
@dataclass(frozen=True)
class SearchMust:
    """만족하지 못하면 **결과에서 빠진다.** 사용자가 명시한 요구만 여기 온다."""

    lat: float
    lng: float
    radius_m: int
    judge_at: datetime                         # 영업 판정 시각 (TimeIntent.service_at 사영)
    kind: str | None = None
    open_now: bool = False
    require_tags: tuple[str, ...] = field(default_factory=tuple)
    exclude_ids: tuple[int, ...] = field(default_factory=tuple)
    limit: int = 20


@dataclass(frozen=True)
class SearchPrefer:
    """**빼지 않는다. 순위만 올린다.**

    특화·야간·응급이 한 자리에 있는 건 셋 다 재료가 같기 때문이다 — 간판 이름 정규식
    (`geo/tagging.py`). 실측 2026-08-20 활성 병원 5,457곳 중 night 1 · emergency 2 ·
    ortho 2. 신뢰도가 같으니 권한도 같아야 하고, 이 신뢰도로는 거를 자격이 없다.
    """

    tags: tuple[str, ...] = field(default_factory=tuple)
    confidence: str = "name_regex"       # 어디서 온 신호인지. 표시·감사용


@dataclass(frozen=True)
class SearchPlan:
    must: SearchMust
    prefer: SearchPrefer = field(default_factory=SearchPrefer)


# ------------------------------------------------------------------ 이동
@dataclass(frozen=True)
class WalkPlan:
    """도보로 갈 때만 의미 있는 것. 차량 판정에 적용되면 안 된다."""

    option: WalkOption = "recommended"
    avoid: tuple[WalkFacility, ...] = field(default_factory=tuple)
    max_walk_min: int | None = None      # **개가 걸어도 되는 시간.** 전체 이동시간과 다르다


@dataclass(frozen=True)
class JourneyPlan:
    """어떻게 갈까. 판정에 필요한 **재료와 우선순위**까지만.

    `mode_priority` 가 '선호 수단' 하나가 아닌 이유: 급할 때 차가 없으면 택시, 그것도
    아니면 도보다. 무엇이 실제로 가능한지는 경로를 받아봐야 알기 때문에 순서만 준다.
    """

    origin_lat: float
    origin_lng: float
    resolved_at: datetime
    departure_at: datetime
    companion: Companion = "dog"
    measured: bool = False

    # --- resolver 가 정한 시각. **엔진은 datetime.now() 를 부르지 않는다**
    travel_is_night: bool = False

    mode_priority: tuple[Mode, ...] = field(default_factory=tuple)
    max_total_min: int | None = None
    hard_limit: bool = False
    walk: WalkPlan = field(default_factory=WalkPlan)

    # --- 상황이 먹인 것
    profile: DogProfile | None = None
    temp_c: float | None = None


# ------------------------------------------------------------------ 표시
@dataclass(frozen=True)
class ViewPlan:
    """어떻게 보여줄까. 결과 집합도 경로도 안 바꾼다."""

    sort: Sort = "distance"
    pin_ids: tuple[int, ...] = field(default_factory=tuple)
    show_call_cta: bool = False     # 안전 표면 — 긴급도가 높으면 조건을 좁히는 대신 전화를 권한다
    call_reasons: tuple[str, ...] = field(default_factory=tuple)
