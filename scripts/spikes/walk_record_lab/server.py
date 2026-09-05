"""Run with python -m scripts.spikes.walk_record_lab.server; binds loopback only."""
from __future__ import annotations

import argparse
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from scripts.sim.walk.lab import router as trace_router
from scripts.spikes.storyboard_and_regions.sources import service_key
from scripts.spikes.walk_record_lab.context import ContextReader
from scripts.spikes.walk_record_lab.core import Experiment, prepare, summarize
from scripts.spikes.walk_record_lab.selection import select

ROOT = Path(__file__).resolve().parents[3]


def create_app(cache: Path, key: str = ""):
    app = FastAPI(title="Local walk record lab")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.include_router(trace_router)
    lock = threading.Lock()

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Same-origin requests only"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def view():
        return FileResponse(ROOT / "app/static/walk_record_lab.html")

    @app.get("/map/client-config")
    def map_config():
        return {"provider": "osm"}

    @app.get("/record-lab/config")
    def config():
        return {"can_fetch": bool(key), "synthetic": True}

    @app.post("/record-lab/run")
    def run(experiment: Experiment):
        # Serialize cache writes and cap externally triggered work per run.
        with lock:
            try:
                artifacts, entries = prepare(experiment)
                reader = ContextReader(cache, key)
                selection = select(artifacts, entries, experiment.selection, experiment.reference_walks)
                contexts, metrics = reader.selected_contexts(selection, experiment.fetch)
                result = summarize(experiment, artifacts, entries, contexts, selection)
                result["queries"] = metrics
                return result
            except ValueError:
                raise HTTPException(422, "Invalid scenario or tap time; check walk duration") from None

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    key = service_key(args.env_file) if args.env_file else ""
    uvicorn.run(create_app(args.cache_dir, key), host="127.0.0.1", port=args.port,
                access_log=False)


if __name__ == "__main__":
    main()
