"""Actual collector boundary with a fake HTTP transport: no production key or DB."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from scripts.spikes.diary_storyboard.collect_record_envelopes import collect_snapshot, save_run
from scripts.spikes.diary_storyboard.envelope_sources import PublicDataReader
from scripts.spikes.diary_storyboard.record_envelopes import RecordEnvelopeSnapshot

FIXTURE = Path(__file__).parents[3] / "scripts/spikes/diary_storyboard/fixtures/record_envelopes_gangnam.json"


def sample():
    return RecordEnvelopeSnapshot.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def page(rows, total=None, code="00"):
    return {"header": {"resultCode": code}, "body": {"items": rows, "totalCount": len(rows) if total is None else total}}


def reader_for(tmp_path, respond, **kwargs):
    return PublicDataReader(tmp_path, fetch=True, key="test-secret-key+/=",
                            client=httpx.Client(transport=httpx.MockTransport(respond)), **kwargs)


def test_all_record_kinds_share_queries_keep_originals_and_replay_without_network(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if "AsosHourly" in str(request.url.path):
            assert request.url.params["startDt"] == "20260907"  # Not next-day authorship.
            rows = [{"stnId": "108", "stnNm": "Seoul", "tm": "2026-09-07 15:00",
                     "ta": "24", "rn": "", "hm": "60", "secret": "not-public"}]
        elif "storeListInRadius" in str(request.url.path):
            rows = [{"bizesId": "shop-1", "lat": "37.48928", "lon": "127.05633",
                     "indsLclsNm": "food", "tel": "do-not-export"}]
        elif "park" in str(request.url.path):
            rows = [{"manageNo": "park-1", "parkNm": "Example park", "latitude": "37.48928",
                     "longitude": "127.05633", "phoneNumber": "do-not-export"}]
        else:
            rows = []
        return httpx.Response(200, json=page(rows))

    original = sample()
    reader = reader_for(tmp_path / "private", respond)
    result = collect_snapshot(original, reader)
    assert result.records == original.records
    assert result.synthetic and result.context_mode == "provider"
    assert len(result.envelopes) == 24 and len(calls) == 6
    assert {r.content.kind for r in result.records} == {"behavior", "note", "photo"}
    assert sum(e.status == "not_requested" for e in result.envelopes) == 4
    weather = [e for e in result.envelopes if e.tags == ("environment.weather",) and e.payload]
    assert len(weather) == 5 and all(e.provenance.temporal_basis == "source_observation" for e in weather)
    assert weather[0].payload["items"][0]["relation"]["at_pin"] is False
    assert all(e.payload["items"][0]["provider_fields"]["rn"] == "" for e in weather)
    output = tmp_path / "public"
    save_run(output, original, result, reader)
    public = (output / "snapshot.json").read_text(encoding="utf-8")
    assert "do-not-export" not in public and "not-public" not in public
    assert "test-secret" not in public

    def forbidden(_):
        raise AssertionError("offline replay attempted HTTP")

    offline = PublicDataReader(tmp_path / "private", client=httpx.Client(transport=httpx.MockTransport(forbidden)))
    replay = collect_snapshot(original, offline)
    assert replay == result and offline.requests == 0 and offline.cache_hits == 6
    assert collect_snapshot(result, offline) == result  # No duplicate append on a repeated read.


@pytest.mark.parametrize(("responses", "status", "reason"), [
    ([page([], code="03")], "empty", None),
    ([403], "unavailable", "http_403"),
    ([page([], code="30")], "unavailable", "provider_rejected"),
    ([{"bad": "shape"}], "unavailable", "invalid_provider_response"),
    ([page([{"id": 1}], 2), 503], "partial", "http_503"),
    ([page([{"id": 1}], 2), page([{"id": 1}], 2)], "partial", "repeated_page"),
    ([page([{"id": 1}], 2), page([{"id": 2}], 3)], "partial", "total_changed"),
    ([page([], 2)], "partial", "pagination_mismatch"),
])
def test_empty_failure_and_partial_are_distinct(tmp_path, responses, status, reason):
    remaining = iter(responses)

    def respond(_):
        body = next(remaining)
        return httpx.Response(body) if isinstance(body, int) else httpx.Response(200, json=body)

    receipt = reader_for(tmp_path, respond).read("parks", {})
    assert (receipt["status"], receipt["reason"]) == (status, reason)


def test_failed_secret_echo_and_exception_are_not_written(tmp_path):
    secret = "test-secret-key+/="

    def respond(request):
        raise httpx.ConnectError("connection to " + str(request.url), request=request)

    reader = reader_for(tmp_path / "exception", respond)
    receipt = reader.read("parks", {})
    assert receipt["reason"] == "transport_failed"
    reader = reader_for(tmp_path / "echo", lambda _: httpx.Response(200, json=page([{"echo": secret}])))
    assert reader.read("parks", {})["reason"] == "credential_echo_rejected"
    for path in tmp_path.rglob("*.json"):
        assert secret not in path.read_text(encoding="utf-8")
        assert "serviceKey" not in path.read_text(encoding="utf-8")


def test_budget_counts_actual_pages_and_no_implicit_retry(tmp_path):
    reader = reader_for(tmp_path, lambda _: httpx.Response(200, json=page([{"id": 1}], 2)), max_requests=1)
    receipt = reader.read("parks", {})
    assert reader.requests == 1 and receipt["reason"] == "request_budget_exhausted"
    assert receipt["status"] == "partial"
    skipped = reader.read("rivers", {})
    assert skipped["status"] == "not_requested" and skipped["retrieved_at"] is None
    assert reader.requests == 1


def test_page_budget_is_not_a_complete_result(tmp_path):
    reader = reader_for(tmp_path, lambda _: httpx.Response(200, json=page([{"id": 1}], 2)), max_pages=1)
    assert reader.read("parks", {})["reason"] == "page_budget_exhausted"


def test_cache_only_missing_and_failed_cache_never_fetch(tmp_path):
    calls = []
    reader = reader_for(tmp_path, lambda r: calls.append(r) or httpx.Response(403))
    reader.read("parks", {})
    # Explicit fetch still uses a failure cache unless refresh is requested.
    second = reader_for(tmp_path, lambda r: calls.append(r) or httpx.Response(200, json=page([])))
    assert second.read("parks", {})["status"] == "unavailable" and len(calls) == 1
    offline = PublicDataReader(tmp_path / "missing")
    assert offline.read("parks", {})["reason"] == "cache_missing"


def test_refresh_preserves_prior_receipt_and_appends_record_envelopes(tmp_path):
    before = sample().model_copy(update={"records": sample().records[:1]})
    first_reader = reader_for(tmp_path, lambda _: httpx.Response(200, json=page([])))
    first = collect_snapshot(before, first_reader)
    old_receipts = {p.name for p in (tmp_path / "receipts").glob("*.json")}
    refresh = reader_for(tmp_path, lambda _: httpx.Response(403), refresh=True)
    result = collect_snapshot(first, refresh)
    assert len(result.envelopes) == 8
    assert result.records == first.records
    assert all(e.supersedes is not None for e in result.envelopes[4:])
    assert set(result.selected_envelope_ids) == {e.id for e in result.envelopes[4:]}
    assert old_receipts <= {p.name for p in (tmp_path / "receipts").glob("*.json")}


def test_modified_cache_cannot_silently_change_a_record_material(tmp_path):
    reader_for(tmp_path, lambda _: httpx.Response(200, json=page([]))).read("parks", {})
    path = next(tmp_path.glob("parks-*.json"))
    content = json.loads(path.read_text(encoding="utf-8"))
    content["rows"] = [{"invented": "location"}]
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        PublicDataReader(tmp_path).read("parks", {})


def test_missing_coordinates_and_projection_cap_do_not_become_empty_or_complete(tmp_path):
    record = sample().model_copy(update={"records": sample().records[:1]})
    rows = [{"latitude": "37.48928", "longitude": "127.05633", "parkNm": "park"}] * 3
    reader = reader_for(tmp_path, lambda _: httpx.Response(200, json=page(rows)))
    result = collect_snapshot(record, reader, max_items=1)
    park = result.envelopes[0]
    assert park.status == "partial" and park.reason == "projection_limit"
    assert park.payload["coverage"]["matched_rows"] == 3
    river = result.envelopes[1]
    assert river.status == "partial" and river.reason == "unusable_source_rows"
    assert river.payload["coverage"]["unusable_rows"] == 3


def test_outside_area_is_not_reported_as_an_empty_neighborhood(tmp_path):
    data = copy.deepcopy(sample().model_dump(mode="json"))
    for record in data["records"]:
        if record["location"]:
            record["location"]["point"] = {"lat": 0, "lng": 0}
    reader = PublicDataReader(tmp_path)
    result = collect_snapshot(RecordEnvelopeSnapshot.model_validate(data), reader)
    assert reader.requests == 0 and reader.memory == {}
    assert all(e.status == "not_requested" for e in result.envelopes)


def test_old_synthetic_envelopes_cannot_be_relabelled_as_live(tmp_path):
    path = FIXTURE.with_name("record_envelopes.json")
    original = RecordEnvelopeSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="records-only"):
        collect_snapshot(original, PublicDataReader(tmp_path))
