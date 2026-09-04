"""Credential-safe collection and explicit coverage for the storyboard experiment."""

import json

import httpx
import pytest

from scripts.spikes.storyboard_and_regions.sources import collect, service_key


def page(rows, total, code="00"):
    return {"header": {"resultCode": code}, "body": {"items": rows, "totalCount": total}}


def collect_pages(tmp_path, pages, **kwargs):
    calls = []

    def respond(request):
        calls.append(request)
        item = pages[len(calls)-1]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            return httpx.Response(item)
        return httpx.Response(200, json=item)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = collect("parks", {}, key="private-key+/=", cache_dir=tmp_path,
                         client=client, **kwargs)
    return result, calls


def test_complete_pagination_and_offline_cache(tmp_path):
    result, calls = collect_pages(tmp_path, [page([{"id": 1}, {"id": 2}], 3),
                                            page({"item": [{"id": 3}]}, 3)])
    assert result["status"] == "known"
    assert result["rows"] == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert calls[0].url.params["serviceKey"] == "private-key+/="
    assert calls[1].url.params["pageNo"] == "2"
    cached, later_calls = collect_pages(tmp_path, [])
    assert cached == result and later_calls == []
    for path in tmp_path.iterdir():
        assert "private-key" not in path.read_text(encoding="utf-8")
        assert "serviceKey" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("pages", "status", "failure"), [
    ([page([], 0, "03")], "known", None),
    ([503], "fetch_failed", "http_503"),
    ([page([], 0, "30")], "fetch_failed", "provider_rejected"),
    ([[]], "parse_failed", "invalid_provider_response"),
    ([{"header": None}], "parse_failed", "invalid_provider_response"),
    ([page([{"id": 1}], 2), page([{"id": 2}], 3)],
     "partial", "total_changed_during_pagination"),
    ([page([{"id": 1}], 2), page([{"id": 1}], 2)], "partial", "repeated_page"),
    ([page([{"id": 1}], 2), httpx.ConnectError("secret request URL")],
     "partial", "transport_failed"),
])
def test_no_results_failures_and_partial_stay_distinct(tmp_path, pages, status, failure):
    result, _ = collect_pages(tmp_path, pages)
    assert result["status"] == status
    assert result["failure"] == failure
    assert "secret request URL" not in json.dumps(result)


def test_page_budget_is_not_complete(tmp_path):
    result, _ = collect_pages(tmp_path, [page([{"id": 1}], 2)], max_pages=1)
    assert result["status"] == "partial"
    assert result["failure"] == "page_budget_exhausted"


def test_portal_key_decodes_once(monkeypatch):
    monkeypatch.setenv("DAENGS_DATA_GO_KR_SERVICE_KEY", "test%2Bkey%2F%3D")
    assert service_key() == "test+key/="
