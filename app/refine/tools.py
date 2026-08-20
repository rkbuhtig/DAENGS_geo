"""상태 편집 툴. 순수 함수 (state, args) → state. UI도 LLM도 이걸 부른다.

**툴은 정책별로 묶여 있다** (state.py 참조):
  TARGET_TOOLS  — 어디를 갈까. 결과 집합을 바꾼다
  JOURNEY_TOOLS — 어떻게 갈까. 결과를 빼지 않는다
  VIEW_TOOLS    — 표시·세션 (정렬, undo, reset)

새 툴을 만들면 셋 중 하나에 넣어라. 어디에도 안 들어가면 정책이 불분명한 것이다.
'min_rating' 같은 툴은 의도적으로 없다 (condition-schema.md).
"""

from collections.abc import Callable
from typing import Any

from app.refine.state import SearchState

MAX_HISTORY = 10


def _push(state: SearchState) -> SearchState:
    s = state.model_copy(deep=True)
    s.history = (s.history + [state.snapshot()])[-MAX_HISTORY:]
    return s


# ---------------------------------------------------------------- TARGET (필터)
def set_origin(state: SearchState, lat: float, lng: float) -> SearchState:
    s = _push(state); s.lat, s.lng = lat, lng; return s


def set_radius(state: SearchState, m: int) -> SearchState:
    s = _push(state); s.target.radius_m = max(100, min(20000, int(m))); return s


def widen(state: SearchState, factor: float = 2.0) -> SearchState:
    return set_radius(state, int(state.target.radius_m * factor))


def narrow(state: SearchState, factor: float = 0.5) -> SearchState:
    return set_radius(state, int(state.target.radius_m * factor))


def set_time(state: SearchState, open_now: bool | None = None, night: bool | None = None,
             emergency: bool | None = None) -> SearchState:
    s = _push(state)
    if open_now is not None: s.target.open_now = open_now
    if night is not None: s.target.night = night
    if emergency is not None: s.target.emergency = emergency
    return s


def set_specialty(state: SearchState, tags: list[str]) -> SearchState:
    s = _push(state); s.target.specialty = sorted(set(tags)); return s


def require(state: SearchState, tags: list[str]) -> SearchState:
    s = _push(state); s.target.require_tags = sorted(set(s.target.require_tags) | set(tags)); return s


def unrequire(state: SearchState, tags: list[str]) -> SearchState:
    s = _push(state); s.target.require_tags = [t for t in s.target.require_tags if t not in tags]; return s


def exclude(state: SearchState, ids: list[int]) -> SearchState:
    s = _push(state); s.target.exclude_ids = sorted(set(s.target.exclude_ids) | set(ids)); return s


def pin(state: SearchState, ids: list[int]) -> SearchState:
    s = _push(state); s.target.pin_ids = sorted(set(s.target.pin_ids) | set(ids)); return s


# ------------------------------------------------- JOURNEY / 수단 (scope: any)
def set_mode(state: SearchState, mode: str | None) -> SearchState:
    """어느 leg 를 앞에 놓을지의 선호. Transport 는 늘 셋 다 반환한다."""
    s = _push(state); s.journey.preferred_mode = mode  # type: ignore[assignment]
    if mode in ("walk", "car", "transit") and s.sort == "distance":
        s.sort = "duration"
    return s


def set_max_total_min(state: SearchState, minutes: int | None,
                      hard: bool | None = None) -> SearchState:
    """**전체 이동시간** 상한. 수단 무관 — 차든 도보든 같은 잣대다.

    개가 걸어도 되는 시간은 `set_walk_max_min` 이다. 둘을 한 값으로 쓰면
    '차로 10분'과 '노견 도보 10분'이 같은 뜻이 된다.
    hard=True 일 때만 결과에서 제외 (정책 경계를 넘는 유일한 지점).
    """
    s = _push(state); s.journey.max_total_min = minutes
    if hard is not None: s.journey.hard_limit = hard
    return s


# ------------------------------------------------ JOURNEY / 도보 (scope: walk)
# 이 그룹은 preferred_mode 를 건드리지 않는다. '계단 없는 길로'가 도보를 함의한다면
# 그건 자연어 층이 set_mode(walk) 를 **따로 내는** 것이지, 툴이 몰래 세울 일이 아니다.
def set_walk_option(state: SearchState, option: str) -> SearchState:
    s = _push(state); s.journey.walk.option = option  # type: ignore[assignment]
    return s


def set_walk_avoid(state: SearchState, facilities: list[str]) -> SearchState:
    s = _push(state)
    s.journey.walk.avoid = sorted(set(s.journey.walk.avoid) | set(facilities))  # type: ignore[arg-type]
    # option 도 도보 scope 안이라 같이 움직여도 된다 (계층을 넘지 않는다)
    if "stairs" in s.journey.walk.avoid: s.journey.walk.option = "no_stairs"
    return s


def unset_walk_avoid(state: SearchState, facilities: list[str]) -> SearchState:
    s = _push(state)
    s.journey.walk.avoid = [f for f in s.journey.walk.avoid if f not in facilities]
    if "stairs" in facilities and s.journey.walk.option == "no_stairs":
        s.journey.walk.option = "recommended"
    return s


def set_walk_max_min(state: SearchState, minutes: int | None) -> SearchState:
    """**개가 걸어도 되는 시간** 상한. 전체 이동시간(`set_max_total_min`)과 다르다."""
    s = _push(state); s.journey.walk.max_walk_min = minutes
    return s


# ------------------------------------------------------------------ VIEW (표시)
def set_sort(state: SearchState, sort: str) -> SearchState:
    s = _push(state); s.sort = sort  # type: ignore[assignment]
    return s


def undo(state: SearchState) -> SearchState:
    if not state.history:
        return state
    prev = SearchState(**state.history[-1])
    prev.history = state.history[:-1]
    return prev


def reset(state: SearchState) -> SearchState:
    s = _push(state)
    return SearchState(lat=s.lat, lng=s.lng, history=s.history)


TARGET_TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_origin": set_origin, "set_radius": set_radius, "widen": widen, "narrow": narrow,
    "set_time": set_time, "set_specialty": set_specialty, "require": require, "unrequire": unrequire,
    "exclude": exclude, "pin": pin,
}
# 수단 선택은 scope="any", 수단별 설정은 그 수단 scope. 계층이 다르다.
MODE_TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_mode": set_mode, "set_max_total_min": set_max_total_min,
}
WALK_TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_walk_option": set_walk_option, "set_walk_avoid": set_walk_avoid,
    "unset_walk_avoid": unset_walk_avoid, "set_walk_max_min": set_walk_max_min,
}
JOURNEY_TOOLS: dict[str, Callable[..., SearchState]] = {**MODE_TOOLS, **WALK_TOOLS}
VIEW_TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_sort": set_sort, "undo": undo, "reset": reset,
}
TOOLS: dict[str, Callable[..., SearchState]] = {**TARGET_TOOLS, **JOURNEY_TOOLS, **VIEW_TOOLS}


def policy_of(tool: str) -> str:
    if tool in TARGET_TOOLS: return "target"
    if tool in JOURNEY_TOOLS: return "journey"
    if tool in VIEW_TOOLS: return "view"
    return "unknown"


def scope_of(tool: str) -> str:
    """어느 수단에서만 의미가 있나. 정책(policy)과 **직교하는 축**이다.

    'any' = 수단 무관 (반경·정렬·전체 이동시간), 'walk' = 도보로 갈 때만.
    """
    return "walk" if tool in WALK_TOOLS else "any"


# LLM에 주는 툴 설명. policy(결과를 바꾸나)와 scope(어느 수단에서만 의미 있나)를 같이 준다.
TOOL_SPECS: list[dict[str, Any]] = [
    {"policy": "target", "scope": "any", "name": "set_origin", "desc": "검색 기준 좌표 변경 (집 근처 등)", "args": {"lat": "float", "lng": "float"}},
    {"policy": "target", "scope": "any", "name": "set_radius", "desc": "검색 반경(m)", "args": {"m": "int"}},
    {"policy": "target", "scope": "any", "name": "widen", "desc": "반경 넓히기(기본 2배)", "args": {"factor": "float?"}},
    {"policy": "target", "scope": "any", "name": "narrow", "desc": "반경 좁히기(기본 절반)", "args": {"factor": "float?"}},
    {"policy": "target", "scope": "any", "name": "set_time", "desc": "지금 영업중/야간/응급 필터", "args": {"open_now": "bool?", "night": "bool?", "emergency": "bool?"}},
    {"policy": "target", "scope": "any", "name": "set_specialty", "desc": "진료 특화 (ortho, eye, dental, derma, cardio, rehab)", "args": {"tags": "list[str]"}},
    {"policy": "target", "scope": "any", "name": "require", "desc": "필수 태그 (24h, center, secondary, surgery)", "args": {"tags": "list[str]"}},
    {"policy": "target", "scope": "any", "name": "unrequire", "desc": "필수 태그 해제", "args": {"tags": "list[str]"}},
    {"policy": "target", "scope": "any", "name": "exclude", "desc": "결과에서 제외할 병원 id (화면 순번→id는 shown_ids로 매핑)", "args": {"ids": "list[int]"}},
    {"policy": "target", "scope": "any", "name": "pin", "desc": "위로 고정할 병원 id", "args": {"ids": "list[int]"}},
    {"policy": "journey", "scope": "any", "name": "set_mode", "desc": "선호 이동수단 walk|car|transit|null. 도보 설정을 바꾸고 싶으면 이걸 따로 부를 것", "args": {"mode": "str?"}},
    {"policy": "journey", "scope": "any", "name": "set_max_total_min", "desc": "전체 이동시간 상한(분), 수단 무관. hard=true면 초과를 결과에서 뺀다(기본 false: 표시만)", "args": {"minutes": "int?", "hard": "bool?"}},
    {"policy": "journey", "scope": "walk", "name": "set_walk_option", "desc": "도보 옵션 recommended|main_road|shortest|no_stairs", "args": {"option": "str"}},
    {"policy": "journey", "scope": "walk", "name": "set_walk_avoid", "desc": "도보 시 피할 시설 stairs|underpass|overpass", "args": {"facilities": "list[str]"}},
    {"policy": "journey", "scope": "walk", "name": "unset_walk_avoid", "desc": "도보 피하기 해제", "args": {"facilities": "list[str]"}},
    {"policy": "journey", "scope": "walk", "name": "set_walk_max_min", "desc": "개가 걸어도 되는 시간 상한(분). 전체 이동시간과 다르다", "args": {"minutes": "int?"}},
    {"policy": "view", "scope": "any", "name": "set_sort", "desc": "정렬 distance|duration|open_first", "args": {"sort": "str"}},
    {"policy": "view", "scope": "any", "name": "undo", "desc": "직전 상태로", "args": {}},
    {"policy": "view", "scope": "any", "name": "reset", "desc": "필터 초기화", "args": {}},
    {"policy": "view", "scope": "any", "name": "ask", "desc": "의도가 불명확할 때 되묻기. 상태 변경 없음", "args": {"question": "str"}},
]


def apply(state: SearchState, tool: str, args: dict[str, Any] | None = None) -> SearchState:
    fn = TOOLS.get(tool)
    if fn is None:
        raise KeyError(f"unknown tool: {tool}")
    return fn(state, **(args or {}))
