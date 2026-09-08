"""The writing projection changes payload shape, not scene selection or evidence."""

import json
from copy import deepcopy

import pytest

from scripts.spikes.diary_storyboard.how_demo import scenarios
from scripts.spikes.diary_storyboard.how_stamp_demo import cases, run, source_with_records
from scripts.spikes.diary_storyboard.stamp_storyboard import accept_writing, render, writing_request
from scripts.spikes.diary_storyboard.stamp_tool import StampTool
from scripts.spikes.diary_storyboard.writing_projection import (
    comparison_display,
    json_size,
    prepare_comparison,
    resolve_how,
    verify_comparison,
)


def prepare(case="all_records"):
    tool = StampTool("record_how", cases()[case]["source"])
    return tool, prepare_comparison(tool, tool.refs)


def test_fixed_selection_original_text_time_and_context_survive_projection():
    tool, result = prepare()
    before = deepcopy(tool.dump())
    baseline, schema = writing_request(tool, tool.refs)
    assert result["baseline_input"] == baseline
    assert result["response_schema"] == schema.model_json_schema()
    assert [s["id"] for s in result["compact_input"]["stamps"]] == [r.id for r in tool.refs]
    for old, new in zip(baseline["stamps"], result["compact_input"]["stamps"]):
        for field in ("when", "record", "context", "relations", "route_binding"):
            assert new[field] == old[field]
    assert tool.dump() == before
    assert result["status"] == "not_sent"


def test_shared_definitions_remove_duplicates_but_preserve_every_role_and_relation():
    tool, result = prepare()
    compact, manifest = result["compact_input"], result["manifest"]
    assert len(compact["how_dictionary"]) == 7
    assert sum(len(s["how"]) for s in compact["stamps"]) == 9
    for old, new in zip(result["baseline_input"]["stamps"], compact["stamps"]):
        assert len(old["how"]) == len(new["how"])
        for a, b in zip(old["how"], new["how"]):
            assert a["role"] == b["role"] and a["relation"] == b["relation"]
            binding = manifest["how_bindings"][b["use"]]
            assert binding["material_ref"] == a["material_ref"]
            assert new["id"] in binding["stamp_ids"]
    for alias, binding in manifest["how_bindings"].items():
        raw = resolve_how(tool, result, alias)
        assert raw["ref"] == binding["material_ref"]
        assert "support" in raw and "anchor" in raw


def test_long_turn_support_stays_local_without_losing_direction_or_record_delta():
    tool, result = prepare("note_return")
    compact = result["compact_input"]
    record = next(s for s in compact["stamps"] if "record" in s)
    use = next(u for u in record["how"]
               if compact["how_dictionary"][u["use"]]["kind"] == "turn")
    definition = compact["how_dictionary"][use["use"]]
    assert definition["direction"] == "reverse"
    assert use["relation"]["record_minus_vertex_s"] == 5
    assert use["relation"]["turn_occurrence_time"] == "not_resolved"
    assert "support" not in definition and "metrics" not in definition
    assert "available_at" not in record
    raw = resolve_how(tool, result, use["use"])
    assert raw["support"]["window_s"] > 300
    assert "duration_s" not in record["record"]


@pytest.mark.parametrize("name,direction", [("left", "left"), ("right", "right")])
def test_turn_direction_and_ordered_geometry_links_are_kept(name, direction):
    source = source_with_records(scenarios()[name]["source"], [(18, "photo", "")])
    tool = StampTool("record_how", source)
    compact = prepare_comparison(tool, tool.refs)["compact_input"]
    assert next(h for h in compact["how_dictionary"].values() if h["kind"] == "turn")[
        "direction"
    ] == direction
    relations = [h["relation"]["type"] for s in compact["stamps"] for h in s["how"]]
    assert "ends_at_focus_vertex" in relations
    assert "starts_at_focus_vertex" in relations


def test_stay_duration_is_only_an_observed_window_and_cofocus_does_not_invent_order():
    source = source_with_records(scenarios()["pause_turn"]["source"], [(24, "note", " 메모\n ")])
    tool = StampTool("record_how", source)
    compact = prepare_comparison(tool, tool.refs)["compact_input"]
    row, = compact["stamps"]
    assert row["record"]["text"] == " 메모\n "
    stay = next(h for h in compact["how_dictionary"].values() if h["kind"] == "local_stay")
    assert stay["observed_window_s"] > 0
    assert stay["duration_basis"] == "bounded_observation_window_not_action_duration"
    turn = next(h for h in row["how"] if compact["how_dictionary"][h["use"]]["kind"] == "turn")
    assert turn["relation"]["event_order"] == "not_established"


def test_unlocated_record_gets_no_invented_how_but_keeps_its_exact_text():
    source = cases()["note_stay"]["source"]
    source["records"]["records"][0]["location"] = None
    source["records"]["records"][0]["time_basis"] = "session_fallback"
    source["attachments"] = []
    tool = StampTool("record_how", source)
    result = prepare_comparison(tool, tool.refs)
    record = next(s for s in result["compact_input"]["stamps"] if "record" in s)
    assert record["how"] == []
    assert record["when"]["basis"] == "session_fallback"
    assert record["route_binding"] == "not_attached"


def test_missing_gps_accuracy_is_not_silently_changed_to_known_accuracy():
    walk = scenarios()["right"]["source"]
    walk = walk.model_copy(update={"fixes": tuple(
        f.model_copy(update={"accuracy_m": None}) for f in walk.fixes
    )})
    tool = StampTool("record_how", source_with_records(walk))
    compact = prepare_comparison(tool, tool.refs)["compact_input"]
    assert all(h["accuracy"]["p50_m"] is None and h["accuracy"]["unknown_fixes"] > 0
               for h in compact["how_dictionary"].values())
    assert compact["how_limits"]["calibration"] == "synthetic_only"


def test_exact_same_kind_in_different_gap_runs_is_not_deduplicated_as_one_fact():
    tool, result = prepare("gap")
    compact = result["compact_input"]
    assert len(compact["how_dictionary"]) == 2
    first, second = compact["stamps"]
    assert first["how"][0]["use"] != second["how"][0]["use"]
    definitions = compact["how_dictionary"]
    assert definitions[first["how"][0]["use"]]["route_run"] != (
        definitions[second["how"][0]["use"]]["route_run"]
    )
    assert compact["how_limits"]["cross_route_run_continuity"] == "not_established"
    assert first["relations"] == second["relations"] == []
    assert resolve_how(tool, result, first["how"][0]["use"])["support"]["chain_index"] != (
        resolve_how(tool, result, second["how"][0]["use"])["support"]["chain_index"]
    )


def test_projection_does_not_select_optional_stamps_or_accept_missing_required_records():
    tool, _ = prepare("photo_turn")
    required = tuple(r for r in tool.refs if tool.resolve(r)["required"])
    result = prepare_comparison(tool, required)
    assert [s["id"] for s in result["compact_input"]["stamps"]] == [required[0].id]
    assert len(result["compact_input"]["how_dictionary"]) == 3
    with pytest.raises(ValueError, match="required"):
        prepare_comparison(tool, ())


@pytest.mark.parametrize("target", ["compact", "alias", "source", "metric"])
def test_changed_comparison_or_source_cannot_resolve_a_saved_alias(target):
    tool, result = prepare()
    alias = next(iter(result["manifest"]["how_bindings"]))
    if target == "compact":
        result["compact_input"]["how_dictionary"][alias]["kind"] = "invented"
    elif target == "alias":
        result["manifest"]["how_bindings"][alias]["material_ref"]["version"] = "0" * 64
    elif target == "metric":
        result["statistics"]["after_bytes"] = 0
    else:
        source = tool.dump()["source"]
        source["records"]["records"][1]["content"]["text"] = "changed"
        tool = StampTool("record_how", source)
    with pytest.raises(ValueError):
        resolve_how(tool, result, alias)


def test_numeric_byte_measurement_is_not_reported_as_tokens_or_cost():
    _, result = prepare()
    stats = result["statistics"]
    assert stats["before_bytes"] == json_size(result["baseline_input"])
    assert stats["after_bytes"] == json_size(result["compact_input"])
    assert stats["after_bytes"] < stats["before_bytes"]
    assert stats["repeated_definitions_removed"] == 2
    assert stats["token_usage"] is None and stats["llm_calls"] == 0
    assert json_size({"메모": "🐕"}) == len('{"메모":"🐕"}'.encode())


def test_displayed_json_preserves_float_spelling_and_matches_the_reported_size():
    _, result = prepare("photo_turn")
    display = comparison_display(result)
    assert display["all"]["before"]["bytes"] == result["statistics"]["before_bytes"]
    assert display["all"]["after"]["bytes"] == result["statistics"]["after_bytes"]
    assert '"tolerance_m": 8.0' in display["all"]["before"]["text"]
    for item in [display["all"], *display["by_stamp"].values()]:
        for side in item.values():
            assert json_size(json.loads(side["text"])) == side["bytes"]


def test_schema_and_anchor_resolution_for_writing_remain_compatible():
    tool, result = prepare()
    raw = {"title": "구조 검산", "cards": [
        {"stamp_id": s["id"], "title": "구조 검산", "text": "모델이 작성한 문장 아님"}
        for s in result["compact_input"]["stamps"]
    ]}
    board = accept_writing(tool, tool.refs, raw)
    assert [c["anchor"] for c in render(tool, board)["cards"]] == [tool.anchor(r) for r in tool.refs]
    assert verify_comparison(StampTool.load(tool.dump()), result) == result


def test_demo_saves_unsent_inputs_full_supports_and_reproducible_manifest(tmp_path):
    run(tmp_path, writing_comparison=True)
    saved = json.loads((tmp_path / "photo_turn/writing_comparison.json").read_text(encoding="utf-8"))
    book = json.loads((tmp_path / "photo_turn/stamp_book.json").read_text(encoding="utf-8"))
    assert verify_comparison(StampTool.load(book), saved) == saved
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "__CASE_DATA__" not in html
    assert 'id="before-json"' in html and 'id="after-json"' in html
    with pytest.raises(ValueError, match="empty output"):
        run(tmp_path, writing_comparison=True)
