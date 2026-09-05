"""The recorded Android UI lab stays behind dev_console and needs no DB."""

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings


def test_place_ui_lab_is_gated_and_serves_only_static_files(monkeypatch):
    import app.main

    try:
        monkeypatch.setattr(settings, "dev_console", False)
        module = importlib.reload(app.main)
        with TestClient(module.app) as client:
            assert client.get("/place-ui-lab/").status_code == 404
            assert client.get("/place-ui-lab/fixtures.json").status_code == 404

        monkeypatch.setattr(settings, "dev_console", True)
        module = importlib.reload(app.main)
        with TestClient(module.app) as client:
            assert client.get("/place-ui-lab").status_code == 200
            for asset in ("", "app.js", "style.css", "fixtures.json"):
                assert client.get(f"/place-ui-lab/{asset}").status_code == 200
            assert client.get("/place-ui-lab/missing.json").status_code == 404
            assert client.get("/place-ui-lab/%2e%2e/%2e%2e/core/config.py").status_code == 404
    finally:
        monkeypatch.undo()
        importlib.reload(app.main)


def test_recordings_cover_every_control_combination_without_identity_drift():
    path = Path(__file__).resolve().parents[2] / "app/static/place_ui_lab/fixtures.json"
    recordings = json.loads(path.read_text(encoding="utf-8-sig"))["cases"]
    assert len(recordings) == 24
    for region in ("gangnam", "seongsu", "haeundae", "jeju"):
        baseline = recordings[f"{region}-baseline"]
        expected = {
            g["kind"]: {(h["place"]["key"]["source"], h["place"]["key"]["ref"])
                        for h in g["results"]}
            for g in baseline["groups"]
        }
        for dog in ("baseline", "small", "large"):
            for suffix in ("", "_parking"):
                response = recordings[f"{region}-{dog}{suffix}"]
                for group in response["groups"]:
                    assert not group["truncated"]
                    assert {
                        (h["place"]["key"]["source"], h["place"]["key"]["ref"])
                        for h in group["results"]
                    } == expected[group["kind"]]
                    if dog == "baseline":
                        assert all(not h["evaluations"] for h in group["results"])
