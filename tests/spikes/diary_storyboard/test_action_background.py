"""Action provenance, conditional supplementation, quality and source preservation."""

import json
from copy import deepcopy

import pytest

from scripts.spikes.diary_storyboard.how_demo import route, scenarios
from scripts.spikes.diary_storyboard.how_stamp_demo import cases, source_with_records
from scripts.spikes.diary_storyboard.stamp_storyboard import accept_selection, writing_request
from scripts.spikes.diary_storyboard.stamp_tool import StampTool


def mixed_route():
    return route("dwell-and-pace", [(0, 0, 0), (120, 120, 0), (180, 120, 0),
                                   (300, 240, 0), (340, 320, 0), (460, 440, 0)])


def make_tool(walk=None, records=(), target=3, **policy):
    return StampTool("action_background", source_with_records(walk or mixed_route(), records),
                     {"target_scene_count": target, **policy})


def derived(tool):
    return [tool.project(ref)["action"] for ref in tool.refs
            if tool.project(ref)["action"]["origin"] == "derived_observation"]


def counts(tool):
    return tool.dump()["slot_audit"]["scene_counts"]


def test_no_records_only_observed_dwell_and_fast_qualify_not_duplicate_slow():
    tool = make_tool()
    assert {a["kind"] for a in derived(tool)} == {"observed_dwell", "observed_fast"}
    assert len(derived(tool)) == 2
    assert counts(tool)["remaining_deficit"] == 1  # Never fabricate a third scene.
    assert any(d["reason"] == "overlapping_selected_observation"
               for d in tool.dump()["slot_audit"]["action_selection"])
    assert all(a["subject"] == "recording_device" and a["status"] == "candidate"
               and a["action_meaning"] == "not_inferred" for a in derived(tool))


def test_user_records_meet_target_and_all_original_content_survives():
    records = [(6, "note", "  원문 그대로\n"), (50, "photo", ""), (84, "note", "세 번째")]
    source = source_with_records(mixed_route(), records)
    source["records"]["records"][2]["content"] = {
        "kind": "behavior", "code": "sniffing", "pet_id": None}
    tool = StampTool("action_background", source, {"target_scene_count": 3})
    assert not derived(tool)
    assert len(tool.refs) == 3
    assert [tool.project(r)["action"]["content"] for r in tool.refs] == [
        r["content"] for r in source["records"]["records"]]
    assert all(d["reason"] == "user_target_met"
               for d in tool.dump()["slot_audit"]["action_selection"])
    assert tool.dump()["derived_action_catalog"]["candidates"]  # Pool != promotion.


def test_one_record_only_fills_deficit_and_never_relabels_background_as_action():
    tool = make_tool(records=[(6, "note", "먼저 적은 글")], target=2)
    assert counts(tool)["supplemented"] == 1
    assert derived(tool)[0]["kind"] == "observed_dwell"
    for ref in tool.refs:
        material = tool.project(ref)
        assert "how" not in material and "background" in material
        assert all(h["role"] == "trajectory_context" for h in material["background"]["trajectory"])
    selected = accept_selection(tool, {"optional_stamp_ids": []})
    assert selected == tool.refs  # Rule-chosen stamps, not a second LLM selection.
    request, _ = writing_request(tool, selected)
    assert len(request["stamps"]) == 2


def test_existing_record_at_dwell_suppresses_a_duplicate_observation_scene():
    tool = make_tool(records=[(30, "note", "이때 남긴 메모")])
    assert {a["kind"] for a in derived(tool)} == {"observed_fast"}
    assert any(d["reason"] == "near_user_record_time"
               for d in tool.dump()["slot_audit"]["action_selection"])


@pytest.mark.parametrize("name", ["straight", "right", "left", "out_back", "gap"])
def test_ordinary_shapes_and_gps_absence_never_fill_the_action_quota(name):
    tool = make_tool(scenarios()[name]["source"])
    assert not tool.refs
    assert counts(tool)["remaining_deficit"] == 3


def test_sustained_slow_progress_can_fill_a_scene_without_an_invented_action():
    walk = route("slow", [(0, 0, 0), (120, 120, 0), (240, 150, 0), (360, 270, 0)])
    tool = make_tool(walk, target=1)
    # Dwell can also be observed over a bounded slow window. Either label must
    # stay an observation; inspect the independent pace pool for the full run.
    slow, = [c for c in tool.dump()["derived_action_catalog"]["candidates"]
             if c["kind"] == "observed_slow"]
    assert slow["metrics"]["mean_mps"] == pytest.approx(0.25)
    assert slow["support"]["window_s"] == 120
    assert "content" not in derived(tool)[0]


@pytest.mark.parametrize("accuracy", [None, 30])
def test_unknown_or_rejected_accuracy_cannot_create_surrogate_actions(accuracy):
    walk = mixed_route()
    walk = walk.model_copy(update={"fixes": tuple(
        f.model_copy(update={"accuracy_m": accuracy}) for f in walk.fixes)})
    tool = make_tool(walk)
    assert not tool.refs
    assert tool.dump()["derived_action_catalog"]["speed_reference"]["baseline_mps"] is None


def test_gps_speed_rejection_and_one_short_spike_are_not_fast_action_candidates():
    spike = route("spike", [(0, 0, 0), (120, 120, 0), (125, 132, 0), (245, 252, 0)])
    rejected = route("rejected", [(0, 0, 0), (120, 120, 0), (160, 520, 0), (280, 640, 0)])
    for walk in (spike, rejected):
        tool = make_tool(walk)
        assert not derived(tool)
    assert make_tool(rejected).dump()["how_catalog"]["quality_audit"]


def test_short_pace_changes_across_a_gap_cannot_be_combined():
    walk = route("pace-gap", [(0, 0, 0), (120, 120, 0), (130, 140, 0),
                              (210, 140, 0), (220, 160, 0), (340, 280, 0)])
    walk = walk.model_copy(update={"fixes": tuple(f for f in walk.fixes
        if not 130 < (f.at - walk.started_at).total_seconds() < 210)})
    assert not make_tool(walk).refs


def test_whole_session_fallback_note_and_missing_attachment_are_preserved():
    source = source_with_records(mixed_route(), [(6, "note", "산책 전체 메모")])
    source["attachments"] = []
    record = source["records"]["records"][0]
    record.update(location=None, time_basis="session_fallback")
    tool = StampTool("action_background", source, {"target_scene_count": 1})
    ref, = tool.refs
    assert tool.anchor(ref)["location"] is None
    assert tool.project(ref)["action"]["content"] == record["content"]
    assert tool.project(ref)["background"]["trajectory"] == []


def test_dwell_does_not_require_a_speed_reference_and_uses_an_observed_anchor():
    walk = scenarios()["stay"]["source"]
    tool = make_tool(walk, target=1)
    action, = derived(tool)
    assert action["kind"] == "observed_dwell"
    assert tool.dump()["derived_action_catalog"]["speed_reference"]["baseline_mps"] is None
    anchor = tool.anchor(tool.refs[0])
    assert any(anchor["location"]["point"] == {"lat": f.lat, "lng": f.lng}
               and anchor["event_at"] == f.at.isoformat() for f in walk.fixes)
    assert "action_onset" in anchor["time_basis"]


def test_no_product_minimum_is_invented_and_zero_disables_supplementation():
    with pytest.raises(ValueError, match="target_scene_count"):
        StampTool("action_background", source_with_records(mixed_route()))
    assert not make_tool(target=0).refs
    with pytest.raises(ValueError, match="capacity"):
        make_tool(target=8)
    # A lower target never truncates user records.
    tool = make_tool(records=[(6, "note", "첫"), (8, "note", "둘")], target=1)
    assert len(tool.refs) == 2 and not derived(tool)


def test_book_replays_and_tampering_or_source_changes_cannot_reuse_references():
    tool = make_tool()
    book = json.loads(json.dumps(tool.dump()))
    assert StampTool.load(book).query() == tool.query()
    bad = deepcopy(book)
    bad["derived_action_catalog"]["candidates"][0]["origin"] = "user_record"
    with pytest.raises(ValueError, match="replay"):
        StampTool.load(bad)
    changed = make_tool(target=1)
    with pytest.raises(ValueError, match="stale"):
        changed.resolve(tool.refs[0])
    tool.project(tool.refs[0])["action"]["origin"] = "edited"
    assert tool.project(tool.refs[0])["action"]["origin"] == "derived_observation"


def test_old_how_experiment_retains_its_original_three_movement_candidates():
    source = cases()["no_record"]["source"]
    legacy = StampTool("record_how", source)
    current = StampTool("action_background", source, {"target_scene_count": 3})
    assert len(legacy.refs) == 3
    assert [a["kind"] for a in derived(current)] == ["observed_dwell"]
    assert StampTool.load(legacy.dump()).query() == legacy.query()
