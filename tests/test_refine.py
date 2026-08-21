from datetime import UTC, datetime

import pytest

from app.planning.state import EditableState
from app.profile.source import PERSONAS
from app.refine import tools
from app.refine.diff import changes
from app.refine.engine import draft, refine
from app.refine.nl import FakeLLM, ToolCall

S = EditableState(lat=37.4979, lng=127.0276)


def test_tools_are_pure_and_push_history():
    s2 = tools.narrow(S)
    assert S.target.radius_m == 2000 and s2.target.radius_m == 1000
    assert len(s2.history) == 1
    s3 = tools.undo(s2)
    assert s3.target.radius_m == 2000 and s3.history == []


def test_undo_on_empty_is_noop():
    assert tools.undo(S) is S


def test_walk_avoid_stays_inside_walk_scope():
    """도보 툴은 option 까지만 건드린다. **수단(preferred_mode)은 절대 안 세운다.**"""
    s = tools.set_walk_avoid(S, ["stairs"])
    assert s.journey.walk.option == "no_stairs"
    assert s.journey.preferred_mode is None, "하위 설정이 상위(수단)를 몰래 세웠다"
    assert tools.unset_walk_avoid(s, ["stairs"]).journey.walk.option == "recommended"


def test_walk_settings_survive_switching_to_car():
    """차량으로 바꿔도 도보 설정은 남는다 — 도보 대안에 계속 쓰이고, 돌아오면 살아 있어야 한다."""
    s = tools.set_walk_avoid(S, ["stairs"])
    s = tools.set_mode(s, "car")
    assert s.journey.preferred_mode == "car"
    assert s.journey.walk.avoid == ["stairs"] and s.journey.walk.option == "no_stairs"


def test_total_and_walk_time_limits_are_separate():
    """'차로 10분'과 '노견 도보 10분'은 다른 값이다."""
    s = tools.set_max_total_min(S, 30)
    s = tools.set_walk_max_min(s, 10)
    assert s.journey.max_total_min == 30 and s.journey.walk.max_walk_min == 10
    assert tools.set_max_total_min(s, 45).journey.walk.max_walk_min == 10


def test_time_limit_does_not_imply_a_mode():
    """'15분 안에'는 수단을 함의하지 않는다 — 차로 갈 수도 있다."""
    assert tools.set_max_total_min(S, 15).journey.preferred_mode is None


def test_set_mode_switches_sort_to_duration():
    assert tools.set_mode(S, "car").sort == "duration"


def test_diff_lists_every_change():
    s = tools.set_night_service(tools.narrow(S))
    s = tools.exclude(s, [3, 4])
    c = changes(S, s)
    assert "반경 2km → 1km" in c and "야간 표방 우선" in c and "2곳 제외" in c


def test_diff_draft():
    assert changes(None, S)[0].startswith("초안")


@pytest.mark.parametrize("utt,tool,args", [
    ("너무 멀어", "narrow", {}),
    ("좀 더 넓게 봐줘", "widen", {}),
    ("500m 안에서만", "set_radius", {"m": 500}),
    ("지금 열린 데", "set_open_now", {"on": True}),
    ("밤에 갈 수 있는 곳", "set_night_service", {"on": True}),
    ("급해요 지금 당장", "set_urgency", {"level": "urgent"}),
    ("뒷다리 절뚝거려서 관절 잘 보는 데", "set_specialty", {"tags": ["ortho"]}),
    ("계단 없는 길로 걸어갈래", "set_walk_avoid", {"facilities": ["stairs"]}),
    ("15분 안에 갈 수 있는 데", "set_max_total_min", {"minutes": 15}),
    ("차로 갈게", "set_mode", {"mode": "car"}),
    ("아까대로", "undo", {}),
    ("24시 하는 데", "require", {"tags": ["24h"]}),
])
async def test_fake_llm_rules(utt, tool, args):
    plan = await FakeLLM().plan(utt, S, [], "")
    names = {c.tool: c for c in plan}
    assert tool in names, plan
    for k, v in args.items():
        assert names[tool].args[k] == v


async def test_fake_llm_ordinal_exclude_uses_shown_ids():
    plan = await FakeLLM().plan("두번째 거는 빼줘", S, [11, 22, 33], "")
    assert ToolCall("exclude", {"ids": [22]}) in plan


async def test_fake_llm_asks_when_clueless():
    plan = await FakeLLM().plan("음...", S, [], "")
    assert plan[0].tool == "ask"


def test_draft_uses_profile_only_as_default():
    s = draft(37.5, 127.0, PERSONAS["halmae"], 2000)
    assert s.journey.walk.option == "no_stairs"             # journey 기본값만
    assert s.target.open_now is False and s.target.specialty == []   # target 필터는 안 건드림
    s2 = draft(37.5, 127.0, PERSONAS["kong"], 2000)
    assert s2.journey.walk.option == "recommended"


async def test_refine_edits_then_utterance():
    r = await refine(None, [ToolCall("set_radius", {"m": 800})], "야간에 하는 데",
                     [], PERSONAS["dubu"], 37.5, 127.0, 2000)
    assert r.state.target.radius_m == 800 and r.state.target.night_service is True
    assert r.question is None
    assert any("야간" in c for c in r.changes)


async def test_refine_question_leaves_state():
    r = await refine(S, [], "글쎄", [], None, 37.5, 127.0, 2000)
    assert r.question and r.state.snapshot() == S.snapshot()


# --- 정책 경계 (state.py) --------------------------------------------------
def test_every_tool_belongs_to_exactly_one_policy():
    from app.refine.tools import CONTEXT_TOOLS, JOURNEY_TOOLS, TARGET_TOOLS, TOOLS, VIEW_TOOLS
    groups = [set(CONTEXT_TOOLS), set(TARGET_TOOLS), set(JOURNEY_TOOLS), set(VIEW_TOOLS)]
    assert set().union(*groups) == set(TOOLS)                  # 빠진 툴 없음
    for i, a in enumerate(groups):                             # 겹치는 툴 없음
        for b in groups[i + 1:]:
            assert not (a & b)


def test_context_tools_touch_neither_target_nor_journey():
    """상황은 **입력**이지 정책이 아니다.

    '급하다'가 target 을 직접 건드리면 journey 는 그걸 영영 못 본다 — `emergency` 가
    정확히 그 상태였다. 사영은 resolver 한 곳에서만 일어나야 하고, 툴은 사실만 적는다.
    """
    from app.refine.tools import CONTEXT_TOOLS
    args = {"set_urgency": {"level": "urgent"},
            "set_time_intent": {"kind": "service_at", "at": datetime(2026, 8, 20, 15, 0, tzinfo=UTC)}}
    for name, fn in CONTEXT_TOOLS.items():
        out = fn(S, **args[name])
        assert out.target == S.target, f"{name} 이 target 을 건드렸다"
        assert out.journey == S.journey, f"{name} 이 journey 를 건드렸다"


def test_reset_clears_filters_but_keeps_the_situation():
    """필터 초기화가 사실까지 지우면 안 된다 — 지금 급한 건 필터를 푼다고 안 달라진다."""
    s = tools.set_urgency(tools.set_night_service(S), "urgent")
    s = tools.set_time_intent(s, "depart_at", datetime(2026, 8, 20, 21, 0, tzinfo=UTC))
    r = tools.reset(s)
    assert r.target.night_service is False
    assert r.urgency == "urgent" and r.time_intent is not None


def test_tool_specs_cover_all_tools_with_policy():
    from app.refine.tools import TOOL_SPECS, TOOLS, policy_of
    spec_names = {t["name"] for t in TOOL_SPECS} - {"ask"}
    assert spec_names == set(TOOLS)
    assert all(t["policy"] == policy_of(t["name"]) for t in TOOL_SPECS if t["name"] != "ask")


def test_journey_tools_never_touch_target():
    from app.refine.tools import JOURNEY_TOOLS
    args = {"set_mode": {"mode": "car"}, "set_walk_option": {"option": "no_stairs"},
            "set_max_total_min": {"minutes": 10}, "set_walk_avoid": {"facilities": ["stairs"]},
            "unset_walk_avoid": {"facilities": ["stairs"]}, "set_walk_max_min": {"minutes": 10}}
    for name, fn in JOURNEY_TOOLS.items():
        out = fn(S, **args[name])
        assert out.target == S.target, f"{name} 이 target 을 건드렸다"


def test_target_tools_never_touch_journey():
    from app.refine.tools import TARGET_TOOLS
    args = {"set_origin": {"lat": 37.6, "lng": 127.1}, "set_radius": {"m": 500}, "widen": {},
            "narrow": {}, "set_open_now": {}, "set_night_service": {},
            "set_emergency_service": {}, "set_specialty": {"tags": ["eye"]},
            "note_symptoms": {"terms": ["눈이 뿌옇"]}, "clear_symptoms": {},
            "require": {"tags": ["24h"]}, "unrequire": {"tags": ["24h"]},
            "exclude": {"ids": [1]}, "pin": {"ids": [2]}}
    for name, fn in TARGET_TOOLS.items():
        out = fn(S, **args[name])
        assert out.journey == S.journey, f"{name} 이 journey 를 건드렸다"


def test_diff_groups_by_policy():
    from app.refine.diff import changes_by_policy
    s = tools.set_walk_avoid(tools.narrow(S), ["stairs"])
    g = changes_by_policy(S, s)
    assert any("반경" in c for c in g["target"])
    assert any("피하기" in c or "도보 옵션" in c for c in g["journey"])
    assert not g["target"] or all("계단" not in c for c in g["target"])


def test_max_total_min_is_advice_only_unless_hard():
    s = tools.set_max_total_min(S, 10)
    assert s.journey.max_total_min == 10 and s.journey.hard_limit is False
    assert tools.set_max_total_min(S, 10, hard=True).journey.hard_limit is True


def test_every_tool_has_a_scope_and_walk_tools_are_marked():
    """scope 는 policy 와 직교하는 축. 도보 전용 툴만 walk 여야 한다."""
    assert {n for n in tools.TOOLS if tools.scope_of(n) == "walk"} == set(tools.WALK_TOOLS)
    for spec in tools.TOOL_SPECS:
        assert spec.get("scope") in ("any", "walk"), spec["name"]
        if spec["name"] in tools.TOOLS:
            assert spec["scope"] == tools.scope_of(spec["name"]), spec["name"]


def test_nl_emits_mode_explicitly_for_walk_scoped_intent():
    """'계단 없는 길'은 도보를 함의한다 — 그럼 set_mode(walk)를 **따로** 내야 한다.
    툴이 몰래 세우면 applied/diff 에 안 보여서 사용자가 왜 도보가 됐는지 모른다."""
    import asyncio

    from app.refine.nl import FakeLLM
    plan = asyncio.run(FakeLLM().plan("계단 없는 길로", S, [], ""))
    assert [c.tool for c in plan] == ["set_mode", "set_walk_avoid"]


def test_nl_merges_accumulating_tools_instead_of_dropping():
    """같은 툴이 두 번 나오면 인자를 합친다. 마지막 것만 남기면 조건이 조용히 사라진다.

    증상이 아니라 **과목**을 두 개 말한 경우다 — 증상→과목 추론은 하지 않는다 (nl.py).
    """
    import asyncio

    from app.refine.nl import FakeLLM
    plan = asyncio.run(FakeLLM().plan("안과랑 정형 둘 다 보는 데", S, [], ""))
    tags = next(c.args["tags"] for c in plan if c.tool == "set_specialty")
    assert set(tags) == {"eye", "ortho"}, tags


def test_symptoms_do_not_become_specialties():
    """증상은 진단이 아니다. "숨을 헐떡여요" → 심장은 관할 밖이고 재료도 없다.

    (실측 2026-08-20: cardio 태그 전국 16곳 · ortho 2곳. 그것도 간판 이름일 뿐이다.)
    증상 표현은 커뮤니티 근거 경로가 원문 그대로 받아 쓴다.
    """
    import asyncio

    from app.refine.nl import FakeLLM
    for utt in ("숨을 헐떡여요", "뒷다리를 절뚝거려요", "눈이 뿌옇게 됐어요", "자꾸 긁어요"):
        plan = asyncio.run(FakeLLM().plan(utt, S, [], ""))
        assert not [c for c in plan if c.tool == "set_specialty"], f"{utt} -> {plan}"
