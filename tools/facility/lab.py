"""Facility inspection page consumes the shared Place search API."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.places_v2 import router as places_router

router = APIRouter()
router.include_router(places_router)


@router.get("/facility-map", include_in_schema=False)
async def view():
    return FileResponse(Path(__file__).parent / "static/facility.html", media_type="text/html")
