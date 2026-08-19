"""상태 편집 툴. 순수 함수 (state, args) → state. UI도 LLM도 이걸 부른다.

새 툴 = 함수 하나 + TOOLS 등록. LLM에 주는 스키마도 여기서 나온다.
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


def set_origin(state: SearchState, lat: float, lng: float) -> SearchState:
    s = _push(state); s.lat, s.lng = lat, lng; return s


def set_radius(state: SearchState, m: int) -> SearchState:
    s = _push(state); s.radius_m = max(100, min(20000, int(m))); return s


def widen(state: SearchState, factor: float = 2.0) -> SearchState:
    return set_radius(state, int(state.radius_m * factor))


def narrow(state: SearchState, factor: float = 0.5) -> SearchState:
    return set_radius(state, int(state.radius_m * factor))


def set_time(state: SearchState, open_now: bool | None = None, night: bool | None = None,
             emergency: bool | None = None) -> SearchState:
    s = _push(state)
    if open_now is not None: s.open_now = open_now
    if night is not None: s.night = night
    if emergency is not None: s.emergency = emergency
    return s


def set_specialty(state: SearchState, tags: list[str]) -> SearchState:
    s = _push(state); s.specialty = sorted(set(tags)); return s


def require(state: SearchState, tags: list[str]) -> SearchState:
    s = _push(state); s.require_tags = sorted(set(s.require_tags) | set(tags)); return s


def unrequire(state: SearchState, tags: list[str]) -> SearchState:
    s = _push(state); s.require_tags = [t for t in s.require_tags if t not in tags]; return s


def set_mode(state: SearchState, mode: str | None) -> SearchState:
    s = _push(state); s.mode = mode  # type: ignore[assignment]
    if mode in ("walk", "car", "transit") and s.sort == "distance":
        s.sort = "duration"
    return s


def set_walk_option(state: SearchState, option: str) -> SearchState:
    s = _push(state); s.walk.option = option  # type: ignore[assignment]
    if s.mode is None: s.mode = "walk"
    return s


def set_walk_max(state: SearchState, minutes: int | None) -> SearchState:
    s = _push(state); s.walk.max_min = minutes
    if s.mode is None: s.mode = "walk"
    return s


def avoid(state: SearchState, facilities: list[str]) -> SearchState:
    s = _push(state)
    s.walk.avoid = sorted(set(s.walk.avoid) | set(facilities))  # type: ignore[arg-type]
    if "stairs" in s.walk.avoid: s.walk.option = "no_stairs"
    if s.mode is None: s.mode = "walk"
    return s


def exclude(state: SearchState, ids: list[int]) -> SearchState:
    s = _push(state); s.exclude_ids = sorted(set(s.exclude_ids) | set(ids)); return s


def pin(state: SearchState, ids: list[int]) -> SearchState:
    s = _push(state); s.pin_ids = sorted(set(s.pin_ids) | set(ids)); return s


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


TOOLS: dict[str, Callable[..., SearchState]] = {
    "set_origin": set_origin, "set_radius": set_radius, "widen": widen, "narrow": narrow,
    "set_time": set_time, "set_specialty": set_specialty, "require": require, "unrequire": unrequire,
    "set_mode": set_mode, "set_walk_option": set_walk_option, "set_walk_max": set_walk_max,
    "avoid": avoid, "exclude": exclude, "pin": pin, "set_sort": set_sort, "undo": undo, "reset": reset,
}

# LLM에 주는 툴 설명 (OpenAI function schema로 변환 가능한 최소 형태)
TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "set_radius", "desc": "검색 반경(m) 설정", "args": {"m": "int"}},
    {"name": "widen", "desc": "반경 넓히기(기본 2배)", "args": {"factor": "float?"}},
    {"name": "narrow", "desc": "반경 좁히기(기본 절반)", "args": {"factor": "float?"}},
    {"name": "set_time", "desc": "지금 영업중/야간/응급 필터", "args": {"open_now": "bool?", "night": "bool?", "emergency": "bool?"}},
    {"name": "set_specialty", "desc": "진료 특화 태그 (ortho, eye, dental, derma, cardio, rehab)", "args": {"tags": "list[str]"}},
    {"name": "require", "desc": "필수 태그 (24h, center, secondary, surgery)", "args": {"tags": "list[str]"}},
    {"name": "set_mode", "desc": "이동수단 walk|car|transit|null", "args": {"mode": "str?"}},
    {"name": "set_walk_option", "desc": "도보 옵션 recommended|main_road|shortest|no_stairs", "args": {"option": "str"}},
    {"name": "set_walk_max", "desc": "도보 최대 분", "args": {"minutes": "int?"}},
    {"name": "avoid", "desc": "도보 시 피할 시설 stairs|underpass|overpass", "args": {"facilities": "list[str]"}},
    {"name": "exclude", "desc": "결과에서 제외할 병원 id (화면 순번→id는 shown_ids로 매핑)", "args": {"ids": "list[int]"}},
    {"name": "pin", "desc": "위로 고정할 병원 id", "args": {"ids": "list[int]"}},
    {"name": "set_sort", "desc": "정렬 distance|duration|open_first", "args": {"sort": "str"}},
    {"name": "undo", "desc": "직전 상태로", "args": {}},
    {"name": "reset", "desc": "필터 초기화", "args": {}},
    {"name": "ask", "desc": "의도가 불명확할 때 사용자에게 되묻기. 상태 변경 없음", "args": {"question": "str"}},
]


def apply(state: SearchState, tool: str, args: dict[str, Any] | None = None) -> SearchState:
    fn = TOOLS.get(tool)
    if fn is None:
        raise KeyError(f"unknown tool: {tool}")
    return fn(state, **(args or {}))
