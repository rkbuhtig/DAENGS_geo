"""Source isolation, slot meaning, thin-card references, and preserved-output replay."""

from copy import deepcopy

import pytest

from scripts.spikes.diary_storyboard.stamp_demo import ARCHIVE, RECORDS, prepare, read
from scripts.spikes.diary_storyboard.stamp_storyboard import (
    Storyboard,
    accept_selection,
    accept_writing,
    render,
    selection_request,
    writing_request,
)
from scripts.spikes.diary_storyboard.stamp_tool import StampRef, StampTool


def record_tool(source=None, **policy):
    return StampTool("record_envelopes", source if source is not None else read(RECORDS), policy)


def ref(tool, suffix):
    return next(r for r in tool.refs if r.id.endswith(":" + suffix))


def board_for(tool):
    refs = accept_selection(tool, {"optional_stamp_ids": []})
    raw = {"title": "fixture", "cards": [
        {"stamp_id": r.id, "title": "fixture", "text": "fixture"} for r in refs
    ]}
    return refs, raw, accept_writing(tool, refs, raw)


def test_record_stamps_use_explicit_selected_envelopes_and_keep_original_note():
    source = read(RECORDS)
    tool = record_tool(source)
    assert len(tool.refs) == len(source["records"]) == 6
    frame = tool.resolve(ref(tool, "behavior-01"))
    assert frame["context_envelope_ids"] == ["park-02"]
    assert "park-01" not in {e for r in tool.refs for e in tool.resolve(r)["context_envelope_ids"]}
    note = next(r for r in source["records"] if r["ref"]["id"] == "note-01")
    assert tool.project(ref(tool, "note-01"))["record"]["text"] == note["content"]["text"]
    assert "record" not in frame  # source content stored once, not copied into every frame


def test_context_distinguishes_prior_query_from_photo_location_and_action_duration():
    tool = record_tool()
    photo = tool.project(ref(tool, "photo-01"))
    context = {e["id"]: e for e in photo["context"]}
    assert context["facilities-empty"]["relation_to_stamp"] == "same_record"
    assert context["facilities-empty"]["status"] == "empty"
    assert context["river-01"]["relation_to_stamp"] == "prior_record_query"
    assert context["river-01"]["elapsed_s"] == 120
    assert context["river-01"]["applies_to"]["id"] == "note-01"
    relation, = photo["relations"]
    assert relation["elapsed_s"] == 120
    assert relation["action"]["code"] == "sniffing"
    assert relation["continuous_presence"] == "not_established"
    assert "duration_s" not in photo["record"]
    assert "pet_id" not in photo["record"]  # session membership cannot identify photo subjects


def test_space_capacity_changes_context_without_deleting_records_or_emitting_departure():
    small, large = record_tool(space_slots=1), record_tool(space_slots=5)
    assert [r.id for r in small.refs] == [r.id for r in large.refs]
    assert small.dump()["source"] == large.dump()["source"]
    assert any(a["reason"] == "capacity_eviction" for a in small.dump()["slot_audit"])
    current = small.resolve(ref(small, "note-01"))["context_envelope_ids"]
    assert {"river-01", "facilities-partial"} <= set(current)
    # Current record's own evidence is preserved even when past-context slots are tight.
    assert small.resolve(ref(small, "photo-01"))["context_envelope_ids"] == ["facilities-empty"]
    assert len(large.resolve(ref(large, "photo-01"))["context_envelope_ids"]) > 1
    assert {a["reason"] for a in small.dump()["slot_audit"]} <= {
        "admit", "expired", "capacity_eviction", "session_reset"
    }


def test_expiry_and_session_scope_do_not_reuse_context():
    tool = record_tool()
    frame = tool.resolve(ref(tool, "note-unlocated"))
    assert frame["context_envelope_ids"] == ["unlocated-not-requested"]
    assert frame["previous_action_id"] is None
    assert tool.anchor(ref(tool, "note-unlocated"))["location"] is None
    source = read(RECORDS)
    next(r for r in source["records"] if r["ref"]["id"] == "photo-01")["session_id"] = "other"
    with pytest.raises(ValueError, match="one walk session"):
        record_tool(source)


def test_fallback_time_never_gets_an_action_interval_or_recent_spatial_context():
    source = read(RECORDS)
    record = next(r for r in source["records"] if r["ref"]["id"] == "note-unlocated")
    record["time_basis"] = "session_fallback"
    record["event_at"] = "2026-09-07T15:03:30+09:00"
    envelope = next(e for e in source["envelopes"] if e["id"] == "unlocated-not-requested")
    envelope["target"]["event_at"] = record["event_at"]
    tool = record_tool(source)
    material = tool.project(ref(tool, "note-unlocated"))
    assert material["relations"] == []
    assert [e["id"] for e in material["context"]] == ["unlocated-not-requested"]


@pytest.mark.parametrize("change,expected", [
    ("none", "projected"), ("temporal", "not_event_weather"), ("provider", "not_supported")
])
def test_weather_projector_requires_supported_format_and_event_time(change, expected):
    source = read(RECORDS)
    weather = next(e for e in source["envelopes"] if e["id"] == "weather-historical")
    if change == "temporal":
        weather["provenance"]["temporal_basis"] = "lookup_snapshot"
        weather["provenance"]["valid_time"] = None
    elif change == "provider":
        weather["provenance"]["provider"] = "unsupported-provider"
    tool = record_tool(source)
    row = next(e for e in tool.project(ref(tool, "note-later"))["context"]
               if e["id"] == "weather-historical")
    assert row["projection_status"] == expected
    assert ("measurements" in row) == (change == "none")
    assert "payload" not in row


def test_frozen_book_isolated_from_input_output_mutation_and_replays():
    source = read(RECORDS)
    tool = record_tool(source)
    expected = tool.dump()
    source["records"][0]["content"]["code"] = "barking"
    tool.dump()["source"]["records"].clear()
    tool.resolve(tool.refs[0])["context_envelope_ids"].clear()
    tool.project(tool.refs[0])["record"].clear()
    tool.refs[0].version = "0" * 64
    assert tool.dump() == expected
    assert StampTool.load(expected).dump() == expected


def test_projection_change_cannot_reuse_an_existing_stamp_version(monkeypatch):
    import scripts.spikes.diary_storyboard.stamp_tool as module

    tool = record_tool()
    saved = tool.dump()
    original = module._project_envelope

    def changed(envelope):
        return {**original(envelope), "projector_revision": "changed"}

    monkeypatch.setattr(module, "_project_envelope", changed)
    assert tool.dump() == saved  # already compiled tool is still frozen
    with pytest.raises(ValueError, match="replay"):
        StampTool.load(saved)
    assert record_tool().refs[0].version != tool.refs[0].version


@pytest.mark.parametrize("change", ["frame", "policy", "source", "envelope", "ref"])
def test_modified_book_needs_a_new_version_instead_of_silent_rebinding(change):
    book = record_tool().dump()
    if change == "frame":
        book["stamps"][0]["frame"]["context_envelope_ids"] = []
    elif change == "policy":
        book["policy"]["space_slots"] = 1
    elif change == "source":
        book["source"]["records"][0]["content"]["code"] = "barking"
    elif change == "envelope":
        book["source"]["envelopes"][0]["payload"]["features"][0]["distance_m"] = 999
    else:
        book["stamps"][0]["ref"]["version"] = "0" * 64
    with pytest.raises(ValueError):
        StampTool.load(book)


def test_card_owns_only_text_and_versioned_reference_and_resolves_original_anchor():
    tool = record_tool()
    _, _, board = board_for(tool)
    assert all(set(c) == {"stamp_ref", "title", "text"}
               for c in board.model_dump(mode="json")["cards"])
    view = render(tool, Storyboard.model_validate(board.model_dump(mode="json")))
    photo = next(c for c in view["cards"] if c["stamp_ref"]["id"].endswith(":photo-01"))
    assert photo["anchor"]["event_at"] == "2026-09-07T15:05:00+09:00"
    assert photo["anchor"]["location"]["point"] == {"lat": 37.5665, "lng": 126.978}
    assert view["semantic_status"] == "not_evaluated"
    changed = read(RECORDS)
    changed["records"][0]["content"]["code"] = "barking"
    with pytest.raises(ValueError, match="source version"):
        render(record_tool(changed), board)
    with pytest.raises(ValueError, match="stale"):
        render(record_tool(space_slots=1), board)


def test_selection_and_writer_reject_lost_records_extra_facts_and_duplicate_cards():
    tool = record_tool()
    refs, raw, _ = board_for(tool)
    with pytest.raises(ValueError, match="required"):
        writing_request(tool, refs[:-1])
    with pytest.raises(ValueError, match="stale"):
        writing_request(tool, (StampRef(id=refs[0].id, version="0" * 64), *refs[1:]))
    altered = deepcopy(raw)
    altered["cards"][0]["anchor"] = {"event_at": "invented"}
    with pytest.raises(ValueError):
        accept_writing(tool, refs, altered)
    raw["cards"][0]["stamp_id"] = refs[1].id
    with pytest.raises(ValueError, match="exactly once"):
        accept_writing(tool, refs, raw)
    with pytest.raises(ValueError, match="exceed capacity"):
        selection_request(record_tool(max_cards=2))


def test_empty_records_are_normal_and_do_not_require_a_model_call():
    source = read(RECORDS)
    source.update(records=[], envelopes=[], selected_envelope_ids=[])
    tool = record_tool(source)
    refs = accept_selection(tool, {"optional_stamp_ids": []})
    board = accept_writing(tool, refs, None)
    assert not render(tool, board)["cards"]
    with pytest.raises(ValueError, match="no writing call"):
        writing_request(tool, refs)


def test_optional_selection_has_no_hidden_minimum_and_rejects_duplicate_choices():
    tool = StampTool("archived_v1", read(ARCHIVE / "movement/source.json"))
    assert accept_selection(tool, {"optional_stamp_ids": []}) == ()
    with pytest.raises(ValueError, match="duplicate"):
        accept_selection(tool, {"optional_stamp_ids": [tool.refs[0].id] * 2})


def test_all_preserved_cards_replay_with_same_text_time_and_gap_chain_without_new_calls():
    files = prepare()
    report = files["report.json"]
    assert report["new_model_calls"] == 0 and report["record_stamps"] == 6
    assert sum(r["cards"] for r in report["archive_replays"].values()) == 21
    assert all(r["text_and_anchor_preserved"] for r in report["archive_replays"].values())
    assert not files["records/select_request.json"]["call_needed"]
    for name in ("movement", "actions", "gap"):
        tool = StampTool.load(files[f"{name}/stamp_book.json"])
        board = Storyboard.model_validate(files[f"{name}/storyboard.json"])
        assert render(tool, board) == files[f"{name}/rendered.json"]
