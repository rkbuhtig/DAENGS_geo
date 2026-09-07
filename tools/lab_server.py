"""Select local review tools: python -m tools.lab_server --tool walk-trace.

The common API never imports this entrypoint. Tool internals/assets keep their
existing locations until stage 4; only selected tools and their API dependencies
are imported. Run from the same working directory to retain fixture/SQLite paths.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
AVAILABLE_TOOLS = (
    "walk-trace", "cellophane", "spatial-diary", "world-context",
    "territory-sites", "territory-season", "place-ui", "place-intent", "facility",
)
MAP_TOOLS = frozenset({
    "walk-trace", "cellophane", "spatial-diary", "world-context", "territory-sites",
    "place-intent", "facility",
})


def _page(application: FastAPI, url: str, filename: str) -> None:
    async def view():
        return FileResponse(STATIC / filename, media_type="text/html")

    application.add_api_route(url, view, methods=["GET"], include_in_schema=False)


def _fixture(application: FastAPI, url: str, filename: str, media_type: str) -> None:
    async def data():
        path = Path.cwd() / filename
        if not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})

    application.add_api_route(url, data, methods=["GET"], include_in_schema=False)


def create_app(
    *, enabled_tools: Sequence[str], season_db: Path = Path(".local/territory-season.sqlite3")
) -> FastAPI:
    """Explicit selection is the lab opt-in; dev_console never adds labs to app.main."""
    chosen = set(enabled_tools)
    unknown = chosen - set(AVAILABLE_TOOLS)
    if not chosen or unknown:
        raise ValueError(f"Select review tools from {AVAILABLE_TOOLS}; unknown: {sorted(unknown)}")

    application = FastAPI(title="DAENGS_geo review tools", version="0.1.0")
    if chosen & MAP_TOOLS:
        from app.api.static_map import router as map_router
        from app.usage.gate import usage_request_scope

        application.include_router(map_router)

        @application.middleware("http")
        async def bind_usage_request_scope(request, call_next):
            # Preserve the request budget previously supplied by app.main.
            async with usage_request_scope():
                return await call_next(request)

    if "place-ui" in chosen:
        application.mount(
            "/place-ui-lab", StaticFiles(directory=STATIC / "place_ui_lab", html=True),
            name="place-ui-lab",
        )

    if "walk-trace" in chosen:
        from scripts.sim.walk.lab import router as walk_trace_router

        application.include_router(walk_trace_router)

    if "place-intent" in chosen:
        from app.discovery.place_intent.lab import router as place_intent_router

        application.include_router(place_intent_router)

    if "territory-sites" in chosen:
        from app.features.territory.game.dev_api import router as territory_sites_router

        application.include_router(territory_sites_router)
        _page(application, "/dev/territory-sites", "territory_sites.html")

    if "territory-season" in chosen:
        from app.features.territory.game.season_lab import build_app

        application.mount("/territory-season-lab", build_app(season_db))

    if "facility" in chosen:
        from app.api.places_v2 import router as places_router

        application.include_router(places_router)
        _page(application, "/facility-map", "facility.html")

    if "cellophane" in chosen:
        for url, html, fixture, media_type in (
            ("/cellophane", "cellophane.html", "cellophane.json", "application/geo+json"),
            ("/cellophane-distribution", "cellophane_distribution.html",
             "cellophane-distribution.json", "application/json"),
            ("/continuous-hex-comparison", "continuous_hex_comparison.html",
             "continuous-hex-visualization.json", "application/json"),
        ):
            _page(application, url, html)
            _fixture(application, url + "/data", fixture, media_type)

    if "spatial-diary" in chosen:
        from app.api.spatial_diary_lab import build_spatial_diary_ui_fixture

        _page(application, "/spatial-diary-lab", "spatial_diary_lab.html")

        @application.get("/spatial-diary-lab/data", include_in_schema=False)
        async def spatial_diary_data():
            return JSONResponse(
                build_spatial_diary_ui_fixture(), headers={"Cache-Control": "no-store"},
            )

    if "world-context" in chosen:
        _page(application, "/world-context", "world_context.html")

        @application.get("/world-context/data/{name}", include_in_schema=False)
        async def world_context_data(name: str):
            if name not in {"latent.json", "world_context.json", "osm_world.json"}:
                raise HTTPException(status_code=404)
            path = Path.cwd() / name
            if not path.exists():
                raise HTTPException(status_code=404)
            return FileResponse(path, media_type="application/json")

    return application


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", action="append", choices=AVAILABLE_TOOLS, required=True,
                        help="Review tool to mount; repeat to combine tools")
    parser.add_argument("--season-db", type=Path, default=Path(".local/territory-season.sqlite3"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(enabled_tools=args.tool, season_db=args.season_db),
                host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
