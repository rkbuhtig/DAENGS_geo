"""`GET /anchor/search` 의 상한 계약 — `truncated` 가 갈리는 지점.

**왜 필요한가**: 핸들러는 `limit + 1` 개를 뽑아 초과 여부를 판단한 뒤 잘라서 준다. 이
구조는 경계에서만 틀린다 — 정확히 `limit` 개가 있을 때 `truncated=true` 로 새거나,
`limit + 1` 개인데 `false` 로 삼키거나. 어느 쪽도 밀도 해석을 조용히 오도한다
(모듈 docstring: "조용히 자르면 '이 동네엔 앵커가 이만큼뿐'으로 읽힌다").

앵커 표면은 지금까지 어떤 테스트도 때리지 않았다 — 테스트 감사 Pass 3 의 공백 목록에서.

격리는 좌표로 한다 (`tests/conftest` 의 방식). 동해 먼바다 한 칸을 쓰고 그 bbox 만 조회하므로
실적재 데이터와 안 섞인다. 행은 이 파일이 소유한다.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import get_session
from app.main import app
from tests.conftest import db_session

# 실적재 앵커(육지)와 안 겹치는 먼바다. bbox 도 여기만 본다.
LAT, LNG = 37.4979, 130.9000
BBOX = {"south": LAT - 0.01, "north": LAT + 0.01, "west": LNG - 0.01, "east": LNG + 0.01}
SOURCE = "test-anchor-truncated"


async def _seed(session, n: int) -> None:
    await session.execute(
        text("""
        INSERT INTO anchor (cell, source, kind, location)
        SELECT :src || ':' || g, :src, 'test',
               ST_SetSRID(ST_MakePoint(:lng + g * 0.00001, :lat), 4326)::geography
        FROM generate_series(1, :n) AS g
        """),
        {"src": SOURCE, "lat": LAT, "lng": LNG, "n": n},
    )


async def _search(session, **params) -> dict:
    app.dependency_overrides[get_session] = lambda: session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/anchor/search", params={**BBOX, **params})
        assert response.status_code == 200, response.text
        return response.json()
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seeded", "limit", "expected_count", "expected_truncated"),
    [
        (3, 5, 3, False),   # 상한에 못 미침
        (5, 5, 5, False),   # **정확히 상한** — 여기서 true 로 새면 없는 누락을 알린다
        (6, 5, 5, True),    # 상한 + 1 — 여기서 false 로 삼키면 누락이 조용해진다
    ],
)
async def test_truncated_flips_exactly_at_the_limit(
    seeded: int, limit: int, expected_count: int, expected_truncated: bool
) -> None:
    async with db_session() as session:
        try:
            await _seed(session, seeded)
            body = await _search(session, limit=limit)
            assert body["count"] == expected_count
            assert body["truncated"] is expected_truncated
            assert len(body["results"]) == expected_count
        finally:
            await session.execute(text("DELETE FROM anchor WHERE source = :s"), {"s": SOURCE})


@pytest.mark.asyncio
async def test_kind_filter_narrows_without_touching_the_limit() -> None:
    """`kind` 미지정이 '전부'라는 기본값. 필터가 상한 판단보다 먼저 걸린다."""
    async with db_session() as session:
        try:
            await _seed(session, 4)
            assert (await _search(session, limit=10))["count"] == 4
            assert (await _search(session, limit=10, kind="test"))["count"] == 4
            assert (await _search(session, limit=10, kind="한전주"))["count"] == 0
        finally:
            await session.execute(text("DELETE FROM anchor WHERE source = :s"), {"s": SOURCE})
