"""Record/envelope boundaries before collectors, proximity UI, or LLM integration."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.spikes.diary_storyboard.record_envelopes import RecordEnvelopeSnapshot

FIXTURE = (Path(__file__).parents[3] / "scripts/spikes/diary_storyboard/fixtures"
           / "record_envelopes.json")


def read_sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_user_writing_and_behavior_at_same_point_keep_separate_identity():
    snapshot = RecordEnvelopeSnapshot.model_validate(read_sample())
    behavior, note, photo = snapshot.records[:3]
    assert behavior.location.point == note.location.point
    assert behavior.ref.key != note.ref.key
    assert note.content.kind == "note" and photo.content.kind == "photo"
    # Raw text remains user writing, not a normalized behavior or generated summary.
    roundtrip = RecordEnvelopeSnapshot.model_validate_json(snapshot.model_dump_json())
    assert roundtrip.records[1].content.text == read_sample()["records"][1]["content"]["text"]
    assert "pet_id" not in roundtrip.records[1].content.model_dump()


def test_late_note_queries_event_time_and_legacy_authorship_stays_unknown():
    snapshot = RecordEnvelopeSnapshot.model_validate(read_sample())
    note = snapshot.records[3]
    weather = next(e for e in snapshot.envelopes if e.id == "weather-historical")
    assert note.authored_at.date() > note.event_at.date()
    assert weather.target.event_at == note.event_at != note.authored_at
    assert snapshot.records[5].authored_at is None


def test_pinless_writing_stays_a_record_and_does_not_gain_a_coordinate():
    snapshot = RecordEnvelopeSnapshot.model_validate(read_sample())
    note = snapshot.records[4]
    envelope = next(e for e in snapshot.envelopes if e.id == "unlocated-not-requested")
    assert note.location is None and note.content.text
    assert envelope.status == "not_requested" and envelope.target.point is None


def test_append_preserves_originals_and_selects_one_result():
    raw = read_sample()
    before = copy.deepcopy(raw["records"])
    snapshot = RecordEnvelopeSnapshot.model_validate(raw)
    assert raw["records"] == before
    assert {"park-01", "park-02"} <= {e.id for e in snapshot.envelopes}
    assert "park-02" in snapshot.selected_envelope_ids
    assert "park-01" not in snapshot.selected_envelope_ids


def test_same_instant_with_different_timezone_cannot_duplicate_selected_query():
    data = read_sample()
    duplicate = copy.deepcopy(data["envelopes"][-1])
    duplicate.update(id="park-independent-retry", supersedes=None)
    duplicate["target"]["event_at"] = "2026-09-07T06:03:00Z"
    data["envelopes"].append(duplicate)
    data["selected_envelope_ids"].append(duplicate["id"])
    with pytest.raises(ValidationError, match="same query scope"):
        RecordEnvelopeSnapshot.model_validate(data)


def test_records_are_valid_before_any_collector_has_run():
    data = read_sample()
    data.update(envelopes=[], selected_envelope_ids=[])
    snapshot = RecordEnvelopeSnapshot.model_validate(data)
    assert len(snapshot.records) == 6


@pytest.mark.parametrize("case", [
    "stale_revision", "unknown_record", "other_owner", "location_invented", "authorship_query",
    "naive_time", "raw_payload_changed", "empty_is_not_failure", "unlocated_query",
    "note_as_behavior", "photo_without_location", "unknown_tag", "duplicate_record",
    "wrong_historical_time", "replacement_other_target", "replacement_cycle",
    "both_versions_selected", "duplicate_selection", "synthetic_disguised",
    "wrong_route_time", "behavior_wrong_pet", "note_wrong_store",
])
def test_rejects_invalid_material_association(case):
    data = read_sample()
    first = data["envelopes"][0]
    if case == "stale_revision":
        first["target"]["record"]["version"] = "stale"
    elif case == "unknown_record":
        first["target"]["record"]["id"] = "missing"
    elif case == "other_owner":
        data["records"][0]["owner_id"] = "another-owner"
    elif case == "location_invented":
        first["target"]["point"]["lat"] += 0.01
    elif case == "authorship_query":
        data["envelopes"][4]["target"]["event_at"] = data["records"][3]["authored_at"]
    elif case == "naive_time":
        data["records"][1]["authored_at"] = "2026-09-07T15:03:00"
    elif case == "raw_payload_changed":
        first["payload"]["features"][0]["distance_m"] = 0
    elif case == "empty_is_not_failure":
        data["envelopes"][6]["status"] = "empty"
    elif case == "unlocated_query":
        data["envelopes"][5]["target"]["point"] = {"lat": 0, "lng": 0}
    elif case == "note_as_behavior":
        data["records"][1]["content"]["code"] = "sniffing"
    elif case == "photo_without_location":
        data["records"][2]["location"] = None
    elif case == "unknown_tag":
        first["tags"] = ["emotion.happy"]
    elif case == "duplicate_record":
        data["records"].append(copy.deepcopy(data["records"][0]))
    elif case == "wrong_historical_time":
        data["envelopes"][4]["provenance"]["valid_time"] = {
            "start_at": "2026-09-08T15:00:00+09:00", "end_at": "2026-09-08T16:00:00+09:00",
        }
    elif case == "replacement_other_target":
        data["envelopes"][-1]["supersedes"] = "river-01"
    elif case == "replacement_cycle":
        first["supersedes"] = "park-02"
    elif case == "both_versions_selected":
        data["selected_envelope_ids"].append("park-01")
    elif case == "duplicate_selection":
        data["selected_envelope_ids"].append("park-02")
    elif case == "synthetic_disguised":
        first["provenance"]["synthetic"] = False
    elif case == "wrong_route_time":
        data["records"][3]["location"]["captured_at"] = "2026-09-07T15:07:00+09:00"
    elif case == "behavior_wrong_pet":
        data["records"][0]["content"]["pet_id"] = "another-pet"
    elif case == "note_wrong_store":
        data["records"][1]["ref"]["store"] = "walk_photo"
    with pytest.raises(ValidationError):
        RecordEnvelopeSnapshot.model_validate(data)
