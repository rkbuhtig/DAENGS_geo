"""모바일 Spatial Diary dev lab의 계산·표현 경계."""

import json
import math
from pathlib import Path

from app.features.spatial_diary.dev_lab import build_spatial_diary_ui_fixture

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "app" / "static" / "spatial_diary_lab.html").read_text(encoding="utf-8")


def test_fixture_uses_one_canonical_paint_generation_and_conserves_every_walk():
    payload = build_spatial_diary_ui_fixture()

    assert payload["fixture_version"] == 2
    assert len(payload["sheets"]) == 12
    assert payload["paint"]["radius_u"] == 8.0
    assert payload["paint"]["brush_bands_m"] == [3.0, 8.0, 20.0]
    assert payload["paint"]["brush_reach_m"] == 20.0
    assert all(
        math.isclose(sheet["source_segment_s"], sheet["occupancy_mass_s"])
        for sheet in payload["sheets"]
    )
    assert all(sheet["cells"] for sheet in payload["sheets"])
    assert len({cell["id"].split(":", 2)[0] for sheet in payload["sheets"] for cell in sheet["cells"]}) == 1


def test_fixture_has_session_owned_pins_and_a_distinct_larger_read_radius():
    payload = build_spatial_diary_ui_fixture()
    sessions = {sheet["session_id"] for sheet in payload["sheets"]}
    pins = payload["pins"]

    assert len(pins) == 7
    assert {pin["session_id"] for pin in pins} <= sessions
    assert all(pin["read_radius_m"] > payload["paint"]["brush_reach_m"] for pin in pins)
    assert any(len(sheet["participants"]) == 2 for sheet in payload["sheets"])
    assert all(pin["title"] and pin["summary"] and pin["narration"] for pin in pins)
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_fixture_separates_experimental_single_session_route_from_cellophane():
    payload = build_spatial_diary_ui_fixture()
    sessions = payload["sessions"]

    assert len(sessions) == len(payload["sheets"]) == 12
    assert payload["experimental_contract"]["route_is_persisted"] is False
    assert all(session["route"]["storage"] == "fixture_only_simplified_route" for session in sessions)
    assert all(session["route"]["segments"] for session in sessions)
    assert {
        segment["speed_band"]
        for session in sessions
        for segment in session["route"]["segments"]
    } == {"slow", "normal", "fast", "stopped"}
    ordered = [pin["event_index"] for pin in payload["pins"] if pin["session_id"] == "ui-walk-03"]
    assert ordered == [1, 2, 3]


def test_lab_is_a_mobile_map_diary_split_with_static_cellophane_compositing():
    assert "grid-template-rows:auto minmax(0,3fr) minmax(0,2fr)" in HTML
    assert "width:min(100vw,411px)" in HTML
    assert "DATA_URL = '/spatial-diary-lab/data'" in HTML
    assert "1-cell.remaining" in HTML
    assert "state.payload.display.sheet_alpha" in HTML
    assert "requestAnimationFrame" not in HTML
    assert "transition:" not in HTML


def test_lab_has_distinct_single_session_and_cohort_policies():
    assert 'id="session-mode"' in HTML
    assert 'id="cohort-mode"' in HTML
    assert 'data-policy="single-session"' in HTML
    assert 'data-policy="session-cohort"' in HTML
    assert "state.session.selectedSessionId" in HTML
    assert "state.cohort.selectedAreaKey" in HTML
    assert "renderSessionMode" in HTML
    assert "renderCohortMode" in HTML


def test_single_session_uses_ordered_route_and_cohort_uses_static_area_reading():
    assert "new naver.maps.Polyline" in HTML
    assert "L.polyline" in HTML
    assert "segment.speed_band" in HTML
    assert "approximate_start" in HTML
    assert "approximate_end" in HTML
    assert "event-marker" in HTML
    assert "시작·종료와 사건 순서는 합산하지 않습니다" in HTML


def test_lab_uses_real_map_provider_and_keeps_the_two_radii_distinct():
    assert "oapi.map.naver.com/openapi/v3/maps.js" in HTML
    assert "tile.openstreetmap.org" in HTML
    assert "selectedArea.readRadiusM" in HTML
    assert "state.payload.paint.brush_reach_m" in HTML
    assert "new naver.maps.Circle" in HTML
    assert "두 반경 비교" in HTML
    assert "HeatMap" not in HTML


def test_selection_drives_the_mode_specific_fixed_diary_reader():
    assert "state.session.selectedEpisodeId=pin.pin_id" in HTML
    assert "state.cohort.selectedAreaKey=area.key" in HTML
    assert "$('journal-title').textContent = title" in HTML
    assert "$('narration').textContent = narration" in HTML
    assert "metresBetween(pin.point,selectedArea.point) <= selectedArea.readRadiusM" in HTML
    assert 'id="previous"' in HTML
    assert 'id="next"' in HTML
