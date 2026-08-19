from fastapi import FastAPI

from app.api import hospital, places, static_map
from app.core.config import settings

app = FastAPI(title="DAENGS_geo", version="0.1.0")
app.include_router(places.router)
app.include_router(hospital.router)
app.include_router(static_map.router)


@app.get("/health")
async def health():
    return {"ok": True, "map_provider": settings.map_provider}
