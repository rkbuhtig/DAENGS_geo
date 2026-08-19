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
    assert S.radius_m == 2000 and s2.radius_m == 1000
    assert len(s2.history) == 1
    s3 = tools.undo(s2)
    assert s3.radius_m == 2000 and s3.history == []


def test_undo_on_empty_is_noop():
    assert tools.undo(S) is S


def test_avoid_stairs_sets_option_and_mode():
    s = tools.avoid(S, ["stairs"])
    assert s.walk.option == "no_stairs" and s.mode == "walk"


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
    assert s.walk.option == "no_stairs"
    assert s.open_now is False and s.specialty == []       # 필터는 없음
    s2 = draft(37.5, 127.0, PERSONAS["kong"], 2000)
    assert s2.walk.option == "recommended"


async def test_refine_edits_then_utterance():
    r = await refine(None, [ToolCall("set_radius", {"m": 800})], "야간에 하는 데",
                     [], PERSONAS["dubu"], 37.5, 127.0, 2000)
    assert r.state.radius_m == 800 and r.state.night is True
    assert r.question is None
    assert any("야간" in c for c in r.changes)


async def test_refine_question_leaves_state():
    r = await refine(S, [], "글쎄", [], None, 37.5, 127.0, 2000)
    assert r.question and r.state.snapshot() == S.snapshot()
