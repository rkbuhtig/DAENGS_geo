import pytest

from app.profile.source import PERSONAS
from app.refine import tools
from app.refine.diff import changes
from app.refine.engine import draft, refine
from app.refine.nl import FakeLLM, ToolCall
from app.refine.state import SearchState

S = SearchState(lat=37.4979, lng=127.0276)


def test_tools_are_pure_and_push_history():
    s2 = tools.narrow(S)
    assert S.target.radius_m == 2000 and s2.target.radius_m == 1000
    assert len(s2.history) == 1
    s3 = tools.undo(s2)
    assert s3.target.radius_m == 2000 and s3.history == []


def test_undo_on_empty_is_noop():
    assert tools.undo(S) is S


def test_avoid_stairs_sets_option_and_mode():
    s = tools.avoid(S, ["stairs"])
    assert s.journey.walk.option == "no_stairs" and s.journey.mode == "walk"
    assert tools.unavoid(s, ["stairs"]).journey.walk.option == "recommended"


def test_set_mode_switches_sort_to_duration():
    assert tools.set_mode(S, "car").sort == "duration"


def test_diff_lists_every_change():
    s = tools.set_time(tools.narrow(S), night=True)
    s = tools.exclude(s, [3, 4])
    c = changes(S, s)
    assert "반경 2km → 1km" in c and "야간 진료만" in c and "2곳 제외" in c


def test_diff_draft():
    assert changes(None, S)[0].startswith("초안")


@pytest.mark.parametrize("utt,tool,args", [
    ("너무 멀어", "narrow", {}),
    ("좀 더 넓게 봐줘", "widen", {}),
    ("500m 안에서만", "set_radius", {"m": 500}),
    ("지금 열린 데", "set_time", {"open_now": True}),
    ("밤에 갈 수 있는 곳", "set_time", {"night": True}),
    ("뒷다리 절뚝거려서 관절 잘 보는 데", "set_specialty", {"tags": ["ortho"]}),
    ("계단 없는 길로 걸어갈래", "avoid", {"facilities": ["stairs"]}),
    ("15분 안에 갈 수 있는 데", "set_max_min", {"minutes": 15}),
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
    assert r.state.target.radius_m == 800 and r.state.target.night is True
    assert r.question is None
    assert any("야간" in c for c in r.changes)


async def test_refine_question_leaves_state():
    r = await refine(S, [], "글쎄", [], None, 37.5, 127.0, 2000)
    assert r.question and r.state.snapshot() == S.snapshot()


# --- 정책 경계 (state.py) --------------------------------------------------
def test_every_tool_belongs_to_exactly_one_policy():
    from app.refine.tools import JOURNEY_TOOLS, TARGET_TOOLS, TOOLS, VIEW_TOOLS
    groups = [set(TARGET_TOOLS), set(JOURNEY_TOOLS), set(VIEW_TOOLS)]
    assert set().union(*groups) == set(TOOLS)                  # 빠진 툴 없음
    for i, a in enumerate(groups):                             # 겹치는 툴 없음
        for b in groups[i + 1:]:
            assert not (a & b)


def test_tool_specs_cover_all_tools_with_policy():
    from app.refine.tools import TOOL_SPECS, TOOLS, policy_of
    spec_names = {t["name"] for t in TOOL_SPECS} - {"ask"}
    assert spec_names == set(TOOLS)
    assert all(t["policy"] == policy_of(t["name"]) for t in TOOL_SPECS if t["name"] != "ask")


def test_journey_tools_never_touch_target():
    from app.refine.tools import JOURNEY_TOOLS
    args = {"set_mode": {"mode": "car"}, "set_walk_option": {"option": "no_stairs"},
            "set_max_min": {"minutes": 10}, "avoid": {"facilities": ["stairs"]},
            "unavoid": {"facilities": ["stairs"]}}
    for name, fn in JOURNEY_TOOLS.items():
        out = fn(S, **args[name])
        assert out.target == S.target, f"{name} 이 target 을 건드렸다"


def test_target_tools_never_touch_journey():
    from app.refine.tools import TARGET_TOOLS
    args = {"set_origin": {"lat": 37.6, "lng": 127.1}, "set_radius": {"m": 500}, "widen": {},
            "narrow": {}, "set_time": {"night": True}, "set_specialty": {"tags": ["eye"]},
            "require": {"tags": ["24h"]}, "unrequire": {"tags": ["24h"]},
            "exclude": {"ids": [1]}, "pin": {"ids": [2]}}
    for name, fn in TARGET_TOOLS.items():
        out = fn(S, **args[name])
        assert out.journey == S.journey, f"{name} 이 journey 를 건드렸다"


def test_diff_groups_by_policy():
    from app.refine.diff import changes_by_policy
    s = tools.avoid(tools.narrow(S), ["stairs"])
    g = changes_by_policy(S, s)
    assert any("반경" in c for c in g["target"])
    assert any("피하기" in c or "도보 옵션" in c for c in g["journey"])
    assert not g["target"] or all("계단" not in c for c in g["target"])


def test_max_min_is_advice_only_unless_hard():
    s = tools.set_max_min(S, 10)
    assert s.journey.max_min == 10 and s.journey.hard_limit is False
    assert tools.set_max_min(S, 10, hard=True).journey.hard_limit is True
