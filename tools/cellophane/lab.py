"""Cellophane comparison pages and their fixed CWD fixture names."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def _register(url: str, html: str, filename: str, media_type: str) -> None:
    async def view():
        return FileResponse(STATIC / html, media_type="text/html")

    async def data():
        path = Path.cwd() / filename
        if not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})

    router.add_api_route(url, view, methods=["GET"], include_in_schema=False)
    router.add_api_route(url + "/data", data, methods=["GET"], include_in_schema=False)


for url, html, fixture, media_type in (
    ("/cellophane", "cellophane.html", "cellophane.json", "application/geo+json"),
    ("/cellophane-distribution", "cellophane_distribution.html",
     "cellophane-distribution.json", "application/json"),
    ("/continuous-hex-comparison", "continuous_hex_comparison.html",
     "continuous-hex-visualization.json", "application/json"),
):
    _register(url, html, fixture, media_type)
