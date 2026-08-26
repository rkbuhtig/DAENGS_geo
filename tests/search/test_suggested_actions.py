import pytest
from pydantic import ValidationError

from app.features.hospital.actions import build_actions
from app.features.hospital.api import HospitalSearchIn, hospital_search
from app.planning.state import EditableState
from app.refine import tools
from app.refine.actions import Edit, SuggestedAction
from app.refine.engine import refine
from app.refine.nl import ToolCall
from tests.conftest import TEST_ORIGIN, seeded_places


def _state() -> EditableState:
    return EditableState(lat=TEST_ORIGIN[0], lng=TEST_ORIGIN[1])


def _by_id(actions: list[SuggestedAction], action_id: str) -> SuggestedAction:
    return next(action for action in actions if action.id == action_id)


def test_zero_results_offer_only_applicable_recovery_actions():
    actions = build_actions(_state(), result_count=0, question=None)

    assert [action.id for action in actions] == ["widen_radius"]
    assert actions[0].edits == [Edit(tool="set_radius", args={"m": 4000})]
    assert actions == build_actions(_state(), result_count=0, question=None), "같은 state는 같은 제안"


def test_max_radius_without_active_filters_does_not_invent_a_recovery():
    state = _state()
    state.target.radius_m = 20_000

    assert build_actions(state, result_count=0, question=None) == []


def test_recovery_relaxes_specific_filters_without_resetting_journey():
    state = _state()
    state.target.radius_m = 20_000
    state.target.open_now = True
    state.target.require_tags = ["24h", "center"]
    state.journey.walk.option = "no_stairs"

    actions = build_actions(state, result_count=0, question=None)

    assert [action.id for action in actions] == ["relax_open_now", "relax_required_tags"]
    relaxed = state
    for edit in _by_id(actions, "relax_required_tags").edits:
        relaxed = tools.apply(relaxed, edit.tool, edit.args)
    assert relaxed.target.require_tags == []
    assert relaxed.target.open_now is True, "선택하지 않은 검색 조건까지 풀면 안 된다"
    assert relaxed.journey.walk.option == "no_stairs", "검색 복구가 이동 안전 설정을 지웠다"


def test_hard_limit_that_dropped_every_result_gets_the_first_recovery_action():
    state = _state()
    state.journey.max_total_min = 10
    state.journey.hard_limit = True

    actions = build_actions(
        state, result_count=0, question=None, dropped_by_hard_limit=2,
    )

    assert actions[0].id == "show_over_time_limit"
    after = tools.apply(state, actions[0].edits[0].tool, actions[0].edits[0].args)
    assert after.journey.max_total_min == 10
    assert after.journey.hard_limit is False


async def test_multi_edit_action_uses_one_refine_turn_and_one_undo_step():
    state = _state()
    action = _by_id(
        build_actions(state, result_count=1, question="어떤 조건을 바꿀까요?"),
        "walk_without_stairs",
    )

    out = await refine(
        state,
        [ToolCall(edit.tool, edit.args) for edit in action.edits],
        utterance=None,
        shown_ids=[],
        profile=None,
        lat=state.lat,
        lng=state.lng,
        default_radius=2000,
    )

    assert out.state.journey.preferred_mode == "walk"
    assert out.state.journey.walk.avoid == ["stairs"]
    assert len(out.state.history) == 1


def test_question_actions_remove_noops_and_stay_bounded():
    state = _state()
    state.journey.preferred_mode = "walk"
    state.journey.walk.avoid = ["stairs"]
    state.journey.walk.option = "no_stairs"

    actions = build_actions(state, result_count=1, question="다시 물어보기")

    assert len(actions) <= 3
    assert "walk_without_stairs" not in {action.id for action in actions}
    assert all(action.source == "policy" and action.kind == "edits" for action in actions)


def test_action_contract_rejects_empty_or_unknown_shapes():
    with pytest.raises(ValidationError):
        SuggestedAction(id="bad", label="빈 액션", source="policy", edits=[])
    with pytest.raises(ValidationError):
        SuggestedAction.model_validate({
            "id": "bad", "label": "임의 URL", "source": "policy", "kind": "external",
            "edits": [{"tool": "widen", "args": {}}],
        })


async def test_api_action_round_trips_through_existing_edits_contract():
    state = _state()
    state.target.require_tags = ["tag-that-cannot-exist-in-seed"]
    async with seeded_places([]) as db:
        first = await hospital_search(
            HospitalSearchIn(state=state, transport="none"), db,
        )
        action = _by_id(first.actions, "relax_required_tags")
        second = await hospital_search(
            HospitalSearchIn(
                state=first.state,
                edits=action.edits,
                transport="none",
            ),
            db,
        )

    assert first.results == []
    assert first.reply.endswith("아래 제안으로 다시 찾아볼 수 있어요.")
    assert second.state.target.require_tags == []
    assert len(second.state.history) == 1
