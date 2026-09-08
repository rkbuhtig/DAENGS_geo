"""HOW supports, editorial focus, exact records, continuity, and replay boundaries."""

from copy import deepcopy
from datetime import datetime

import pytest

from scripts.spikes.diary_storyboard.how_demo import scenarios
from scripts.spikes.diary_storyboard.how_stamp_demo import cases, source_with_records
from scripts.spikes.diary_storyboard.stamp_storyboard import (
    accept_selection,
    accept_writing,
    render,
    writing_request,
)
from scripts.spikes.diary_storyboard.stamp_tool import StampTool


def tool_for(name, policy=None):
    return StampTool("record_how", cases()[name]["source"], policy)


def required(tool):
    return [r for r in tool.refs if tool.resolve(r)["required"]]


def test_photo_keeps_its_point_while_turn_support_remains_a_separate_interval():
    tool = tool_for("photo_turn")
    ref, = required(tool)
    anchor, projected = tool.anchor(ref), tool.project(ref)
    record, = tool.dump()["source"]["records"]["records"]
    assert datetime.fromisoformat(anchor["event_at"]) == datetime.fromisoformat(record["event_at"])
    assert anchor["location"] == record["location"]
    assert projected["record"] == record["content"]
    turn, = [h for h in projected["how"] if h["kind"] == "turn"]
    assert turn["role"] == "focus_context"
    assert turn["relation"]["type"] == "record_near_turn_vertex"
    assert datetime.fromisoformat(projected["available_at"]) > datetime.fromisoformat(anchor["event_at"])
    assert "duration_s" not in projected["record"]
    assert "support" not in tool.resolve(ref)  # no union assigned to the photo/stamp


def test_a_long_turn_support_is_not_enough_to_attach_a_distant_photo():
    tool = tool_for("far_photo")
    ref, = required(tool)
    assert {h["kind"] for h in tool.project(ref)["how"]} == {"straight_run"}
    assert any(h["kind"] == "turn" for r in tool.refs if not tool.resolve(r)["required"]
               for h in tool.project(r)["how"])


def test_record_inside_stay_gets_observation_relation_not_action_duration():
    tool = tool_for("note_stay")
    ref, = required(tool)
    stay, = [h for h in tool.project(ref)["how"] if h["kind"] == "local_stay"]
    assert stay["relation"]["type"] == "record_within_observed_support"
    assert stay["relation"]["record_offset_s"] > 0
    assert stay["support"]["time_meaning"] == "observed_support_window"
    assert tool.project(ref)["record"]["text"] == "여기서 잠깐 주변을 봤다."


def test_reverse_and_retrace_share_a_focus_and_keep_their_different_supports():
    tool = tool_for("note_return")
    ref, = required(tool)
    focus = [h for h in tool.project(ref)["how"] if h["role"] == "focus_context"]
    assert {h["kind"] for h in focus} == {"turn", "retrace"}
    assert len({h["support"]["from_seq"] for h in focus}) == 2
    assert all(h["subject"] == "recording_device" for h in focus)


def test_no_record_emits_movement_focus_without_straight_cards_or_duplicate_reverse():
    tool = tool_for("no_record")
    assert not required(tool)
    assert len(tool.refs) == 3  # turn, stay, reversal+retrace on this synthetic route
    focus_kinds = [{h["kind"] for h in tool.project(r)["how"]
                    if h["role"] in {"focus", "cofocus"}} for r in tool.refs]
    assert {"turn", "retrace"} in focus_kinds
    assert all("straight_run" not in kinds for kinds in focus_kinds)


def test_all_records_absorb_their_focus_candidates_but_remain_required():
    tool = tool_for("all_records")
    assert len(required(tool)) == len(tool.refs) == 3
    selected = accept_selection(tool, {"optional_stamp_ids": []})
    payload, _ = writing_request(tool, selected)
    assert len(payload["stamps"]) == 3
    board = accept_writing(tool, selected, {"title": "검산용", "cards": [
        {"stamp_id": r.id, "title": "검산용", "text": "모델 작성 아님"} for r in selected
    ]})
    assert [c["anchor"] for c in render(tool, board)["cards"]] == [tool.anchor(r) for r in selected]


def test_multiple_records_in_same_stay_are_not_deduplicated():
    walk = scenarios()["pause_turn"]["source"]
    source = source_with_records(walk, [(22, "note", "  첫 메모\n"), (24, "photo", "")])
    tool = StampTool("record_how", source)
    assert len(required(tool)) == len(tool.refs) == 2
    assert tool.project(required(tool)[0])["record"]["text"] == "  첫 메모\n"
    for ref in tool.refs:
        assert {h["kind"] for h in tool.project(ref)["how"] if h["role"] == "focus_context"} == {
            "local_stay", "turn"
        }
        turn = next(h for h in tool.project(ref)["how"] if h["kind"] == "turn")
        assert turn["relation"]["event_order"] == "not_established"


def test_gap_does_not_join_record_context_or_turn_shape():
    tool = tool_for("gap")
    assert len(tool.refs) == 2
    runs = []
    for ref in tool.refs:
        material = tool.project(ref)
        assert material["relations"] == []
        assert {h["kind"] for h in material["how"]} == {"straight_run"}
        runs.append({h["support"]["chain_index"] for h in material["how"]})
    assert runs[0].isdisjoint(runs[1])


def test_stricter_how_accuracy_break_does_not_reuse_previous_action():
    walk = scenarios()["straight"]["source"]
    fixes = list(walk.fixes)
    fixes[12] = fixes[12].model_copy(update={"accuracy_m": 30})
    walk = walk.model_copy(update={"fixes": tuple(fixes)})
    tool = StampTool("record_how", source_with_records(walk, [(8, "photo", ""), (16, "note", "뒤쪽")]))
    refs = required(tool)
    assert tool.project(refs[1])["relations"] == []
    supports = [tool.project(r)["how"][0]["support"] for r in refs]
    assert supports[0]["chain_index"] == supports[1]["chain_index"]
    assert supports[0]["how_run_index"] != supports[1]["how_run_index"]


def test_unattached_and_rejected_records_are_retained_without_invented_how():
    source = cases()["photo_turn"]["source"]
    source["attachments"] = []
    tool = StampTool("record_how", source)
    ref, = required(tool)
    assert tool.project(ref)["how"] == []
    assert tool.resolve(ref)["route_binding"] == "not_attached"
    source = cases()["photo_turn"]["source"]
    source["route"]["fixes"][18]["accuracy_m"] = 30
    tool = StampTool("record_how", source)
    ref, = required(tool)
    assert tool.project(ref)["how"] == []
    assert tool.resolve(ref)["route_binding"] == "rejected_or_isolated_fix"


@pytest.mark.parametrize("mutation", ["point", "time", "session", "version", "duplicate", "origin"])
def test_invalid_route_bindings_fail_closed(mutation):
    source = cases()["photo_turn"]["source"]
    record = source["records"]["records"][0]
    if mutation == "point":
        record["location"]["point"]["lat"] += .001
    elif mutation == "time":
        record["event_at"] = source["route"]["started_at"]
    elif mutation == "session":
        record["session_id"] = "other"
    elif mutation == "version":
        source["attachments"][0]["record_ref"]["version"] = "stale"
    elif mutation == "duplicate":
        source["attachments"].append(deepcopy(source["attachments"][0]))
    else:
        source["records"]["synthetic"] = False
    with pytest.raises(ValueError):
        StampTool("record_how", source)


def test_shape_slot_budget_changes_context_not_focus_or_source():
    small, large = tool_for("all_records", {"shape_context_slots": 0}), tool_for("all_records")
    assert small.dump()["source"] == large.dump()["source"]
    assert [r.id for r in small.refs] == [r.id for r in large.refs]
    for a, b in zip(small.refs, large.refs):
        assert a.version != b.version
        assert all(h["role"] != "shape_context" for h in small.project(a)["how"])
        assert small.resolve(a)["center"] == large.resolve(b)["center"]
    assert any(a["reason"] == "context_budget" for a in small.dump()["slot_audit"]["how"])


def test_replay_preserves_every_support_and_rejects_catalog_tampering():
    tool = tool_for("all_records")
    book = tool.dump()
    catalog = {m["ref"]["id"]: m for m in book["how_catalog"]["materials"]}
    for ref in tool.refs:
        for member in tool.project(ref)["how"]:
            assert member["support"] == catalog[member["material_ref"]["id"]]["support"]
    assert StampTool.load(book).query() == tool.query()
    book["how_catalog"]["materials"][0]["support"]["from_seq"] += 1
    with pytest.raises(ValueError, match="replay"):
        StampTool.load(book)


def test_source_and_projection_copies_cannot_change_existing_stamp():
    source = cases()["note_stay"]["source"]
    tool = StampTool("record_how", source)
    ref, = required(tool)
    source["records"]["records"][0]["content"]["text"] = "edited"
    projection = tool.project(ref)
    projection["how"].clear()
    assert tool.project(ref)["how"]
    changed = StampTool("record_how", source)
    with pytest.raises(ValueError, match="stale"):
        changed.resolve(ref)
