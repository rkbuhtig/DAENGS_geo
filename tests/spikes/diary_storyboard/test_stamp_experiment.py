"""Pools, source-scoped stamps and the actual HTTP/parse boundary without network."""

import json
from copy import deepcopy

import httpx
import pytest

from scripts.spikes.diary_storyboard.selection_demo import ARCHIVE
from scripts.spikes.diary_storyboard.stamp_experiment import (
    execute,
    prepare,
    resolve_selection,
    resolve_writing,
    selection_request,
    writing_request,
)
from scripts.spikes.diary_storyboard.stamp_materials import (
    SlotPool,
    StampPolicy,
    build_stamps,
    compact_stamp,
)
from scripts.spikes.diary_storyboard.storage import digest, read, save


def source(name="actions"):
    return next(c for c in read(ARCHIVE)["cases"] if c["id"] == name)


def test_pool_replaces_by_recency_but_preserves_history_and_snapshot():
    pool = SlotPool("space", 2, 100)
    pool.put("a", {"value": "a"}, 0, 0)
    pool.put("b", {"value": "b"}, 1, 0)
    pool.put("a", {"value": "a-new"}, 2, 0)
    snapshot = pool.snapshot()
    pool.put("c", {"value": "c"}, 3, 0)
    assert list(pool.slots) == ["a", "c"] and len(pool.history) == 4
    assert pool.audit[-1] == {"at_s": 3, "key": "b", "reason": "capacity_eviction"}
    pool.advance(4, 1)
    assert not pool.slots and len(snapshot) == 2
    assert all(row["chain"] == 0 for row in snapshot)
    assert pool.audit[-1]["reason"] == "chain_reset"


def test_pool_expiry_future_rejection_and_snapshot_copy():
    pool = SlotPool("action", 2, 10)
    pool.put("a", {"data": {"name": "record"}}, 5, 0)
    snapshot = pool.snapshot()
    snapshot[0]["data"]["name"] = "mutated"
    assert pool.history[0]["data"]["name"] == "record"
    pool.advance(16, 0)
    assert not pool.snapshot() and pool.audit[-1]["reason"] == "expired"
    with pytest.raises(ValueError, match="chronological"):
        pool.advance(15, 0)


@pytest.mark.parametrize("name,count", [("movement", 7), ("actions", 9), ("gap", 10)])
def test_materials_keep_source_hash_times_chains_and_no_future_context(name, count):
    case = source(name)
    before = deepcopy(case)
    materials = build_stamps(case)
    events = {e["id"]: e for e in case["input"]["events"]}
    assert len(materials["stamps"]) == count
    for record in materials["stamps"]:
        s = record["snapshot"]
        event = events[s["anchor"]["event_id"]]
        assert s["anchor"]["support_s"] == [event["start_s"], event["end_s"]]
        assert s["anchor"]["support_s"][1] - s["anchor"]["support_s"][0] <= 300
        assert digest(s) == record["sha256"]
        assert all(events[i]["end_s"] <= event["end_s"] for i in record["source_event_ids"])
        assert all(events[i]["chain"] == event["chain"] for i in record["source_event_ids"])
        assert {"coordinates", "weather", "view"} <= set(s["unavailable"])
    assert case == before
    assert materials["pools"]["environment"]["status"] == "no_source"
    if name == "gap":
        assert any(a["reason"] == "chain_reset" for a in materials["pools"]["space"]["audit"])
        assert all(
            "e08" not in s["source_event_ids"]
            for s in materials["stamps"]
            if s["snapshot"]["chain"] == 1
        )


def test_photo_stamp_has_action_and_space_relative_times_without_action_duration():
    materials = build_stamps(source())
    stamp = next(s for s in materials["stamps"] if s["snapshot"]["id"] == "stamp:e07")
    s = stamp["snapshot"]
    assert s["anchor"]["support_s"] == [900, 900]
    assert s["relations"][0]["type"] == "after_action_record"
    assert s["relations"][0]["event_id"] == "e04" and s["relations"][0]["elapsed_s"] == 300
    assert s["relations"][1]["event_id"] == "e06" and s["relations"][1]["elapsed_s"] == 120
    assert s["relations"][1]["continuous_presence"] == "not_established"
    assert s["where"]["current"]["descriptor"]["relation"] == "near"
    assert "source_input_sha256" not in json.dumps(compact_stamp(stamp))
    assert len(materials["pools"]["action"]["history"]) == 2


def test_unknown_source_vocabulary_fails_without_guessing():
    case = source()
    event = next(e for e in case["input"]["events"] if e["role"] == "action")
    next(a for a in event["evidence"] if a["id"] == event["primary_evidence_id"])["text"] = (
        "unknown"
    )
    case["input_sha256"] = digest(case["input"])
    with pytest.raises(ValueError, match="unsupported archived action"):
        build_stamps(case)


def test_capacity_eviction_does_not_create_extra_stamps():
    small = build_stamps(source(), StampPolicy(space_slots=1))
    large = build_stamps(source(), StampPolicy(space_slots=5))
    assert [s["snapshot"]["id"] for s in small["stamps"]] == [
        s["snapshot"]["id"] for s in large["stamps"]
    ]
    assert any(a["reason"] == "capacity_eviction" for a in small["pools"]["space"]["audit"])


def test_selection_keeps_required_records_and_derives_usage():
    materials = build_stamps(source())
    _, contract = selection_request(materials)
    selection = resolve_selection(materials, contract(optional_stamp_ids=[]))
    assert selection["selected_stamp_ids"] == ["stamp:e04", "stamp:e07"]
    assert "e06" in selection["used_source_event_ids"]
    assert "stamp:e06" in selection["omitted_stamp_ids"]  # not a card, still used as context
    with pytest.raises(ValueError):
        contract(optional_stamp_ids=["stamp:e04"])
    with pytest.raises(ValueError, match="duplicate"):
        resolve_selection(materials, contract(optional_stamp_ids=["stamp:e03", "stamp:e03"]))


def test_writer_sees_only_selected_stamps_and_cannot_change_time_or_reference_omitted():
    materials = build_stamps(source())
    _, chooser = selection_request(materials)
    selection = resolve_selection(materials, chooser(optional_stamp_ids=[]))
    payload, contract = writing_request(materials, selection)
    assert {s["id"] for s in payload["stamps"]} == {"stamp:e04", "stamp:e07"}
    cards = [
        {"stamp_id": i, "title": "fixture", "text": "fixture"}
        for i in selection["selected_stamp_ids"]
    ]
    result = resolve_writing(materials, selection, contract(title="fixture", cards=cards))
    assert result["cards"][1]["anchor"]["support_s"] == [900, 900]
    cards[0]["stamp_id"] = "stamp:e12"
    with pytest.raises(ValueError):
        contract(title="fixture", cards=cards)
    cards[0]["stamp_id"] = "stamp:e07"
    with pytest.raises(ValueError, match="exactly once"):
        resolve_writing(materials, selection, contract(title="fixture", cards=cards))


def mock_model(monkeypatch, sent, malformed=False):
    def respond(request):
        body = json.loads(request.content)
        sent.append(body)
        payload = json.loads(body["contents"][0]["parts"][0]["text"])
        if "optional" in payload:
            answer = {"optional_stamp_ids": [s["id"] for s in payload["optional"][:1]]}
        else:
            answer = {
                "title": "fixture",
                "cards": [
                    {"stamp_id": s["id"], "title": "fixture", "text": "fixture"}
                    for s in payload["stamps"]
                ],
            }
        if malformed:
            answer = {"bad": True}
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]}}
                ],
                "usageMetadata": {"totalTokenCount": 20},
                "modelVersion": "fake",
            },
        )

    client = httpx.Client
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )


def test_bounded_http_pipeline_and_resume_preserve_raw_and_derived_outputs(tmp_path, monkeypatch):
    sent = []
    mock_model(monkeypatch, sent)
    manifest = prepare(tmp_path)
    assert not sent and manifest["max_attempts"] == 6
    result = execute(tmp_path)
    assert result["attempts"] == 6 and len(sent) == 6
    assert execute(tmp_path) == result and len(sent) == 6
    for case in ("movement", "actions", "gap"):
        raw = read(tmp_path / case / "write/calls/000001/response.json")
        accepted = read(tmp_path / case / "write/accepted.json")
        assert "anchor" not in raw["cards"][0] and "anchor" in accepted["cards"][0]
    path = tmp_path / "actions/select/accepted.json"
    damaged = read(path)
    damaged["selected_stamp_ids"] = []
    save(path, damaged)
    with pytest.raises(ValueError, match="accepted output changed"):
        execute(tmp_path)


def test_rejected_selection_skips_writing_and_never_retries(tmp_path, monkeypatch):
    sent = []
    mock_model(monkeypatch, sent, malformed=True)
    result = execute(tmp_path)
    assert result["attempts"] == 3 and len(sent) == 3
    assert not list(tmp_path.glob("*/write/accepted.json"))
    assert execute(tmp_path) == result and len(sent) == 3


def test_changed_prompts_or_interrupted_attempt_require_explicit_new_experiment(
    tmp_path, monkeypatch
):
    from scripts.spikes.diary_storyboard.stamp_experiment import PROMPTS

    prepare(tmp_path)
    (tmp_path / "movement/select/calls/000001").mkdir(parents=True)
    sent = []
    mock_model(monkeypatch, sent)
    result = execute(tmp_path)
    assert result["attempts"] == 5 and len(sent) == 4
    assert result["unknown_usage_attempts"] == 1
    monkeypatch.setitem(PROMPTS, "stamp_select", "changed")
    with pytest.raises(ValueError, match="experiment changed"):
        prepare(tmp_path)
