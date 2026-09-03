"""점령지 앱 계약과 dev 검수 계약은 같은 저장소를 읽되 다른 정보를 노출한다."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import get_session
from app.features.territory.game.dev_api import router as dev_router
from app.main import app
from tests.conftest import db_session

LAT, LNG = 37.4979, 130.9000
BBOX = {"south": LAT - 0.01, "north": LAT + 0.01, "west": LNG - 0.01, "east": LNG + 0.01}
SOURCE = "test:territory-sites"
ROOT = Path(__file__).resolve().parents[2]


async def _seed(session, n: int) -> None:
    await session.execute(
        text("""
        INSERT INTO territory_site (site_id, source, kind, location)
        SELECT :src || ':' || g, :src,
               CASE WHEN g % 2 = 0 THEN '한전주' ELSE '전용주' END,
               ST_SetSRID(ST_MakePoint(:lng + g * 0.00001, :lat), 4326)::geography
        FROM generate_series(1, :n) AS g
        """),
        {"src": SOURCE, "lat": LAT, "lng": LNG, "n": n},
    )


async def _get(target: FastAPI, session, path: str, params: dict) -> tuple[int, dict]:
    target.dependency_overrides[get_session] = lambda: session
    try:
        transport = ASGITransport(app=target)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get(path, params=params)
        return response.status_code, response.json()
    finally:
        target.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seeded", "limit", "expected_count", "expected_truncated"),
    [(3, 5, 3, False), (5, 5, 5, False), (6, 5, 5, True)],
)
async def test_nearby_truncated_flips_exactly_after_limit(
    seeded: int, limit: int, expected_count: int, expected_truncated: bool
) -> None:
    async with db_session() as session:
        try:
            await _seed(session, seeded)
            status, body = await _get(
                app,
                session,
                "/territory/sites/nearby",
                {"lat": LAT, "lng": LNG, "radius_m": 500, "limit": limit},
            )
            assert status == 200
            assert body["count"] == expected_count
            assert body["truncated"] is expected_truncated
            assert len(body["sites"]) == expected_count
            assert [site["distance_m"] for site in body["sites"]] == sorted(
                site["distance_m"] for site in body["sites"]
            )
        finally:
            await session.execute(
                text("DELETE FROM territory_site WHERE source = :source"), {"source": SOURCE}
            )


@pytest.mark.asyncio
async def test_app_contract_hides_ingest_details() -> None:
    async with db_session() as session:
        try:
            await _seed(session, 1)
            status, body = await _get(
                app,
                session,
                "/territory/sites/nearby",
                {"lat": LAT, "lng": LNG, "radius_m": 500},
            )
            assert status == 200
            assert set(body["sites"][0]) == {"site_id", "lat", "lng", "distance_m"}
            assert body["sites"][0]["site_id"].startswith(SOURCE)
        finally:
            await session.execute(
                text("DELETE FROM territory_site WHERE source = :source"), {"source": SOURCE}
            )


@pytest.mark.asyncio
async def test_dev_search_can_inspect_and_filter_the_source_kind() -> None:
    dev_app = FastAPI()
    dev_app.include_router(dev_router)
    async with db_session() as session:
        try:
            await _seed(session, 4)
            status, body = await _get(
                dev_app,
                session,
                "/dev/territory-sites/search",
                {**BBOX, "kind": "한전주", "limit": 10},
            )
            assert status == 200
            assert body["count"] == 2
            assert {site["kind"] for site in body["sites"]} == {"한전주"}
            assert {site["source"] for site in body["sites"]} == {SOURCE}
        finally:
            await session.execute(
                text("DELETE FROM territory_site WHERE source = :source"), {"source": SOURCE}
            )


def _paths_with_dev_console(enabled: bool) -> set[str]:
    environment = os.environ.copy()
    environment["DAENGS_DEV_CONSOLE"] = "true" if enabled else "false"
    command = """
from app.main import app

def collect_paths(routes):
    paths = []
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.append(path)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.extend(collect_paths(original_router.routes))
    return paths

print("\\n".join(sorted(collect_paths(app.routes))))
"""
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        cwd=ROOT,
    )
    return set(result.stdout.splitlines())


def test_dev_territory_site_surface_is_gated_but_app_read_is_always_mounted() -> None:
    dev_paths = {"/dev/territory-sites", "/dev/territory-sites/search"}
    disabled = _paths_with_dev_console(False)
    enabled = _paths_with_dev_console(True)

    assert dev_paths.isdisjoint(disabled)
    assert dev_paths <= enabled
    assert "/territory/sites/nearby" in disabled
    assert "/anchor/search" not in enabled
    assert "/anchors" not in enabled
