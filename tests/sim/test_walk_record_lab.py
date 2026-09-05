"""Observable semantics: delivery-time capture, deletion, attribution and bounded evidence."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.spikes.storyboard_and_regions.sources import fingerprint
from scripts.spikes.walk_record_lab.context import ContextReader
from scripts.spikes.walk_record_lab.core import Experiment, prepare, summarize
from scripts.spikes.walk_record_lab.server import create_app

ROOT = Path(__file__).resolve().parents[2]


def scenario():
    value = json.loads((ROOT / "scripts/sim/walk/examples/sniff-and-go.json").read_text())
    value.update(sensor={"kind": "perfect", "sample_interval_s": 5, "accuracy_m": 3},
                 faults=[], delivery={})
    return value


def run(value, taps, **kwargs):
    experiment = Experiment(scenario=value, taps=taps, **kwargs)
    artifacts, entries = prepare(experiment)
    return summarize(experiment, artifacts, entries, {})


def tap(code="sniffing", at=20, id="a", note=""):
    return {"id": id, "at_s": at, "code": code, "note": note}


def test_uses_latest_capture_already_delivered_not_truth_or_last_arrival():
    spec = scenario()
    spec["delivery"] = {"batch_size": 3, "reverse_within_batch": True,
                        "duplicate_at_s": [5], "base_latency_s": 1}
    result = run(spec, [tap(at=10), tap(at=12, id="b")])
    assert result["entries"][0]["accepted"] is False
    assert result["entries"][1]["fix_age_s"] == 2
    assert result["entries"][1]["sample_id"] == "sample-000002"


def test_stale_and_bad_accuracy_reject_behavior_but_keep_unlocated_note():
    spec = scenario()
    spec["faults"] = [{"kind": "dropout", "id": "gap", "start_s": 30, "end_s": 80},
                      {"kind": "accuracy", "id": "bad", "start_s": 100, "end_s": 120,
                       "accuracy_m": 85}]
    result = run(spec, [tap(at=60), tap("note", at=60, id="memo", note="쉼"),
                        tap(at=110, id="bad")])
    assert [e["accepted"] for e in result["entries"]] == [False, True, False]
    assert result["entries"][1]["location"] is None
    assert result["profile"]["evidence_ids"] == []


def test_delete_recomputes_all_views_and_profile_but_scene_omission_keeps_evidence():
    entries = [tap(id="a"), tap("barking", at=50, id="b"),
               tap("note", at=70, id="memo", note="사진")]
    first = run(scenario(), entries, scene_limit=2)
    assert first["omitted_entry_ids"] == ["a", "b", "memo"]
    assert first["profile"]["evidence_ids"] == ["a", "b"]
    deleted = run(scenario(), entries[1:], scene_limit=2)
    assert deleted["profile"]["counts"]["sniffing"]["entry_count"] == 0
    assert deleted["profile"]["evidence_ids"] == ["b"]
    assert deleted["source_revision"] != first["source_revision"]
    assert all(row["entry_id"] != "a" for row in deleted["rows"])


def test_empty_walk_has_start_and_end_no_invented_behavior():
    result = run(scenario(), [])
    assert len(result["scenes"]) == 2
    assert result["profile"]["walk_count"] == 1
    assert result["profile"]["evidence_ids"] == []


def test_position_spike_is_measured_separately_and_never_replaced_with_truth():
    spec = scenario()
    spec["faults"] = [{"kind": "position_offset", "id": "spike", "at_s": 20,
                       "east_m": 260, "north_m": 0}]
    result = run(spec, [tap()])
    assert result["entries"][0]["accepted"]
    assert result["evaluation_only"]["anchor_errors"][0]["capture_position_error_m"] > 259
    clean = run(scenario(), [tap()])
    assert result["entries"][0]["location"] != clean["entries"][0]["location"]


def test_remaining_pin_reuses_snapshot_after_first_pin_deleted(tmp_path):
    entries = run(scenario(), [tap(), tap(id="b", at=25)])["entries"]
    loc = entries[0]["location"]
    params = {"cx": round(loc["lng"], 6), "cy": round(loc["lat"], 6), "radius": 250}
    receipt = {"source": "commerce", "status": "known", "query": params, "rows": []}
    (tmp_path / f"commerce-{fingerprint(params)[:16]}.json").write_text(json.dumps(receipt))
    contexts, stats = ContextReader(tmp_path).contexts(entries[1:], "common")
    assert contexts["b"]["sources"][0]["status"] == "known"
    assert stats["query_groups_fetched"] == 0


def test_note_cannot_leak_into_behavior_or_request_context(tmp_path):
    result = run(scenario(), [tap("note", note="짖었다", at=30)])
    reader = ContextReader(tmp_path)
    contexts, stats = reader.contexts(result["entries"], "common", True)
    assert contexts == {}
    assert stats["commerce_anchors"] == 0
    assert result["profile"]["counts"]["barking"]["entry_count"] == 0


def test_behavior_policy_avoids_excretion_lookup_and_common_shares_nearby_anchor(tmp_path):
    entries = run(scenario(), [tap("excretion"), tap(at=21, id="b")])["entries"]
    reader = ContextReader(tmp_path)
    contexts, stats = reader.contexts(entries, "behavior")
    assert contexts["a"]["status"] == "routine_only"
    assert stats["commerce_anchors"] == 1
    contexts, stats = reader.contexts(entries, "common")
    assert stats["commerce_anchors"] == 1
    assert contexts["a"]["sources"][0]["status"] == "cache_missing"
    assert list(tmp_path.iterdir()) == []


def test_partial_source_keeps_status_and_no_raw_contacts(tmp_path):
    entries = run(scenario(), [tap()])["entries"]
    loc = entries[0]["location"]
    params = {"cx": round(loc["lng"], 6), "cy": round(loc["lat"], 6), "radius": 250}
    receipt = {"source": "commerce", "status": "partial", "query": params,
               "rows": [{"lat": loc["lat"], "lon": loc["lng"], "indsLclsNm": "음식",
                         "phoneNumber": "secret-contact", "bizesNm": "raw-name"}]}
    (tmp_path / f"commerce-{fingerprint(params)[:16]}.json").write_text(json.dumps(receipt))
    contexts, _ = ContextReader(tmp_path).contexts(entries, "common")
    assert contexts["a"]["sources"][0]["status"] == "partial"
    assert contexts["a"]["facts"]
    assert "secret-contact" not in json.dumps(contexts)
    assert "raw-name" not in json.dumps(contexts)


def test_http_rejects_cross_origin_and_invalid_tap(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/record-lab/config").json()["can_fetch"] is False
        payload = {"scenario": scenario(), "taps": [tap(at=99999)]}
        assert client.post("/record-lab/run", json=payload).status_code == 422
        assert client.post("/record-lab/run", json=payload,
                           headers={"origin": "https://other.invalid"}).status_code == 403


@pytest.mark.parametrize("entries", [[tap(), tap()], [tap("note")], [tap(note="hidden")]])
def test_invalid_entry_contract(entries):
    with pytest.raises(ValueError):
        Experiment(scenario=scenario(), taps=entries)
