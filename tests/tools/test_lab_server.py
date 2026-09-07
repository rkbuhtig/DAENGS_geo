"""Stage 3 execution boundaries and review HTTP/storage regression checks (Decision: #86)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.lab_server import create_app

ROOT = Path(__file__).resolve().parents[2]


def _isolated(code, cwd, **variables):
    environment = {**os.environ, "PYTHONPATH": str(ROOT), **variables}
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=environment,
        capture_output=True, text=True, check=True, timeout=30,
    )


@pytest.mark.parametrize("dev_console", ["true", "false"])
def test_common_api_import_never_loads_review_code_or_creates_local_data(tmp_path, dev_console):
    _isolated('''
import sys
from fastapi.testclient import TestClient
from app.main import app
for name in sys.modules:
    assert not name.startswith(("tools", "scripts")), name
    assert name not in {
        "tools.spatial_diary.fixture", "tools.place_intent.lab",
        "tools.territory_game.season_lab", "tools.territory_game.sites_lab",
    }, name
with TestClient(app) as client:
    assert client.get("/health").status_code == 200
    for path in ["/walk-trace-lab", "/cellophane", "/facility-map", "/place-ui-lab/",
                 "/place-intent-lab", "/spatial-diary-lab", "/world-context",
                 "/dev/territory-sites", "/territory-season-lab/"]:
        assert client.get(path).status_code == 404, path
''', tmp_path, DAENGS_DEV_CONSOLE=dev_console)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tool", ["place-ui", "territory-season"])
def test_standalone_tools_do_not_import_settings_database_or_providers(tmp_path, tool):
    _isolated(f'''
import importlib.abc
import sys
class BlockSharedRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("app.core", "app.providers", "app.discovery", "scripts")):
            raise AssertionError("Unexpected shared runtime: " + fullname)
sys.meta_path.insert(0, BlockSharedRuntime())
from tools.lab_server import create_app
from fastapi.testclient import TestClient
application = create_app(enabled_tools=[{tool!r}])
with TestClient(application) as client:
    path = "/place-ui-lab/fixtures.json" if {tool!r} == "place-ui" else "/territory-season-lab/api/seasons"
    assert client.get(path).status_code == 200
    assert client.get("/map/client-config").status_code == 404
    assert client.get("/walk-trace-lab").status_code == 404
''', tmp_path)
    assert (tmp_path / ".local/territory-season.sqlite3").exists() == (tool == "territory-season")


def test_walk_selection_does_not_load_other_labs_or_database(tmp_path):
    _isolated('''
import sys
from tools.lab_server import create_app
from fastapi.testclient import TestClient
app = create_app(enabled_tools=["walk-trace"])
assert "app.main" not in sys.modules
assert "app.core.db" not in sys.modules
assert "tools.place_intent.lab" not in sys.modules
assert "tools.territory_game.season_lab" not in sys.modules
with TestClient(app) as client:
    assert client.get("/walk-trace-lab/example").status_code == 200
    assert client.get("/map/client-config").status_code == 200
    assert client.get("/spatial-diary-lab").status_code == 404
''', tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tools", [[], ["territory-season", "typo"]])
def test_invalid_selection_fails_before_creating_a_database(tmp_path, tools):
    db = tmp_path / "game.sqlite3"
    with pytest.raises(ValueError, match="Select review tools"):
        create_app(enabled_tools=tools, season_db=db)
    assert not db.exists()


def test_fixed_fixture_routes_keep_cwd_names_content_and_missing_states(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fixtures = {
        "/cellophane/data": ("cellophane.json", "application/geo+json"),
        "/cellophane-distribution/data": ("cellophane-distribution.json", "application/json"),
        "/continuous-hex-comparison/data": ("continuous-hex-visualization.json", "application/json"),
    }
    with TestClient(create_app(enabled_tools=["cellophane", "world-context"])) as client:
        for url, (filename, media_type) in fixtures.items():
            assert client.get(url).status_code == 404
            content = json.dumps({"source": filename, "query": {"radius_m": 30}})
            (tmp_path / filename).write_text(content)
            response = client.get(url)
            assert response.text == content
            assert response.headers["content-type"] == media_type
            assert response.headers["cache-control"] == "no-store"
        for name in ("latent.json", "world_context.json", "osm_world.json"):
            assert client.get("/world-context/data/" + name).status_code == 404
            (tmp_path / name).write_text('{"source":"fixture"}')
            assert client.get("/world-context/data/" + name).json() == {"source": "fixture"}
        (tmp_path / "private.json").write_text('{"private":true}')
        for path in ["/world-context/data/private.json", "/cellophane/data/private.json",
                     "/world-context/data/%2e%2e%2fprivate.json"]:
            assert client.get(path).status_code == 404
        assert client.get("/cellophane/data?path=private.json").json()["source"] == "cellophane.json"
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("custom_path", [False, True])
def test_mounted_season_preserves_existing_store_assets_and_restart(tmp_path, monkeypatch, custom_path):
    from tools.territory_game.season_lab import build_app

    monkeypatch.chdir(tmp_path)
    db = tmp_path / ("custom.sqlite3" if custom_path else ".local/territory-season.sqlite3")
    options = {"season_db": db} if custom_path else {}
    # Create via the existing standalone app, then resume through the new mount.
    with TestClient(build_app(db)) as old:
        response = old.post("/api/seasons", json={"season_id": "saved", "starts_ms": 0})
        assert response.status_code == 201
        before = response.json()
    with TestClient(create_app(enabled_tools=["territory-season"], **options)) as client:
        assert client.get("/territory-season-lab/api/seasons/saved").json() == before
        assert client.get("/territory-season-lab/").status_code == 200
        assert client.get("/territory-season-lab/lab.mjs").status_code == 200
        result = client.post("/territory-season-lab/api/seasons/saved/commands", json={
            "request_id": "clock", "command": {"action": "advance", "delta_ms": 1000},
        })
        assert result.status_code == 200
        after = client.get("/territory-season-lab/api/seasons/saved").json()
        assert after != before
    with TestClient(create_app(enabled_tools=["territory-season"], **options)) as restarted:
        assert restarted.get("/territory-season-lab/api/seasons/saved").json() == after
    if custom_path:
        assert not (tmp_path / ".local").exists()


def test_usage_budget_is_shared_within_request_and_reset_for_next_request():
    from app.usage.gate import UsageGate
    from app.usage.ledger import InMemoryLedger
    from app.usage.models import MeasuredRouteIntent, UsageDenied
    from app.usage.policy import BoundedDevPolicy, DevUsageLimits, OperationLimit

    gate = UsageGate(BoundedDevPolicy(DevUsageLimits(
        measured_route=OperationLimit(request_units=1, window_units=10),
    )), InMemoryLedger())
    app = create_app(enabled_tools=["place-intent"])

    @app.get("/test-budget")
    async def budget():
        intent = MeasuredRouteIntent(mode="walk")
        permit = await gate.check(intent)
        await gate.consume(intent, permit)
        with pytest.raises(UsageDenied):
            await gate.consume(intent, permit)
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/test-budget").json() == {"ok": True}
        assert client.get("/test-budget").json() == {"ok": True}
