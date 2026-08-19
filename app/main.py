from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import hospital, places, static_map
from app.core.config import settings

app = FastAPI(title="DAENGS_geo", version="0.1.0")
app.include_router(places.router)
app.include_router(hospital.router)
app.include_router(static_map.router)


if settings.dev_console:
    _DEV = Path(__file__).parent / "static" / "dev.html"

    @app.get("/dev", include_in_schema=False)
    async def dev_console():
        """검증용 콘솔. 앱 UI가 아니다 — 루프(말→조건→화면)와 spots가 말이 되는지 눈으로 보는 용도."""
        return FileResponse(_DEV, media_type="text/html")


@app.get("/health")
async def health():
    return {"ok": True, "map_provider": settings.map_provider}
