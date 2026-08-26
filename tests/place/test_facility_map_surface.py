"""`/facility-map`이 legacy 차집합이 아니라 canonical Place 계약을 소비한다."""

from pathlib import Path

HTML = (
    Path(__file__).resolve().parents[2] / "app" / "static" / "facility.html"
).read_text(encoding="utf-8")


def test_facility_map_uses_one_canonical_post_contract():
    assert "fetch('/v2/places/search'" in HTML
    assert "method:'POST'" in HTML
    assert "'/facility/search" not in HTML
    assert "Promise.all" not in HTML


def test_facility_map_reads_place_hit_without_internal_database_ids():
    assert "const f = hit.place" in HTML
    assert "hit.evaluations.dog_access" in HTML
    assert "f.facts.pet_access" in HTML
    assert "f.key.source" in HTML
    assert "okIds" not in HTML


def test_facility_map_keeps_all_three_evaluation_states_visible():
    assert "const counts = {compatible:0, incompatible:0, unknown:0}" in HTML
    assert "입장 조건상 가능" in HTML
    assert "조건 불일치" in HTML
    assert "정보 부족 · 확인 필요" in HTML
    assert "미만/이하 미확인" in HTML
    assert "≤" not in HTML
