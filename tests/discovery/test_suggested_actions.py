import pytest
from pydantic import ValidationError

from app.discovery.refine.actions import Edit, SuggestedAction
from app.discovery.refine.engine import refine
from app.discovery.refine.nl import ToolCall
from app.discovery.state import EditableState


async def test_multi_edit_action_uses_one_refine_turn_and_one_undo_step():
    """결정 #45 — 버튼 하나가 툴 여럿이어도 되돌림은 한 칸이다.

    #66 으로 도보 옵션 축이 사라지면서 **현재 정책이 내는 액션은 전부 edit 하나짜리**가
    됐다 (예전엔 `walk_without_stairs` 가 set_mode + set_walk_avoid 둘이었다). 계약은
    그대로 여러 개를 허용하므로, 정책이 다시 둘을 낼 때 깨지지 않게 여기서 직접 만들어 본다.
    """
    state = EditableState(lat=37.5, lng=127.0)
    action = SuggestedAction(
        id="walk_within_15", label="걸어서 15분 안에", source="policy",
        edits=[Edit(tool="set_mode", args={"mode": "walk"}),
               Edit(tool="set_max_total_min", args={"minutes": 15})],
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
    assert out.state.journey.max_total_min == 15
    assert len(out.state.history) == 1


def test_action_contract_rejects_empty_or_unknown_shapes():
    with pytest.raises(ValidationError):
        SuggestedAction(id="bad", label="빈 액션", source="policy", edits=[])
    with pytest.raises(ValidationError):
        SuggestedAction.model_validate({
            "id": "bad", "label": "임의 URL", "source": "policy", "kind": "external",
            "edits": [{"tool": "widen", "args": {}}],
        })
