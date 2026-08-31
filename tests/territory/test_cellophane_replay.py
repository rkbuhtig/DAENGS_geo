"""PR4 Android export local replay 계약."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scripts.spikes.territory_paint.cellophane_replay import (
    REPO_ROOT,
    VARIANTS,
    DeviceExport,
    main,
    replay_export,
)
from scripts.verify.walk_fixture import route

START = datetime(2026, 8, 31, 9, tzinfo=UTC)


def _export() -> dict:
    fixes = []
    for row in route():
        fixes.append({
            "client_seq": row["client_seq"],
            "chain_index": row["chain_index"],
            "at": (START + timedelta(seconds=row["offset_s"])).isoformat(),
            "lat": row["lat"],
            "lng": row["lng"],
            "accuracy_m": row["accuracy_m"],
            "is_mock": True,
        })
    return {
        "format": 1,
        "session": {
            "id": "synthetic-replay",
            "dog_id": None,
            "started_at": START.isoformat(),
            "ended_at": (START + timedelta(seconds=310)).isoformat(),
        },
        "fixes": fixes,
    }


def _clock():
    value = -0.001

    def tick() -> float:
        nonlocal value
        value += 0.001
        return value

    return tick


def test_android_export_runs_all_four_candidates_through_the_same_contract():
    report, geojsons = replay_export(_export(), clock=_clock())
    source = report["input"]
    rows = report["comparison"]["variants"]

    assert [row["key"] for row in rows] == [variant.key for variant in VARIANTS]
    assert set(geojsons) == {row["geojson_file"] for row in rows}
    assert source["fix_count"] == len(_export()["fixes"])
    assert source["chain_count"] == 2
    assert source["segment_count"] > 0
    assert all(row["mass_error_s"] == pytest.approx(0.0, abs=1e-9) for row in rows)
    assert all(row["local_anchor_count"] > 0 for row in rows)
    assert all(row["paint_ms"] == pytest.approx(1.0) for row in rows)
    assert all(row["serialize_ms"] == pytest.approx(1.0) for row in rows)


def test_candidate_geojson_is_deterministic_and_keeps_chains_separate():
    _first_report, first = replay_export(_export(), clock=_clock())
    _second_report, second = replay_export(_export(), clock=_clock())
    assert first == second

    payload = json.loads(first["cellophane-r8-step.geojson"])
    chains = [
        feature for feature in payload["features"]
        if feature["properties"]["kind"] == "accepted_chain"
    ]
    assert [chain["properties"]["chain_index"] for chain in chains] == [0, 1]
    assert payload["meta"]["mass_conserved"] is True


def test_summary_has_comparison_metrics_but_no_raw_location_fields():
    report, _geojsons = replay_export(_export(), clock=_clock())
    encoded = json.dumps(report, sort_keys=True)
    required = {
        "cell_count",
        "payload_bytes",
        "paint_ms",
        "support_area_m2",
        "local_occupancy_p50_s",
        "local_occupancy_max_s",
        "top10_mass_share",
        "gap_brush_overlap_count",
    }
    assert required <= report["comparison"]["variants"][0].keys()
    for forbidden in ('"fixes"', '"lat"', '"lng"', '"q"', '"r"', '"cell_id"'):
        assert forbidden not in encoded


def test_export_contract_rejects_unknown_format_and_duplicate_sequence():
    wrong = _export()
    wrong["format"] = 2
    with pytest.raises(ValidationError):
        DeviceExport.model_validate(wrong)

    duplicate = _export()
    duplicate["fixes"][1]["client_seq"] = duplicate["fixes"][0]["client_seq"]
    with pytest.raises(ValidationError, match="client_seq must be unique"):
        DeviceExport.model_validate(duplicate)


def test_cli_writes_report_and_four_geojsons_outside_the_repo(tmp_path, capsys):
    source = tmp_path / "walk.json"
    out = tmp_path / "replay"
    source.write_text(json.dumps(_export()), encoding="utf-8")

    assert main(["--input", str(source), "--out", str(out)]) == 0
    assert {path.name for path in out.iterdir()} == {
        "report.json",
        *(f"cellophane-{variant.key}.geojson" for variant in VARIANTS),
    }
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["input"]["session_id"] == "synthetic-replay"
    assert "written to" in capsys.readouterr().out


def test_cli_refuses_to_read_or_write_raw_location_artifacts_inside_repo(tmp_path):
    external = tmp_path / "walk.json"
    external.write_text(json.dumps(_export()), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--input", str(REPO_ROOT / "walk.json"), "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit):
        main(["--input", str(external), "--out", str(REPO_ROOT / "replay")])


def test_local_read_radius_must_be_positive():
    with pytest.raises(ValueError, match="local_read_m"):
        replay_export(_export(), local_read_m=0)
