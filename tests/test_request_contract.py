from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.db import get_session
from app.features.hospital.api import HospitalSearchIn
from app.journey.api import Dest, JourneyIn
from app.main import app
from app.planning.state import CURRENT_STATE_VERSION, EditableState
from app.refine import tools
from app.refine.engine import refine
from app.refine.tools import ToolInputError


def test_legacy_state_is_migrated_without_silent_loss():
    old = {
        "lat": 37.5,
        "lng": 127.0,
        "target": {
            "night": True,
            "emergency": True,
            "at": "2026-08-21T12:00:00Z",
        },
    }

    state = EditableState.model_validate(old)

    assert state.state_version == CURRENT_STATE_VERSION
    assert state.target.night_service is True
    assert state.target.emergency_service is True
    assert state.time_intent is not None
    assert state.time_intent.kind == "service_at"
    assert state.time_intent.at == datetime.fromisoformat("2026-08-21T12:00:00+00:00")


def test_current_unversioned_state_is_stamped_and_unknown_fields_are_rejected():
    state = EditableState.model_validate({
        "lat": 37.5,
        "lng": 127.0,
        "target": {"night_service": True},
    })
    assert state.state_version == CURRENT_STATE_VERSION

    with pytest.raises(ValidationError):
        EditableState.model_validate({"lat": 37.5, "lng": 127.0, "typo": True})
    with pytest.raises(ValidationError):
        EditableState.model_validate({"state_version": 999, "lat": 37.5, "lng": 127.0})


@pytest.mark.parametrize("patch", [
    {"lat": 91, "lng": 127},
    {"lat": 37, "lng": 181},
    {"lat": 37, "lng": 127, "target": {"radius_m": 99_999_999}},
    {"lat": 37, "lng": 127, "target": {"limit": 999_999}},
    {"lat": 37, "lng": 127, "history": [{}] * 11},
])
def test_client_state_bounds_are_enforced(patch):
    with pytest.raises(ValidationError):
        EditableState.model_validate(patch)


def test_history_snapshots_are_migrated_and_validated_too():
    state = EditableState.model_validate({
        "lat": 37.5,
        "lng": 127.0,
        "history": [{"lat": 37.4, "lng": 127.1, "target": {"night": True}}],
    })
    assert state.history[0]["state_version"] == CURRENT_STATE_VERSION
    assert state.history[0]["target"]["night_service"] is True

    with pytest.raises(ValidationError):
        EditableState.model_validate({
            "lat": 37.5,
            "lng": 127.0,
            "history": [{"lat": 999, "lng": 127.1}],
        })


async def test_request_origin_overrides_round_tripped_state_without_history_entry():
    old = EditableState(lat=37.0, lng=127.0)

    result = await refine(
        old, edits=[], utterance=None, shown_ids=[], profile=None,
        lat=35.0, lng=129.0, default_radius=2000,
    )

    assert (result.state.lat, result.state.lng) == (35.0, 129.0)
    assert result.state.history == []
    assert (old.lat, old.lng) == (37.0, 127.0)


def test_legacy_set_time_tool_is_migrated_but_not_advertised():
    state = tools.apply(
        EditableState(lat=37.5, lng=127.0),
        "set_time",
        {"open_now": True, "night": True, "emergency": True},
    )
    assert state.target.open_now is True
    assert state.target.night_service is True
    assert state.target.emergency_service is True
    assert "set_time" not in tools.TOOLS


@pytest.mark.parametrize(("tool", "args"), [
    ("does_not_exist", {}),
    ("set_mode", {"mode": "bicycle"}),
    ("set_walk_option", {"option": "teleport"}),
    ("set_sort", {"sort": "random"}),
    ("set_walk_max_min", {"minutes": -1}),
    ("set_radius", {"m": 99_999_999}),
    ("set_origin", {"lat": 999, "lng": 127}),
    ("set_specialty", {"tags": ["fortune_telling"]}),
    ("set_time_intent", {"kind": "service_at"}),
    ("set_mode", {"mode": "walk", "surprise": True}),
])
def test_bad_tool_calls_are_rejected(tool, args):
    with pytest.raises(ToolInputError):
        tools.apply(EditableState(lat=37.5, lng=127.0), tool, args)


def test_api_input_models_reject_invalid_coordinates_and_unbounded_lists():
    with pytest.raises(ValidationError):
        HospitalSearchIn(origin=(999, -999))
    with pytest.raises(ValidationError):
        HospitalSearchIn()
    with pytest.raises(ValidationError):
        HospitalSearchIn(origin=(37.5, 127.0), shown_ids=list(range(1, 102)))
    with pytest.raises(ValidationError):
        JourneyIn(origin=(999, -999), dests=[Dest(lat=37.5, lng=127.0)])
    with pytest.raises(ValidationError):
        Dest(name="missing coordinates")


async def _no_db():
    yield None


def test_bad_edit_is_an_http_422_not_a_500():
    app.dependency_overrides[get_session] = _no_db
    try:
        with TestClient(app) as client:
            response = client.post("/hospital/search", json={
                "origin": [37.5, 127.0],
                "transport": "none",
                "with_evidence": False,
                "edits": [{"tool": "set_mode", "args": {"mode": "bicycle"}}],
            })
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 422
    assert "invalid args for set_mode" in response.json()["detail"]


def test_static_map_rejects_bad_query_before_provider_call():
    with TestClient(app) as client:
        bad_origin = client.get("/map/static?lat=999&lng=127")
        bad_marker = client.get("/map/static?lat=37.5&lng=127&m=999:127:A:0")
    assert bad_origin.status_code == 422
    assert bad_marker.status_code == 422
