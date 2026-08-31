"""PR2 Cellophane GeoJSON 계약.

경로의 continuity, 서버 육각형, 계산 진단을 한 결정론적 payload로 내보내되 표현 색상이나
지도 SDK 상태는 넣지 않는다.
"""

import json
import math
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.features.territory.geojson import (
    cellophane_feature_collection,
    dumps_cellophane_geojson,
    spatial_cell_id,
)
from app.features.territory.paint import NARROW_STEP, PaintSpec, paint_sheet
from app.features.walk.facts import Segment
from app.features.walk.models import WalkFix
from app.geo.cells import hex_boundary_latlng

START = datetime(2026, 8, 31, 9, tzinfo=UTC)
RADIUS_U = 8.0


def _fix(seq: int, client_chain: int, seconds: float, lat: float, lng: float) -> WalkFix:
    return WalkFix(
        client_seq=seq,
        chain_index=client_chain,
        at=START + timedelta(seconds=seconds),
        lat=lat,
        lng=lng,
        accuracy_m=3.0,
        is_mock=False,
    )


def _segments() -> list[Segment]:
    a = _fix(0, 0, 0.0, 37.49790, 127.02760)
    b = _fix(1, 0, 2.5, 37.49790, 127.02765)
    c = _fix(2, 0, 5.0, 37.49790, 127.02770)
    d = _fix(3, 1, 20.0, 37.49900, 127.02900)
    e = _fix(4, 1, 23.5, 37.49900, 127.02905)
    return [
        Segment(a=d, b=e, dt=3.5, dist=4.4, offset_m=8.8, moving=True, chain_index=1),
        Segment(a=b, b=c, dt=2.5, dist=4.4, offset_m=4.4, moving=True, chain_index=0),
        Segment(a=a, b=b, dt=2.5, dist=4.4, offset_m=0.0, moving=True, chain_index=0),
    ]


def _payload():
    segments = _segments()
    sheet = paint_sheet("session-1", START, segments, RADIUS_U, NARROW_STEP)
    return sheet, segments, cellophane_feature_collection(sheet, segments)


def test_each_chain_is_its_own_linestring_without_a_bridge():
    _sheet, _segments_input, payload = _payload()
    chains = [feature for feature in payload["features"]
              if feature["properties"]["kind"] == "accepted_chain"]

    assert [feature["properties"]["chain_index"] for feature in chains] == [0, 1]
    assert [feature["properties"]["segment_count"] for feature in chains] == [2, 1]
    assert chains[0]["geometry"] == {
        "type": "LineString",
        "coordinates": [
            [127.02760, 37.49790],
            [127.02765, 37.49790],
            [127.02770, 37.49790],
        ],
    }
    assert chains[1]["geometry"]["coordinates"] == [
        [127.02900, 37.49900],
        [127.02905, 37.49900],
    ]


def test_disconnected_segments_in_one_chain_fail_instead_of_drawing_a_line():
    segments = _segments()
    disconnected = [segments[2], Segment(
        a=segments[0].a,
        b=segments[0].b,
        dt=segments[0].dt,
        dist=segments[0].dist,
        offset_m=segments[0].offset_m,
        moving=segments[0].moving,
        chain_index=0,
    )]
    sheet = paint_sheet("broken", START, disconnected, RADIUS_U, NARROW_STEP)
    with pytest.raises(ValueError, match="segment가 이어지지 않는다"):
        cellophane_feature_collection(sheet, disconnected)


def test_cell_polygons_are_server_generated_closed_geojson_rings():
    sheet, _segments_input, payload = _payload()
    cells = [feature for feature in payload["features"]
             if feature["properties"]["kind"] == "cell"]
    assert [(feature["properties"]["q"], feature["properties"]["r"])
            for feature in cells] == sorted(sheet.occupancy)

    first = cells[0]
    ring = first["geometry"]["coordinates"][0]
    assert first["geometry"]["type"] == "Polygon"
    assert len(ring) == 7
    assert ring[0] == ring[-1]

    q, r = first["properties"]["q"], first["properties"]["r"]
    expected = [[lng, lat] for lat, lng in reversed(hex_boundary_latlng(q, r, RADIUS_U))]
    expected.append(expected[0].copy())
    assert ring == expected, "GeoJSON 좌표는 [lng, lat] 순서이고 외곽 링은 반시계여야 한다"
    signed_area = math.fsum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in pairwise(ring)
    ) / 2
    assert signed_area > 0


def test_meta_exposes_exact_mass_diagnostics_and_paint_identity():
    sheet, segments, payload = _payload()
    meta = payload["meta"]
    source_s = math.fsum(segment.dt for segment in segments)
    occupancy_s = math.fsum(sheet.occupancy.values())

    assert meta["session_id"] == "session-1"
    assert meta["source_segment_s"] == source_s
    assert meta["occupancy_mass_s"] == occupancy_s
    assert meta["mass_error_s"] == occupancy_s - source_s
    assert meta["mass_conserved"] is True
    assert meta["paint_fp"] == sheet.paint_fp
    assert meta["sample_step_m"] == sheet.sample_step_m
    assert meta["segment_count"] == 3
    assert meta["chain_count"] == 2
    assert meta["cell_count"] == len(sheet.occupancy)


def test_feature_and_json_order_is_deterministic():
    sheet, segments, payload = _payload()
    reversed_payload = cellophane_feature_collection(sheet, reversed(segments))
    assert reversed_payload == payload
    assert dumps_cellophane_geojson(sheet, segments) == dumps_cellophane_geojson(
        sheet, reversed(segments))
    assert json.loads(dumps_cellophane_geojson(sheet, segments)) == payload


def test_cell_id_is_spatial_identity_not_paint_identity():
    cell = (12, -7)
    identifier = spatial_cell_id("hex-v1", 8.0, cell)
    assert identifier == "hex-v1:8.0:12:-7"
    assert spatial_cell_id("hex-v1", 8, cell) == identifier
    assert spatial_cell_id("hex-v1", 15.0, cell) != identifier
    assert spatial_cell_id("hex-v2", 8.0, cell) != identifier


def test_unknown_grid_version_fails_instead_of_using_current_geometry():
    import dataclasses

    sheet, segments, _payload_value = _payload()
    future_spec = PaintSpec(
        paint_version=sheet.paint_version,
        grid_version="hex-v2",
        radius_u=sheet.radius_u,
        profile_name=sheet.profile,
        profile_fp=sheet.profile_fp,
        sample_step_m=sheet.sample_step_m,
    )
    future_sheet = dataclasses.replace(
        sheet,
        grid_version=future_spec.grid_version,
        paint_fp=future_spec.fingerprint,
    )
    with pytest.raises(ValueError, match="지원하지 않는 grid_version"):
        cellophane_feature_collection(future_sheet, segments)


def test_cell_support_mismatch_fails_closed():
    import dataclasses

    sheet, segments, _payload_value = _payload()
    malformed = dataclasses.replace(sheet, peak={})
    with pytest.raises(ValueError, match="occupancy와 peak의 셀 집합"):
        cellophane_feature_collection(malformed, segments)
