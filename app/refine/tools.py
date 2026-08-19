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


# --------------------------------------------------------------- JOURNEY (판정)
def set_mode(state: SearchState, mode: str | None) -> SearchState:
    s = _push(state); s.journey.mode = mode  # type: ignore[assignment]
    if mode in ("walk", "car", "transit") and s.sort == "distance":
        s.sort = "duration"
    return s


def set_walk_option(state: SearchState, option: str) -> SearchState:
    s = _push(state); s.journey.walk.option = option  # type: ignore[assignment]
    if s.journey.mode is None: s.journey.mode = "walk"
    return s


def set_max_min(state: SearchState, minutes: int | None, hard: bool | None = None) -> SearchState:
    """소요시간 상한. hard=True일 때만 결과에서 제외 (정책 경계를 넘는 유일한 지점)."""
    s = _push(state); s.journey.max_min = minutes
    if hard is not None: s.journey.hard_limit = hard
    if minutes is not None and s.journey.mode is None: s.journey.mode = "walk"
    return s


def avoid(state: SearchState, facilities: list[str]) -> SearchState:
    s = _push(state)
    s.journey.walk.avoid = sorted(set(s.journey.walk.avoid) | set(facilities))  # type: ignore[arg-type]
    if "stairs" in s.journey.walk.avoid: s.journey.walk.option = "no_stairs"
    if s.journey.mode is None: s.journey.mode = "walk"
    return s


def unavoid(state: SearchState, facilities: list[str]) -> SearchState:
    s = _push(state)
    s.journey.walk.avoid = [f for f in s.journey.walk.avoid if f not in facilities]
    if "stairs" in facilities and s.journey.walk.option == "no_stairs":
        s.journey.walk.option = "recommended"
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
JOURNEY_TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_mode": set_mode, "set_walk_option": set_walk_option, "set_max_min": set_max_min,
    "avoid": avoid, "unavoid": unavoid,
}
VIEW_TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_sort": set_sort, "undo": undo, "reset": reset,
}
TOOLS: dict[str, Callable[..., SearchState]] = {**TARGET_TOOLS, **JOURNEY_TOOLS, **VIEW_TOOLS}


def policy_of(tool: str) -> str:
    if tool in TARGET_TOOLS: return "target"
    if tool in JOURNEY_TOOLS: return "journey"
    if tool in VIEW_TOOLS: return "view"
    return "unknown"


# LLM에 주는 툴 설명. policy를 같이 줘서 모델도 두 정책을 구분하게 한다.
TOOL_SPECS: list[dict[str, Any]] = [
    {"policy": "target", "name": "set_origin", "desc": "검색 기준 좌표 변경 (집 근처 등)", "args": {"lat": "float", "lng": "float"}},
    {"policy": "target", "name": "set_radius", "desc": "검색 반경(m)", "args": {"m": "int"}},
    {"policy": "target", "name": "widen", "desc": "반경 넓히기(기본 2배)", "args": {"factor": "float?"}},
    {"policy": "target", "name": "narrow", "desc": "반경 좁히기(기본 절반)", "args": {"factor": "float?"}},
    {"policy": "target", "name": "set_time", "desc": "지금 영업중/야간/응급 필터", "args": {"open_now": "bool?", "night": "bool?", "emergency": "bool?"}},
    {"policy": "target", "name": "set_specialty", "desc": "진료 특화 (ortho, eye, dental, derma, cardio, rehab)", "args": {"tags": "list[str]"}},
    {"policy": "target", "name": "require", "desc": "필수 태그 (24h, center, secondary, surgery)", "args": {"tags": "list[str]"}},
    {"policy": "target", "name": "unrequire", "desc": "필수 태그 해제", "args": {"tags": "list[str]"}},
    {"policy": "target", "name": "exclude", "desc": "결과에서 제외할 병원 id (화면 순번→id는 shown_ids로 매핑)", "args": {"ids": "list[int]"}},
    {"policy": "target", "name": "pin", "desc": "위로 고정할 병원 id", "args": {"ids": "list[int]"}},
    {"policy": "journey", "name": "set_mode", "desc": "이동수단 walk|car|transit|null", "args": {"mode": "str?"}},
    {"policy": "journey", "name": "set_walk_option", "desc": "도보 옵션 recommended|main_road|shortest|no_stairs", "args": {"option": "str"}},
    {"policy": "journey", "name": "set_max_min", "desc": "소요시간 상한(분). hard=true면 초과를 결과에서 뺀다(기본 false: 표시만)", "args": {"minutes": "int?", "hard": "bool?"}},
    {"policy": "journey", "name": "avoid", "desc": "도보 시 피할 시설 stairs|underpass|overpass", "args": {"facilities": "list[str]"}},
    {"policy": "journey", "name": "unavoid", "desc": "피하기 해제", "args": {"facilities": "list[str]"}},
    {"policy": "view", "name": "set_sort", "desc": "정렬 distance|duration|open_first", "args": {"sort": "str"}},
    {"policy": "view", "name": "undo", "desc": "직전 상태로", "args": {}},
    {"policy": "view", "name": "reset", "desc": "필터 초기화", "args": {}},
    {"policy": "view", "name": "ask", "desc": "의도가 불명확할 때 되묻기. 상태 변경 없음", "args": {"question": "str"}},
]


def apply(state: SearchState, tool: str, args: dict[str, Any] | None = None) -> SearchState:
    fn = TOOLS.get(tool)
    if fn is None:
        raise KeyError(f"unknown tool: {tool}")
    return fn(state, **(args or {}))
