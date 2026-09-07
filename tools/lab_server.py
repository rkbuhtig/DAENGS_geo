"""Select local review tools: python -m tools.lab_server --tool walk-trace.

The common API never imports this entrypoint. Each tool owns its HTTP surface,
assets and local storage adapter; only selected tools and their API dependencies
are imported. Run from the same working directory to retain fixture/SQLite paths.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI

AVAILABLE_TOOLS = (
    "walk-trace", "cellophane", "spatial-diary", "world-context",
    "territory-sites", "territory-season", "place-ui", "place-intent", "facility",
)
MAP_TOOLS = frozenset({
    "walk-trace", "cellophane", "spatial-diary", "world-context", "territory-sites",
    "place-intent", "facility",
})


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
        from tools.place_ui.lab import mount as place_ui_mount

        place_ui_mount(application)

    if "walk-trace" in chosen:
        from tools.walk_trace.lab import router as walk_trace_router

        application.include_router(walk_trace_router)

    if "place-intent" in chosen:
        from tools.place_intent.lab import router as place_intent_router

        application.include_router(place_intent_router)

    if "territory-sites" in chosen:
        from tools.territory_game.sites_lab import router as territory_game_router

        application.include_router(territory_game_router)

    if "territory-season" in chosen:
        from tools.territory_game.season_lab import mount as territory_game_mount

        territory_game_mount(application, season_db)

    if "facility" in chosen:
        from tools.facility.lab import router as facility_router

        application.include_router(facility_router)

    if "cellophane" in chosen:
        from tools.cellophane.lab import router as cellophane_router

        application.include_router(cellophane_router)

    if "spatial-diary" in chosen:
        from tools.spatial_diary.lab import router as spatial_diary_router

        application.include_router(spatial_diary_router)

    if "world-context" in chosen:
        from tools.world_context.lab import router as world_context_router

        application.include_router(world_context_router)

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
