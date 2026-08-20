"""지오코딩 복구의 질의 후보 생성. 실패한 주소가 어떤 모양이었는지가 여기 박혀 있다."""

import pytest

from app.ingest.geocode_repair import address_candidates


def _raw(road: str = "", lot: str = "") -> dict:
    return {"ROAD_NM_ADDR": road, "LOTNO_ADDR": lot}


def test_road_comes_before_lot():
    """도로명이 지번보다 정확하다. 순서가 곧 우선순위다."""
    tiers = [t for t, _ in address_candidates(
        _raw(road="서울특별시 노원구 월계로 333", lot="서울특별시 노원구 월계동 3-94"))]
    assert tiers.index("road") < tiers.index("lot")


def test_detail_is_stripped_as_a_second_try():
    """'월계로 333, 2층 (월계동)' 은 상세를 떼야 잡히는 경우가 있다 — 실측 39건이 이 단계에서 살았다."""
    cands = {t: q for t, q in address_candidates(
        _raw(road="서울특별시 노원구 월계로 333, 2층 (월계동)"))}
    assert cands["road"] == "서울특별시 노원구 월계로 333, 2층 (월계동)"
    assert cands["road_stripped"] == "서울특별시 노원구 월계로 333"


def test_no_duplicate_queries():
    """상세가 없으면 원본과 상세제거본이 같다. 같은 주소를 두 번 질의하지 않는다."""
    queries = [q for _, q in address_candidates(_raw(road="대구광역시 동구 동북로75길 13"))]
    assert queries == ["대구광역시 동구 동북로75길 13"]


def test_lot_only_still_produces_candidates():
    """도로명이 비어도 지번으로 시도한다 — 실측 48건이 지번으로만 살았다."""
    tiers = [t for t, _ in address_candidates(_raw(lot="경상남도 사천시 사천읍 수석리 259-3"))]
    assert tiers and all(t.startswith("lot") for t in tiers)


@pytest.mark.parametrize("raw", [_raw(), _raw(road="   ", lot="")])
def test_no_address_no_candidates(raw):
    """주소가 아예 없으면 질의할 게 없다. 빈 문자열을 제공사에 던지지 않는다."""
    assert address_candidates(raw) == []
