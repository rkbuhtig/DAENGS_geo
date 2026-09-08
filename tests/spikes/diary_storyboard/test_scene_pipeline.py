"""Independent scene cores, shared background, failure isolation and frozen replay."""

import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from scripts.spikes.diary_storyboard import how_stamps, scene_pipeline
from scripts.spikes.diary_storyboard.how_demo import route
from scripts.spikes.diary_storyboard.how_stamp_demo import cases, source_with_records
from scripts.spikes.diary_storyboard.record_envelopes import payload_hash
from scripts.spikes.diary_storyboard.scene_background import BackgroundEnvelope, target_for
from scripts.spikes.diary_storyboard.scene_core import user_cores
from scripts.spikes.diary_storyboard.scene_pipeline import (
    ScenePolicy,
    background_requests,
    prepare_scene_plan,
    source_from_how,
)
from scripts.spikes.diary_storyboard.stamp_demo import RECORDS, REPO, read
from scripts.spikes.diary_storyboard.stamp_storyboard import accept_selection, writing_request
from scripts.spikes.diary_storyboard.stamp_tool import StampTool


def source():
    walk = route("common-background", [(0, 0, 0), (120, 120, 0), (180, 120, 0),
                                       (300, 240, 0), (340, 320, 0), (460, 440, 0)])
    return source_from_how(source_with_records(walk, [(6, "note", "  원문\n보존  ")]))


def tool(raw, **policy):
    return StampTool("action_background_v2", raw, {"target_scene_count": 3, **policy})


def envelope(core, eid, *, domain="space", status="known"):
    at = datetime.fromisoformat(core["event_at"])
    payload = ({"features": [{"id": eid, "name": "합성 공원", "distance_m": 40,
                              "geometry_reference": "representative_point"}]}
               if domain == "space" else {"temperature_c": 21, "precipitation_mm": 0})
    has_result = status in {"known", "partial", "empty"}
    if status == "empty":
        payload = {"features": []}
    return BackgroundEnvelope.model_validate({
        "id": eid, "target": target_for(core, radius_m=100 if domain == "space" else None),
        "tags": ["space.park" if domain == "space" else "environment.weather"],
        "status": status, "reason": "synthetic_failure" if status == "unavailable" else None,
        "provenance": {
            "provider": "synthetic-provider", "operation": domain,
            "retrieved_at": (at + timedelta(hours=1)).isoformat(),
            "temporal_basis": "lookup_snapshot" if domain == "space" else "event_observation",
            "valid_time": {"start_at": at, "end_at": at + timedelta(minutes=1)}
            if domain == "environment" else None,
            "policy_version": "synthetic-v1", "synthetic": True,
        },
        "payload_format": "synthetic-provider-response-v1",
        "payload": payload if has_result else None,
        "payload_sha256": payload_hash(payload) if has_result else None,
    }).model_dump(mode="json")


def with_background(raw, *, status="known"):
    raw = deepcopy(raw)
    plan = prepare_scene_plan(raw, ScenePolicy(target_scene_count=3))
    raw["background_envelopes"] = [envelope(core, f"{i}-{domain}", domain=domain, status=status)
                                   for i, core in enumerate(plan["cores"])
                                   for domain in ("space", "environment")]
    raw["selected_background_ids"] = [e["id"] for e in raw["background_envelopes"]]
    return raw


def test_user_core_constructor_has_no_route_or_background_dependency():
    records = source()["records"]["records"]
    cores = user_cores(records)
    assert cores[0]["action"]["content"]["text"] == "  원문\n보존  "
    assert cores[0]["location"] == records[0]["location"]
    assert "background" not in cores[0] and "how" not in cores[0]


def test_new_path_never_executes_the_old_how_assembler(monkeypatch):
    def forbidden(*args):
        raise AssertionError("old HOW assembly must not be a scene dependency")
    monkeypatch.setattr(how_stamps, "compile_how_stamps", forbidden)
    built = tool(with_background(source()))
    assert len(built.refs) == 3


def test_both_origins_use_the_same_background_contract_and_preserve_actions():
    raw = source()
    baseline = tool(raw)
    enriched = tool(with_background(raw))
    assert {enriched.project(r)["action"]["origin"] for r in enriched.refs} == {
        "user_record", "derived_observation"}
    for a, b in zip(baseline.refs, enriched.refs):
        before, after = baseline.project(a), enriched.project(b)
        assert before["action"] == after["action"]
        assert baseline.anchor(a) == enriched.anchor(b)
        for domain in ("space", "environment"):
            direct = [e for e in after["background"][domain] if e["relation_to_stamp"] == "same_core"]
            assert len(direct) == 1
            assert direct[0]["projection_status"] == "projected"
            assert direct[0]["applies_to_core"] == enriched.resolve(b)["core_ref"]
        assert a.version != b.version
        assert before["available_at"] < after["available_at"]
    selected = accept_selection(enriched, {"optional_stamp_ids": []})
    assert len(writing_request(enriched, selected)[0]["stamps"]) == 3


@pytest.mark.parametrize("route_status", ["unavailable", "not_requested"])
def test_no_route_still_keeps_record_and_its_direct_background(route_status):
    raw = source()
    raw.update(route=None, attachments=[], route_status=route_status,
               route_reason="missing_route" if route_status == "unavailable" else None)
    built = tool(with_background(raw))
    assert len(built.refs) == 1
    material = built.project(built.refs[0])
    assert material["action"]["content"] == raw["records"]["records"][0]["content"]
    assert material["background"]["trajectory"] == []
    assert material["background"]["space"][0]["projection_status"] == "projected"
    assert built.dump()["scene_plan"]["selection"]["scene_counts"]["remaining_deficit"] == 2


def test_motion_runtime_failure_is_frozen_and_replays_after_recovery(monkeypatch):
    raw = source()
    with monkeypatch.context() as patch:
        def fail(*args):
            raise RuntimeError("calculation unavailable")
        patch.setattr(scene_pipeline, "build_how", fail)
        built = tool(raw)
        assert len(built.refs) == 1
        book = built.dump()
        assert book["source"]["route_status"] == "unavailable"
        assert book["source"]["route"] == raw["route"]
    assert StampTool.load(book).query() == built.query()


def test_unlocated_note_gets_no_invented_query_target():
    raw = source()
    raw["attachments"] = []
    raw["records"]["records"][0].update(location=None, time_basis="session_fallback")
    plan = prepare_scene_plan(raw, ScenePolicy(target_scene_count=1))
    assert all(r["status"] == "not_requested" and r["target"]["point"] is None
               for r in background_requests(plan))
    built = tool(raw, target_scene_count=1)
    assert built.anchor(built.refs[0])["location"] is None


@pytest.mark.parametrize("status", ["unavailable", "empty"])
def test_failed_or_empty_background_does_not_remove_or_rewrite_either_origin(status):
    baseline = tool(source())
    built = tool(with_background(source(), status=status))
    assert [built.project(r)["action"] for r in built.refs] == [
        baseline.project(r)["action"] for r in baseline.refs]
    assert all(built.project(r)["background"]["current_query_status"]["space"] == [status]
               for r in built.refs)


@pytest.mark.parametrize("field", ["version", "session", "time", "point", "hash", "origin"])
def test_mismatched_background_never_silently_attaches(field):
    raw = with_background(source())
    e = raw["background_envelopes"][0]
    if field == "version":
        e["target"]["core_ref"]["version"] = "a" * 64
    elif field == "session":
        e["target"]["session_id"] = "another-walk"
    elif field == "time":
        e["target"]["event_at"] = "2026-09-08T06:00:00Z"
    elif field == "point":
        e["target"]["point"]["lat"] += 0.001
    elif field == "hash":
        e["payload"]["features"][0]["name"] = "unverified edit"
    else:
        e["provenance"]["synthetic"] = False
    with pytest.raises(ValueError):
        tool(raw)


def test_weather_validity_is_checked_and_lookup_time_is_not_event_weather():
    raw = with_background(source())
    weather = raw["background_envelopes"][1]
    weather["provenance"]["valid_time"]["start_at"] = "2026-09-09T00:00:00Z"
    weather["provenance"]["valid_time"]["end_at"] = "2026-09-09T01:00:00Z"
    with pytest.raises(ValueError, match="cover"):
        tool(raw)
    weather["provenance"].update(temporal_basis="lookup_snapshot", valid_time=None)
    material = tool(raw).query()[0]["material"]
    assert material["background"]["environment"][0]["projection_status"] == "not_event_weather"


def test_explicit_replacement_selects_one_saved_result_without_changing_core():
    raw = with_background(source())
    newer = deepcopy(raw["background_envelopes"][0])
    newer.update(id="newer", supersedes=newer["id"])
    newer["payload"]["features"][0]["distance_m"] = 55
    newer["payload_sha256"] = payload_hash(newer["payload"])
    raw["background_envelopes"].append(newer)
    raw["selected_background_ids"].append("newer")
    with pytest.raises(ValueError, match="multiple selected"):
        tool(raw)
    raw["selected_background_ids"].remove(newer["supersedes"])
    built = tool(raw)
    assert built.query()[0]["material"]["background"]["space"][0]["features"][0]["distance_m"] == 55


def test_prior_query_is_context_only_and_gps_gap_clears_background_slots():
    for name, expect_prior in (("all_records", True), ("gap", False)):
        raw = source_from_how(cases()[name]["source"])
        plan = prepare_scene_plan(raw, ScenePolicy(target_scene_count=0))
        first = plan["cores"][0]
        raw["background_envelopes"] = [envelope(first, "first-park")]
        raw["selected_background_ids"] = ["first-park"]
        built = tool(raw, target_scene_count=0)
        second = built.query()[1]["material"]["background"]
        assert bool(second["space"]) is expect_prior
        assert second["current_query_status"]["space"] == ["not_requested"]
        if expect_prior:
            assert second["space"][0]["relation_to_stamp"] == "prior_core_query"
            assert second["space"][0]["elapsed_s"] > 0


@pytest.mark.parametrize("name", list(cases()))
def test_supplement_choices_and_observed_anchors_match_the_previous_policy(name):
    raw = cases()[name]["source"]
    old = StampTool("action_background", raw, {"target_scene_count": 3})
    new = tool(source_from_how(raw))
    assert [r.id for r in new.refs] == [r.id for r in old.refs]
    assert new.dump()["scene_plan"]["selection"]["scene_counts"] == old.dump()["slot_audit"]["scene_counts"]
    for a, b in zip(old.refs, new.refs):
        assert old.project(a)["action"] == new.project(b)["action"]
        for key in ("event_at", "time_basis", "location"):
            assert old.anchor(a)[key] == new.anchor(b)[key]


def test_record_bound_saved_queries_migrate_without_route_or_retargeting():
    snapshot = read(RECORDS)
    built = tool({"session_id": snapshot["records"][0]["session_id"], "records": snapshot})
    assert len(built.refs) == len(snapshot["records"])
    for row in built.query():
        for domain in ("space", "environment", "other"):
            assert all(e["relation_to_stamp"] == "same_core" for e in row["material"]["background"][domain])


def test_saved_provider_collection_keeps_record_origin_and_failed_weather_distinct():
    snapshot = read(REPO / "docs/research/2026-09-08-record-envelope-collection/snapshot.json")
    built = tool({"session_id": snapshot["records"][0]["session_id"], "records": snapshot})
    assert snapshot["synthetic"] and snapshot["context_mode"] == "provider"
    assert len(built.refs) == len(snapshot["records"])
    assert [c["action"] for c in built.dump()["scene_plan"]["cores"]] == [
        c["action"] for c in sorted(user_cores(snapshot["records"]),
                                   key=lambda c: (c["event_at"], c["id"]))]
    weather = {e["id"]: e for row in built.query()
               for e in row["material"]["background"]["environment"]}
    expected = {e["id"]: e for e in snapshot["envelopes"] if "environment.weather" in e["tags"]
                and e["id"] in snapshot["selected_envelope_ids"]}
    assert weather.keys() == expected.keys()
    for eid, saved in expected.items():
        assert weather[eid]["status"] == saved["status"]
        assert weather[eid]["reason"] == saved["reason"]
        assert weather[eid]["temporal_basis"] == saved["provenance"]["temporal_basis"]
        assert weather[eid]["projection_status"] == "no_payload"
    assert StampTool.load(built.dump()).dump() == built.dump()


def test_new_background_queries_use_context_mode_for_both_core_origins():
    raw = with_background(source())
    raw["records"]["context_mode"] = "provider"
    for saved in raw["background_envelopes"]:
        saved["provenance"].update(synthetic=False, provider="test-provider")
        saved["payload_format"] = "test-provider-v1"
        if "environment.weather" in saved["tags"]:
            # A provider observation need not cover the walk's time or location.
            saved["provenance"].update(temporal_basis="source_observation", valid_time={
                "start_at": "2026-09-09T00:00:00Z", "end_at": "2026-09-09T01:00:00Z"})
    built = tool(raw)
    assert {built.anchor(r)["origin"] for r in built.refs} == {"user_record", "derived_observation"}
    assert all(e["projection_status"] == "not_supported" for row in built.query()
               for domain in ("space", "environment") for e in row["material"]["background"][domain])
    assert all(e["temporal_basis"] == "source_observation" for row in built.query()
               for e in row["material"]["background"]["environment"])
    assert StampTool.load(built.dump()).dump() == built.dump()
    raw["background_envelopes"][0]["provenance"]["synthetic"] = True
    with pytest.raises(ValueError, match="origin"):
        tool(raw)


def test_legacy_context_mode_absence_is_preserved_in_frozen_books():
    raw = source()
    raw["records"].pop("context_mode")
    legacy = tool(raw)
    assert "context_mode" not in legacy.dump()["source"]["records"]
    assert StampTool.load(legacy.dump()).dump() == legacy.dump()
    raw["records"]["context_mode"] = "synthetic"
    explicit = tool(raw)
    assert explicit.dump()["source"]["records"]["context_mode"] == "synthetic"
    assert explicit.source_version != legacy.source_version
    assert [explicit.project(r)["action"] for r in explicit.refs] == [
        legacy.project(r)["action"] for r in legacy.refs]


def test_core_refs_stay_stable_across_background_policy_but_stamps_do_not():
    raw = with_background(source())
    a, b = tool(raw), tool(raw, background={"trajectory_slots": 0})
    for x, y in zip(a.refs, b.refs):
        assert a.resolve(x)["core_ref"] == b.resolve(y)["core_ref"]
        assert x.version != y.version
        assert a.project(x)["action"] == b.project(y)["action"]


def test_stale_record_version_or_coordinate_is_not_hidden_as_motion_failure():
    raw = source()
    raw["records"]["records"][0]["location"]["point"]["lat"] += 0.001
    with pytest.raises(ValueError, match="exact observed"):
        tool(raw)


def test_scene_book_replay_checks_plan_and_preserves_all_returned_copies():
    built = tool(with_background(source()))
    book = json.loads(json.dumps(built.dump()))
    assert StampTool.load(book).query() == built.query()
    book["scene_plan"]["cores"][0]["action"]["content"]["text"] = "changed"
    with pytest.raises(ValueError, match="replay"):
        StampTool.load(book)
    projection = built.project(built.refs[0])
    projection["background"]["space"].clear()
    assert built.project(built.refs[0])["background"]["space"]
