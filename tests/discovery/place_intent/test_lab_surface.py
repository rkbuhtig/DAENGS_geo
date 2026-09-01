import os
import subprocess
import sys
from pathlib import Path

from app.discovery.place_intent.lab import _limit_search_preview
from app.place.planning.contract import PlaceKind
from app.place.search import PlaceSearchGroup, PlaceSearchResponse

ROOT = Path(__file__).resolve().parents[3]
HTML = (ROOT / "app" / "static" / "place_intent_lab.html").read_text(encoding="utf-8")


def test_intent_lab_shows_model_policy_and_real_search_layers() -> None:
    assert "AI의 여러 검색 방향을 실제 DB에서 본다" in HTML
    assert "/dev/place-intent/search" in HTML
    assert "Model interpretation" in HTML
    assert "Preserved signals" in HTML
    assert "Search lenses" in HTML
    assert "gate preview" in HTML
    assert "place.name" in HTML
    assert "preview_per_lens" in HTML
    assert "data.trace.lenses.target_lenses" in HTML
    assert "signal.required ? 'required' : 'optional'" in HTML
    assert "실행 가능한 lens가 없어 지도에 표시할 장소가 없습니다." in HTML


def test_intent_lab_limits_each_lens_preview_across_groups() -> None:
    search = PlaceSearchResponse.model_construct(
        conditions=None,
        groups=[
            PlaceSearchGroup.model_construct(
                kind=PlaceKind.CAFE,
                limit=3,
                truncated=False,
                results=["cafe-1", "cafe-2"],
            ),
            PlaceSearchGroup.model_construct(
                kind=PlaceKind.RESTAURANT,
                limit=3,
                truncated=False,
                results=["restaurant-1", "restaurant-2"],
            ),
        ],
    )

    limited = _limit_search_preview(search, 3)

    assert [group.results for group in limited.groups] == [
        ["cafe-1", "cafe-2"],
        ["restaurant-1"],
    ]
    assert [group.truncated for group in limited.groups] == [False, True]


def test_intent_lab_renders_provider_text_without_html_injection() -> None:
    assert "name.textContent = place.name" in HTML
    assert "quote.textContent" in HTML
    assert "introNote.textContent = lens.support_note" in HTML
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
