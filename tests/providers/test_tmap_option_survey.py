import httpx
import pytest

from app.providers.base import LatLng
from app.usage.gate import UsageGate, usage_request_scope
from app.usage.ledger import InMemoryLedger
from app.usage.models import UsageDenied
from app.usage.policy import BoundedDevPolicy, DenyAllPolicy
from scripts.tmap_option_survey import Fetcher, Node, Pair


class SpyClient:
    def __init__(self):
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        return httpx.Response(
            200,
            json={"features": []},
            request=httpx.Request("POST", "https://example.test/route"),
        )


def pair() -> Pair:
    return Pair(
        "gangnam",
        Node(1, "출발", LatLng(37.5, 127.0)),
        Node(2, "도착", LatLng(37.51, 127.01)),
        1000,
    )


async def test_tmap_survey_denial_never_reaches_http_client(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.tmap_option_survey.settings.tmap_app_key", "test-key")
    client = SpyClient()
    fetcher = Fetcher(
        "tmap",
        tmp_path,
        0,
        max_live_calls=1,
        gate=UsageGate(DenyAllPolicy(), InMemoryLedger()),
        client=client,  # type: ignore[arg-type]
    )

    async with usage_request_scope():
        with pytest.raises(UsageDenied) as denied:
            await fetcher.fetch(pair(), "recommended")

    assert denied.value.code == "policy_denied"
    assert client.calls == 0


async def test_tmap_survey_explicit_batch_limit_stops_second_http_call(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.tmap_option_survey.settings.tmap_app_key", "test-key")
    client = SpyClient()
    fetcher = Fetcher(
        "tmap",
        tmp_path,
        0,
        max_live_calls=1,
        gate=UsageGate(BoundedDevPolicy(), InMemoryLedger()),
        client=client,  # type: ignore[arg-type]
    )

    async with usage_request_scope():
        await fetcher.fetch(pair(), "recommended")
        with pytest.raises(UsageDenied) as denied:
            await fetcher.fetch(pair(), "main_road")

    assert denied.value.code == "request_limit"
    assert client.calls == 1
