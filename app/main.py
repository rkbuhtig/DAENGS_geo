import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import anchor, places_v2, static_map
from app.core.config import settings
from app.core.db import get_session
from app.features.journey import api as journey
from app.features.walk import api as walk
from app.usage.composition import route_capability_problems
from app.usage.gate import usage_request_scope

_problems = route_capability_problems()
if _problems:
    # 설정만 받고 런타임에 추정으로 흘려보내면 장애와 구분이 안 된다. 여기서 세운다.
    raise RuntimeError("경로 제공사 설정 오류: " + " / ".join(_problems))

app = FastAPI(title="DAENGS_geo", version="0.1.0")
app.include_router(places_v2.router)
app.include_router(walk.router)
app.include_router(journey.router)
app.include_router(static_map.router)
app.include_router(anchor.router)


@app.middleware("http")
async def bind_usage_request_scope(request, call_next):
    """요청당 사용량 카운터만 만든다. 허용·소비 집행은 실제 외부 호출 Gate 한 곳에서 한다."""
    async with usage_request_scope():
        return await call_next(request)


if settings.dev_console:
    _ANCHORS = Path(__file__).parent / "static" / "anchors.html"
    _CELLOPHANE = Path(__file__).parent / "static" / "cellophane.html"
    _CELLOPHANE_DISTRIBUTION = Path(__file__).parent / "static" / "cellophane_distribution.html"
    _FACILITY = Path(__file__).parent / "static" / "facility.html"

    @app.get("/facility-map", include_in_schema=False)
    async def facility_map():
        """시설 필터를 눈으로 보는 표면. 개를 바꾸면 무엇이 빠지는지가 보여야 한다."""
        return FileResponse(_FACILITY, media_type="text/html")

    @app.get("/anchors", include_in_schema=False)
    async def anchor_map():
        """앵커 분포 눈으로 보기. 검증용 표면이라 dev_console 과 같은 게이트 뒤에 둔다."""
        return FileResponse(_ANCHORS, media_type="text/html")

    @app.get("/cellophane", include_in_schema=False)
    async def cellophane_view():
        """Paint v2 한 장의 chain·육각 셀·질량 보존을 보는 얇은 검증 표면."""
        return FileResponse(_CELLOPHANE, media_type="text/html")

    @app.get("/cellophane/data", include_in_schema=False)
    async def cellophane_data():
        """CWD의 명시적 fixture 하나만 제공한다. 임의 경로는 받지 않는다."""
        path = Path.cwd() / "cellophane.json"
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(
            path,
            media_type="application/geo+json",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/cellophane-distribution", include_in_schema=False)
    async def cellophane_distribution_view():
        """30회 Cellophane 통계와 질량 영역을 실제 지도에서 비교하는 검증 표면."""
        return FileResponse(_CELLOPHANE_DISTRIBUTION, media_type="text/html")

    @app.get("/cellophane-distribution/data", include_in_schema=False)
    async def cellophane_distribution_data():
        """CWD의 고정 통계 fixture만 제공한다. latent truth 파일은 제공하지 않는다."""
        path = Path.cwd() / "cellophane-distribution.json"
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(
            path,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    _WORLD_CTX = Path(__file__).parent / "static" / "world_context.html"
    _WORLD_CTX_DATA = frozenset({"latent.json", "world_context.json", "osm_world.json"})

    @app.get("/world-context", include_in_schema=False)
    async def world_context_view():
        """M2 합성 사건 × 진짜 세계 readout 을 실제 지도 위에서 보는 검증 표면.

        스파이크(`scripts/spikes/territory_paint/world_context_readout.py`) 산출물 전용이라
        같은 dev_console 게이트 뒤에 둔다. basemap 은 앱과 같은 `/map/client-config` 로 뜬다.
        """
        return FileResponse(_WORLD_CTX, media_type="text/html")

    @app.get("/world-context/data/{name}", include_in_schema=False)
    async def world_context_data(name: str):
        """스파이크 산출물만 — 목록 밖 이름과 없는 파일은 404. CWD 에서 읽는다."""
        if name not in _WORLD_CTX_DATA:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        path = Path.cwd() / name
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(path, media_type="application/json")


@app.get("/health")
async def health():
    """Liveness only. Dependencies belong to readiness, not process survival."""
    return {
        "ok": True,
        "map_provider": settings.map_provider,
        "usage_policy": settings.usage_policy,
    }


@app.get("/health/ready")
async def readiness(db: Annotated[AsyncSession, Depends(get_session)]):
    """Ready to serve DB-backed requests. External providers are deliberately excluded."""
    try:
        async with asyncio.timeout(2):
            await db.execute(text("SELECT 1"))
    except (SQLAlchemyError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"ok": True, "database": "ready"}
