"""점령지 선별 — 격자·우선순위·결정론 계약."""

import math

from app.geo.cells import GRID_VERSION, hex_center_latlng
from app.ingest.territory_sites import (
    TERRITORY_SITE_RADIUS_U,
    hex_cell,
    hex_center,
    select,
)


def _lamp(lat, lng, kind="한전주"):
    return {"lat": lat, "lng": lng, "kind": kind, "instt": None, "as_of": None}


def test_one_site_per_cell():
    """같은 셀에 여럿 있어도 하나만 남는다 — 원본 12m 간격이 판정 원을 겹치게 하므로."""
    base = [_lamp(37.5000 + i * 0.00005, 127.0000) for i in range(8)]
    picked = select(base)
    assert len({p["site_id"] for p in picked}) == len(picked)


def test_kepco_pole_wins_over_dedicated():
    """한전주가 진짜 전봇대다. 같은 셀이면 형태 우선순위가 거리보다 앞선다."""
    q, r = hex_cell(37.5, 127.0)
    cx, cy = hex_center(q, r)
    center_lat, center_lng = hex_center_latlng(q, r)
    picked = select(
        [
            _lamp(center_lat, center_lng, "전용주"),
            _lamp(center_lat + 0.00001, center_lng + 0.00001, "한전주"),
        ]
    )
    expected_id = f"territory-site:{GRID_VERSION}:{round(TERRITORY_SITE_RADIUS_U)}:{q}:{r}"
    kinds = [p["kind"] for p in picked if p["site_id"] == expected_id]
    assert kinds == ["한전주"]
    assert math.isfinite(cx) and math.isfinite(cy)


def test_selection_is_deterministic():
    """같은 입력이면 같은 점령지. 순서가 바뀌어도 결과가 흔들리면 안 된다."""
    lamps = [_lamp(37.5 + i * 0.0004, 127.0 + i * 0.0003, "전용주") for i in range(30)]
    first = {(p["site_id"], p["lat"], p["lng"]) for p in select(lamps)}
    second = {(p["site_id"], p["lat"], p["lng"]) for p in select(list(reversed(lamps)))}
    assert first == second


def test_empty_cells_get_no_site():
    """후보가 없는 셀은 비운다 — 없는 자리에 점령지를 만들지 않는다."""
    assert len(select([_lamp(37.5, 127.0)])) == 1


def test_site_id_carries_grid_version_and_radius():
    """격자 버전과 반지름이 ID에 박혀야 다른 격자와 섞이지 않는다."""
    picked = select([_lamp(37.5, 127.0)], radius_u=200.0)
    assert picked[0]["site_id"].startswith(f"territory-site:{GRID_VERSION}:200:")
