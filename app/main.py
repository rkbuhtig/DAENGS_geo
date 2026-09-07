import asyncio
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import places_v2, static_map
from app.core.config import settings
from app.core.db import get_session
from app.features.journey import api as journey
from app.features.spatial_diary import api as spatial_diary_episode
from app.features.territory import api as spatial_diary
from app.features.territory.game import api as territory_game
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
app.include_router(spatial_diary.router)
app.include_router(spatial_diary_episode.router)
app.include_router(static_map.router)
app.include_router(territory_game.router)


@app.middleware("http")
async def bind_usage_request_scope(request, call_next):
    """요청당 사용량 카운터만 만든다. 허용·소비 집행은 실제 외부 호출 Gate 한 곳에서 한다."""
    async with usage_request_scope():
        return await call_next(request)


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
