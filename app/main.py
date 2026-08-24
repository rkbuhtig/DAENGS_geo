from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import facility, places, static_map
from app.core.config import settings
from app.features.hospital import api as hospital
from app.features.pharmacy import api as pharmacy
from app.journey import api as journey
from app.providers.registry import route_capability_problems
from app.usage.gate import usage_request_scope

_problems = route_capability_problems()
if _problems:
    # 설정만 받고 런타임에 추정으로 흘려보내면 장애와 구분이 안 된다. 여기서 세운다.
    raise RuntimeError("경로 제공사 설정 오류: " + " / ".join(_problems))

app = FastAPI(title="DAENGS_geo", version="0.1.0")
app.include_router(places.router)
app.include_router(facility.router)
app.include_router(hospital.router)
app.include_router(pharmacy.router)
app.include_router(journey.router)
app.include_router(static_map.router)


@app.middleware("http")
async def bind_usage_request_scope(request, call_next):
    """요청당 사용량 카운터만 만든다. 허용·소비 집행은 실제 외부 호출 Gate 한 곳에서 한다."""
    async with usage_request_scope():
        return await call_next(request)


if settings.dev_console:
    _DEV = Path(__file__).parent / "static" / "dev.html"

    @app.get("/dev", include_in_schema=False)
    async def dev_console():
        """검증용 콘솔. 앱 UI가 아니다 — 루프(말→조건→화면)와 spots가 말이 되는지 눈으로 보는 용도."""
        return FileResponse(_DEV, media_type="text/html")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "map_provider": settings.map_provider,
        "usage_policy": settings.usage_policy,
    }
