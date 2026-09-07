"""Synthetic spatial diary review surface and its canonical fixture."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from tools.spatial_diary.fixture import build_spatial_diary_ui_fixture

router = APIRouter()


@router.get("/spatial-diary-lab", include_in_schema=False)
async def view():
    return FileResponse(Path(__file__).parent / "static/spatial_diary_lab.html", media_type="text/html")


@router.get("/spatial-diary-lab/data", include_in_schema=False)
async def data():
    return JSONResponse(build_spatial_diary_ui_fixture(), headers={"Cache-Control": "no-store"})
