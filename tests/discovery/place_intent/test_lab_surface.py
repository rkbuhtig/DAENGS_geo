import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HTML = (ROOT / "app" / "static" / "place_intent_lab.html").read_text(encoding="utf-8")


def test_intent_lab_shows_model_policy_and_real_search_layers() -> None:
    assert "Gemini가 고른 검색을 실제 DB에서 본다" in HTML
    assert "/dev/place-intent/search" in HTML
    assert "Model interpretation" in HTML
    assert "Planner candidates" in HTML
    assert "gate preview" in HTML
    assert "place.name" in HTML


def test_intent_lab_renders_provider_text_without_html_injection() -> None:
    assert "name.textContent = place.name" in HTML
    assert "quote.textContent" in HTML
    assert "innerHTML = place.name" not in HTML


def test_intent_lab_renders_invalid_model_output_as_a_typed_empty_state() -> None:
    assert "if (!trace.raw)" in HTML
    assert "modelState = raw ? raw.disposition : 'invalid_output'" in HTML
    assert "data.trace.raw ? data.trace.raw.interpretations.length : 0" in HTML


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


def test_intent_lab_routes_are_behind_dev_console_gate() -> None:
    paths = {"/place-intent-lab", "/dev/place-intent/search"}
    assert paths.isdisjoint(_paths_with_dev_console(False))
    assert paths <= _paths_with_dev_console(True)
