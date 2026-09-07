"""Synthetic events against saved world context; only three named CWD fixtures."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/world-context", include_in_schema=False)
async def view():
    return FileResponse(Path(__file__).parent / "static/world_context.html", media_type="text/html")


@router.get("/world-context/data/{name}", include_in_schema=False)
async def data(name: str):
    if name not in {"latent.json", "world_context.json", "osm_world.json"}:
        raise HTTPException(status_code=404)
    path = Path.cwd() / name
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/json")
