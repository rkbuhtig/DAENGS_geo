"""GPS 경로 저작 Lab의 실행 경계와 dev-console 게이트."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.sim.walk.bundle import build_scenario_from_spec
from scripts.sim.walk.lab import build_lab_payload, router
from scripts.sim.walk.spec import WalkTraceScenarioSpec

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "app" / "static" / "walk_trace_lab.html").read_text(encoding="utf-8")
EXAMPLE = ROOT / "scripts" / "sim" / "walk" / "examples" / "sniff-and-go.json"


def _example() -> dict[str, object]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_lab_payload_keeps_truth_observation_delivery_and_canonical_layers_distinct():
    spec = WalkTraceScenarioSpec.model_validate(_example())
    payload = build_lab_payload(build_scenario_from_spec(spec))

    assert payload["format"] == "walk-trace-lab-result-v1"
    assert payload["scenario"]["format"] == "walk-trace-scenario-v1"
    assert payload["trace"]["format"] == "walk-trace-v1"
    assert payload["delivery"]["format"] == "walk-delivery-v1"
    assert payload["diary_route_experiment"]["format"] == (
        "walk-diary-route-experiment-v1"
    )
    assert payload["diary_route_experiment"]["semantics"]["persistence"] == (
        "forbidden_experiment_only"
    )
    assert payload["evaluation"]["format"] == "walk-trace-evaluation-v1"
    assert payload["evaluation"]["hard_invariants_passed"] is True
    assert payload["cellophane"]["type"] == "FeatureCollection"
    assert payload["summary"]["truth_sample_count"] > payload["summary"]["observed_fix_count"]
    assert payload["summary"]["delivery_event_count"] > payload["summary"]["observed_fix_count"]
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_lab_http_runs_only_the_supplied_contract_without_writing_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with _client() as client:
        response = client.post("/walk-trace-lab/run", json=_example())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["scenario"]["session_id"] == "lab-sniff-and-go"
    assert list(tmp_path.iterdir()) == []


def test_lab_turns_cross_layer_runtime_errors_into_validation_responses():
    payload = _example()
    payload["faults"][0]["end_s"] = 100_000

    with _client() as client:
        response = client.post("/walk-trace-lab/run", json=payload)

    assert response.status_code == 422
    assert "exceeds motion duration" in response.json()["detail"]


def test_lab_html_authors_a_route_and_renders_all_three_time_layers():
    assert "state.backend.onClick" in HTML
    assert "state.points.push(point)" in HTML
    assert "route:{name:'map-authored-route',points_xy:" in HTML
    assert "motion:motionFor(length),sensor:sensorSpec(),faults" in HTML
    assert "fetch(RUN_URL,{method:'POST'" in HTML
    assert "addEventListener('click',() => runScenario())" in HTML
    assert "observedGroups(rows)" in HTML
    assert "result.delivery.events.filter" in HTML
    assert "result.cellophane.features.filter" in HTML
    assert "invalidateResult()" in HTML
    assert "state.result.derived.truth_duration_s" in HTML
    assert "facts.moving_distance_m" in HTML
    assert "수용 이동거리" in HTML
    assert "수용 구간시간" in HTML
    assert "실제 움직임 → GPS 관측 → 앱 전달" in HTML
    assert "selectedDiaryCandidate()" in HTML
    assert "renderDiaryRoute()" in HTML
    assert "nearest_geometry_to_start_m" in HTML
    assert "앞뒤 거리만 자르면 루프·왕복" in HTML
    assert "metrics.gap_count" in HTML
    assert "정확한 경계 교차점은 내부점 양자화의 예외" in HTML


def test_lab_can_exchange_the_versioned_scenario_json():
    assert "JSON.stringify(payload,null,2)" in HTML
    assert "Perfect 기준군 비교 영수증" in HTML
    assert "renderEvaluation()" in HTML
    assert 'id="import-file"' in HTML
    assert "JSON.parse(await file.text())" in HTML
    assert "await runScenario(spec)" in HTML
    assert "session_id:null" in HTML


def test_lab_invalidates_derived_results_when_authoring_controls_change():
    assert "aside select, aside input[type=\"number\"], aside input[type=\"checkbox\"]" in HTML
    assert "control.addEventListener('input',() => invalidateResult())" in HTML


def test_lab_styles_faults_by_contract_kind_instead_of_free_form_id():
    assert "fault.id,fault.kind" in HTML
    assert "faultKinds.has('accuracy')" in HTML
    assert "faultKinds.has('position_offset')" in HTML
    assert "id.includes('accuracy')" not in HTML
    assert "id.includes('spike')" not in HTML


def _paths_with_dev_console(enabled: bool) -> set[str]:
    environment = os.environ.copy()
    environment["DAENGS_DEV_CONSOLE"] = "true" if enabled else "false"
    command = """
from app.main import app

def collect_paths(routes):
    paths = []
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.append(path)
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            paths.extend(collect_paths(original_router.routes))
    return paths

print("\\n".join(sorted(collect_paths(app.routes))))
"""
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def test_walk_trace_lab_is_closed_without_the_dev_console_gate():
    paths = {
        "/walk-trace-lab",
        "/walk-trace-lab/example",
        "/walk-trace-lab/run",
    }
    assert paths.isdisjoint(_paths_with_dev_console(False))
    assert paths <= _paths_with_dev_console(True)
