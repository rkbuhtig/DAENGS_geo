from unittest.mock import AsyncMock

import httpx

from app.ingest.kto import fetch_pet_detail, source_records
from app.place.source_facts.states import DetailAcquisitionState


def _payload(item) -> dict:
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {"items": {"item": item}},
        }
    }


async def test_detail_fetch_distinguishes_no_data_from_failure() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=_payload([])))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_pet_detail(client, "1")

    assert result.state is DetailAcquisitionState.NO_DATA
    assert result.detail is None


async def test_detail_fetch_preserves_source_payload() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json=_payload(
                {
                    "contentid": "1",
                    "acmpyTypeCd": "전구역 동반가능",
                    "acmpyNeedMtr": "",
                }
            ),
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_pet_detail(client, "1")

    assert result.state is DetailAcquisitionState.FETCHED
    assert result.detail == {"acmpyTypeCd": "전구역 동반가능"}


async def test_exhausted_rate_limit_is_fetch_failed(monkeypatch) -> None:
    sleeps = AsyncMock()
    monkeypatch.setattr("app.ingest.kto.asyncio.sleep", sleeps)
    transport = httpx.MockTransport(lambda _: httpx.Response(429))

    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_pet_detail(client, "1")

    assert result.state is DetailAcquisitionState.FETCH_FAILED
    assert sleeps.await_count == 4


def test_shadow_list_keeps_hidden_items_filtered_from_product() -> None:
    records = source_records([
        {"contentid": "1", "title": "노출", "showflag": "1"},
        {"contentid": "2", "title": "숨김", "showflag": "0"},
    ])

    assert {record["source_ref"] for record in records} == {"1", "2"}
