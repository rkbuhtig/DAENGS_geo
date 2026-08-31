"""PR3 dev_console thin viewer 계약."""

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.spikes.territory_paint.cellophane_fixture import build_fixture, main

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "app" / "static" / "cellophane.html").read_text(encoding="utf-8")


def test_fixture_runs_the_canonical_segment_paint_serializer_path():
    payload = build_fixture()
    meta = payload["meta"]
    chains = [feature for feature in payload["features"]
              if feature["properties"]["kind"] == "accepted_chain"]

    assert payload["type"] == "FeatureCollection"
    assert meta["mass_conserved"] is True
    assert meta["source_segment_s"] == meta["occupancy_mass_s"] == 280.0
    assert meta["mass_error_s"] == 0.0
    assert meta["chain_count"] == len(chains) == 2
    assert [feature["properties"]["chain_index"] for feature in chains] == [0, 1]


def test_fixture_cli_writes_the_same_contract(tmp_path):
    output = tmp_path / "cellophane.json"
    assert main(["--out", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == build_fixture()
    assert output.read_bytes().endswith(b"\n")


def test_viewer_has_only_the_four_pr3_readouts():
    assert 'id="mass-check"' in HTML
    assert "properties.kind === 'accepted_chain'" in HTML
    assert "properties.kind === 'cell'" in HTML
    assert 'id="cell-detail"' in HTML
    assert 'id="d-occupancy"' in HTML
    assert 'id="d-peak"' in HTML
    assert 'id="d-version"' in HTML
    assert "segment ${fmt(meta.source_segment_s, 1)}s" in HTML
    assert "painted ${fmt(meta.occupancy_mass_s, 1)}s" in HTML
    assert "error ${fmt(meta.mass_error_s, 4)}s" in HTML


def test_viewer_uses_server_polygons_and_does_not_rebuild_hex_geometry():
    assert "feature.geometry.coordinates[0]" in HTML
    assert "hex_boundary" not in HTML
    assert "radius_u *" not in HTML


def test_viewer_has_no_external_basemap_or_network_dependency():
    assert "빈 배경 · 외부 지도 요청 없음" in HTML
    assert "https://" not in HTML
    assert "tileLayer" not in HTML
    assert "naver.maps" not in HTML
    assert "DATA_URL = '/cellophane/data'" in HTML


def test_cell_selection_is_clickable_and_keyboard_accessible():
    assert "[hidden] { display:none !important }" in HTML
    assert "polygon.addEventListener('click', choose)" in HTML
    assert "polygon.addEventListener('keydown'" in HTML
    assert "event.key === 'Enter' || event.key === ' '" in HTML
    assert "textContent = properties.cell_id" in HTML


def _paths_with_dev_console(enabled: bool) -> set[str]:
    environment = os.environ.copy()
    environment["DAENGS_DEV_CONSOLE"] = "true" if enabled else "false"
    command = (
        "from app.main import app; "
        "print('\\n'.join(sorted(route.path for route in app.routes "
        "if hasattr(route, 'path'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def test_cellophane_surface_is_behind_the_dev_console_gate():
    assert "/cellophane" not in _paths_with_dev_console(False)
    assert {"/cellophane", "/cellophane/data"} <= _paths_with_dev_console(True)
