"""walk trace scenario를 지도에서 저작·실행하는 dev-console 전용 어댑터."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from scripts.sim.walk.bundle import ScenarioArtifacts, build_scenario_from_spec
from scripts.sim.walk.spec import WalkTraceScenarioSpec
from scripts.spikes.walk_diary_route.projector import build_diary_route_experiment

router = APIRouter(prefix="/walk-trace-lab", tags=["walk-trace-lab"])

_ROOT = Path(__file__).resolve().parents[3]
_HTML = _ROOT / "app" / "static" / "walk_trace_lab.html"
_EXAMPLE = Path(__file__).parent / "examples" / "sniff-and-go.json"


def build_lab_payload(artifacts: ScenarioArtifacts) -> dict[str, object]:
    trace_samples = artifacts.trace["samples"]
    return {
        "format": "walk-trace-lab-result-v1",
        "scenario": artifacts.scenario,
        "summary": {
            "truth_sample_count": len(trace_samples),
            "observed_fix_count": len(artifacts.observed.fixes),
            "missing_sample_count": sum(row["observed_fix"] is None for row in trace_samples),
            "delivery_event_count": len(artifacts.delivery["events"]),
            "facts": artifacts.computed.facts.model_dump(mode="json"),
            "quality": artifacts.computed.trail.quality.to_dict(),
        },
        "trace": artifacts.trace,
        "delivery": artifacts.delivery,
        "derived": artifacts.derived,
        "cellophane": json.loads(artifacts.cellophane_geojson),
        "diary_route_experiment": build_diary_route_experiment(
            artifacts.computed.trail, artifacts.computed.facts.started_at
        ),
    }


@router.get("", include_in_schema=False)
async def walk_trace_lab_view():
    return FileResponse(_HTML, media_type="text/html")


@router.get("/example", include_in_schema=False)
async def walk_trace_lab_example():
    return FileResponse(
        _EXAMPLE,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/run", include_in_schema=False)
async def walk_trace_lab_run(spec: WalkTraceScenarioSpec):
    try:
        artifacts = await run_in_threadpool(build_scenario_from_spec, spec)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return JSONResponse(
        build_lab_payload(artifacts),
        headers={"Cache-Control": "no-store"},
    )
