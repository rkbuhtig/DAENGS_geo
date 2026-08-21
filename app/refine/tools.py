"""상태 편집 툴. 순수 함수 (state, args) → state. UI도 LLM도 이걸 부른다.

**툴은 정책별로 묶여 있다** (state.py 참조):
  TARGET_TOOLS  — 어디를 갈까. 결과 집합을 바꾼다
  JOURNEY_TOOLS — 어떻게 갈까. 결과를 빼지 않는다
  VIEW_TOOLS    — 표시·세션 (정렬, undo, reset)

새 툴을 만들면 셋 중 하나에 넣어라. 어디에도 안 들어가면 정책이 불분명한 것이다.
'min_rating' 같은 툴은 의도적으로 없다 (condition-schema.md).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.planning.semantics import TimeIntent
from app.planning.state import EditableState

MAX_HISTORY = 10


def _push(state: EditableState) -> EditableState:
    s = state.model_copy(deep=True)
    s.history = (s.history + [state.snapshot()])[-MAX_HISTORY:]
    return s


# ---------------------------------------------------------------- TARGET (필터)
def set_origin(state: EditableState, lat: float, lng: float) -> EditableState:
    s = _push(state); s.lat, s.lng = lat, lng; return s


def set_radius(state: EditableState, m: int) -> EditableState:
    s = _push(state); s.target.radius_m = max(100, min(20000, int(m))); return s


def widen(state: EditableState, factor: float = 2.0) -> EditableState:
    return set_radius(state, int(state.target.radius_m * factor))


def narrow(state: EditableState, factor: float = 0.5) -> EditableState:
    return set_radius(state, int(state.target.radius_m * factor))


# `set_time(open_now, night, emergency)` 하나였다. 셋은 같은 종류가 아니다 —
# 영업 여부는 검색 조건, 야간·응급은 병원의 표방, 긴급도는 이번 상황의 사실이다.
# 한 툴에 묶어두니 정책 라벨이 하나뿐이라 '응급'이 target 변경으로만 보고됐다.
def set_open_now(state: EditableState, on: bool = True) -> EditableState:
    s = _push(state); s.target.open_now = on; return s


def set_night_service(state: EditableState, on: bool = True) -> EditableState:
    """야간진료를 **표방하는** 곳만. 지금이 밤이냐는 `set_time_intent` 다."""
    s = _push(state); s.target.night_service = on; return s


def set_emergency_service(state: EditableState, on: bool = True) -> EditableState:
    """응급을 **표방하는** 곳만. 이번 상황이 급하냐는 `set_urgency` 다."""
    s = _push(state); s.target.emergency_service = on; return s


def set_specialty(state: EditableState, tags: list[str]) -> EditableState:
    s = _push(state); s.target.specialty = sorted(set(tags)); return s


def note_symptoms(state: EditableState, terms: list[str]) -> EditableState:
    """증상 표현을 **말 그대로** 남긴다. 커뮤니티 검색 쿼리 재료 — 과목 번역이 아니다."""
    s = _push(state); s.target.symptoms = sorted(set(s.target.symptoms) | set(terms)); return s


def clear_symptoms(state: EditableState, terms: list[str] | None = None) -> EditableState:
    s = _push(state)
    s.target.symptoms = [] if terms is None else [t for t in s.target.symptoms if t not in terms]
    return s


def require(state: EditableState, tags: list[str]) -> EditableState:
    s = _push(state); s.target.require_tags = sorted(set(s.target.require_tags) | set(tags)); return s


def unrequire(state: EditableState, tags: list[str]) -> EditableState:
    s = _push(state); s.target.require_tags = [t for t in s.target.require_tags if t not in tags]; return s


def exclude(state: EditableState, ids: list[int]) -> EditableState:
    s = _push(state); s.target.exclude_ids = sorted(set(s.target.exclude_ids) | set(ids)); return s


def pin(state: EditableState, ids: list[int]) -> EditableState:
    s = _push(state); s.target.pin_ids = sorted(set(s.target.pin_ids) | set(ids)); return s


# ------------------------------------------------------- CONTEXT (상황 — 사실)
# 여기 값들은 target 과 journey **둘 다**를 먹인다. 그래서 어느 한쪽 상자에 못 들어간다.
def set_urgency(state: EditableState, level: str) -> EditableState:
    """이번 상황의 긴급도. **사용자가 말한 것만** 여기 들어온다.

    긴급도는 조건을 좁히지 않는다 — 수단 우선순위·정렬·안내 문구를 바꿀 뿐이다.
    '응급 병원을 찾겠다'는 요구는 `set_emergency_service` 로 따로 간다.
    """
    if level not in ("normal", "urgent"):
        raise ValueError(f"unknown urgency: {level}")   # 나머지 툴의 같은 구멍은 검증 관문에서 (step 2 ②)
    s = _push(state); s.urgency = level  # type: ignore[assignment]
    return s


def set_time_intent(state: EditableState, kind: str | None = None,
                    at: datetime | None = None) -> EditableState:
    """시각과 그 **뜻**. kind 없이 부르면 해제 (= 지금)."""
    s = _push(state)
    s.time_intent = TimeIntent(kind=kind, at=at) if (kind and at) else None  # type: ignore[arg-type]
    return s


# ------------------------------------------------- JOURNEY / 수단 (scope: any)
def set_mode(state: EditableState, mode: str | None) -> EditableState:
    """어느 leg 를 앞에 놓을지의 선호. Transport 는 늘 셋 다 반환한다."""
    s = _push(state); s.journey.preferred_mode = mode  # type: ignore[assignment]
    if mode in ("walk", "car", "transit") and s.sort == "distance":
        s.sort = "duration"
    return s


def set_max_total_min(state: EditableState, minutes: int | None,
                      hard: bool | None = None) -> EditableState:
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
def set_walk_option(state: EditableState, option: str) -> EditableState:
    s = _push(state); s.journey.walk.option = option  # type: ignore[assignment]
    return s


def set_walk_avoid(state: EditableState, facilities: list[str]) -> EditableState:
    s = _push(state)
    s.journey.walk.avoid = sorted(set(s.journey.walk.avoid) | set(facilities))  # type: ignore[arg-type]
    # option 도 도보 scope 안이라 같이 움직여도 된다 (계층을 넘지 않는다)
    if "stairs" in s.journey.walk.avoid: s.journey.walk.option = "no_stairs"
    return s


def unset_walk_avoid(state: EditableState, facilities: list[str]) -> EditableState:
    s = _push(state)
    s.journey.walk.avoid = [f for f in s.journey.walk.avoid if f not in facilities]
    if "stairs" in facilities and s.journey.walk.option == "no_stairs":
        s.journey.walk.option = "recommended"
    return s


def set_walk_max_min(state: EditableState, minutes: int | None) -> EditableState:
    """**개가 걸어도 되는 시간** 상한. 전체 이동시간(`set_max_total_min`)과 다르다."""
    s = _push(state); s.journey.walk.max_walk_min = minutes
    return s


# ------------------------------------------------------------------ VIEW (표시)
def set_sort(state: EditableState, sort: str) -> EditableState:
    s = _push(state); s.sort = sort  # type: ignore[assignment]
    return s


def undo(state: EditableState) -> EditableState:
    if not state.history:
        return state
    prev = EditableState(**state.history[-1])
    prev.history = state.history[:-1]
    return prev


def reset(state: EditableState) -> EditableState:
    """**필터 초기화.** 상황(context)은 남긴다 — 사실은 초기화의 대상이 아니다.

    지금이 밤이고 급한 건 필터를 푼다고 달라지지 않는다. 지우려면 각각 따로 부른다.
    """
    s = _push(state)
    return EditableState(lat=s.lat, lng=s.lng, history=s.history,
                       time_intent=s.time_intent, urgency=s.urgency)


TARGET_TOOLS: dict[str, Callable[..., EditableState]] = {
    "set_origin": set_origin, "set_radius": set_radius, "widen": widen, "narrow": narrow,
    "set_open_now": set_open_now, "set_night_service": set_night_service,
    "set_emergency_service": set_emergency_service,
    "set_specialty": set_specialty, "note_symptoms": note_symptoms, "clear_symptoms": clear_symptoms,
    "require": require, "unrequire": unrequire,
    "exclude": exclude, "pin": pin,
}
# 상황은 정책이 아니라 **두 정책의 입력**이다. 그래서 네 번째 그룹이 된다.
CONTEXT_TOOLS: dict[str, Callable[..., EditableState]] = {
    "set_urgency": set_urgency, "set_time_intent": set_time_intent,
}
# 수단 선택은 scope="any", 수단별 설정은 그 수단 scope. 계층이 다르다.
MODE_TOOLS: dict[str, Callable[..., EditableState]] = {
    "set_mode": set_mode, "set_max_total_min": set_max_total_min,
}
WALK_TOOLS: dict[str, Callable[..., EditableState]] = {
    "set_walk_option": set_walk_option, "set_walk_avoid": set_walk_avoid,
    "unset_walk_avoid": unset_walk_avoid, "set_walk_max_min": set_walk_max_min,
}
JOURNEY_TOOLS: dict[str, Callable[..., EditableState]] = {**MODE_TOOLS, **WALK_TOOLS}
VIEW_TOOLS: dict[str, Callable[..., EditableState]] = {
    "set_sort": set_sort, "undo": undo, "reset": reset,
}
TOOLS: dict[str, Callable[..., EditableState]] = {
    **CONTEXT_TOOLS, **TARGET_TOOLS, **JOURNEY_TOOLS, **VIEW_TOOLS,
}


def policy_of(tool: str) -> str:
    if tool in CONTEXT_TOOLS: return "context"
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
    {"policy": "target", "scope": "any", "name": "set_open_now", "desc": "지금 영업중인 곳만", "args": {"on": "bool?"}},
    {"policy": "target", "scope": "any", "name": "set_night_service", "desc": "야간진료를 표방하는 곳만. '지금이 밤이다'가 아니다", "args": {"on": "bool?"}},
    {"policy": "target", "scope": "any", "name": "set_emergency_service", "desc": "응급을 표방하는 곳만. '지금 급하다'가 아니다", "args": {"on": "bool?"}},
    {"policy": "context", "scope": "any", "name": "set_urgency", "desc": "이번 상황의 긴급도 normal|urgent. 조건을 좁히지 않는다 — 병원 종류 요구는 set_emergency_service", "args": {"level": "str"}},
    {"policy": "context", "scope": "any", "name": "set_time_intent", "desc": "시각과 그 뜻. kind=depart_at(출발)|arrive_by(도착기한)|service_at(그 시각에 여는 병원)", "args": {"kind": "str?", "at": "str?"}},
    {"policy": "target", "scope": "any", "name": "set_specialty", "desc": "진료 특화 선호 (ortho, eye, dental, derma, cardio, rehab). 사용자가 과목을 직접 말했을 때만", "args": {"tags": "list[str]"}},
    {"policy": "target", "scope": "any", "name": "note_symptoms", "desc": "증상 표현을 말 그대로 기록 (진단 금지, 과목 번역 금지). 커뮤니티 검색 재료", "args": {"terms": "list[str]"}},
    {"policy": "target", "scope": "any", "name": "clear_symptoms", "desc": "증상 기록 해제. terms 없으면 전부", "args": {"terms": "list[str]?"}},
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


def apply(state: EditableState, tool: str, args: dict[str, Any] | None = None) -> EditableState:
    fn = TOOLS.get(tool)
    if fn is None:
        raise KeyError(f"unknown tool: {tool}")
    return fn(state, **(args or {}))
