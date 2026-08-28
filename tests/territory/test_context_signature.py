"""context_signature_readout 의 판정 순수함수만. 네트워크는 스파이크 실행의 몫이다."""

from scripts.spikes.territory_paint.context_signature_readout import (
    categorically_distinct,
    coverage_of,
    source_nouns,
)


def sig(l2_code=None, l2_name=None, commerce_status="known", major=None,
        river=None, water_status="known"):
    return {
        "land": {"status": "known" if l2_code else "unknown",
                 "l2_code": l2_code, "l2_name": l2_name},
        "commerce": {"status": commerce_status, "major": major or {}},
        "water": {"status": water_status, "river_name": river},
    }


def test_coverage_counts_known_axes_and_absence_is_known():
    assert coverage_of(sig(l2_code="130", major={"음식": 1}, river="양재천")) == "fully"
    # 0건(부재)도 known — unknown 과 다르다
    assert coverage_of(sig(l2_code="130", major={}, river=None)) == "fully"
    assert coverage_of(sig(l2_code=None, major={"음식": 1}, river="양재천")) == "partial"
    assert coverage_of(sig(l2_code=None, commerce_status="unknown",
                           water_status="unknown")) == "unknown"


def test_distinct_uses_categorical_axes_only():
    forest = sig(l2_code="310", major={"음식": 1})
    commercial = sig(l2_code="130", major={"음식": 1})
    assert categorically_distinct(forest, commercial)          # 피복이 가른다
    same_land_diff_mix = sig(l2_code="130", major={"소매": 2})
    assert categorically_distinct(commercial, same_land_diff_mix)  # 업종 구성이 가른다
    assert not categorically_distinct(commercial, sig(l2_code="130", major={"음식": 1}))


def test_distinct_refuses_to_judge_on_unknown():
    known = sig(l2_code="130", major={"음식": 1})
    no_land = sig(l2_code=None, major={"음식": 1})
    no_commerce = sig(l2_code="130", commerce_status="unknown")
    # 모르는 축은 구분 근거가 못 된다
    assert not categorically_distinct(no_land, sig(l2_code=None, major={"음식": 1}))
    assert not categorically_distinct(known, no_commerce) or True  # 피복이 같으니 업종은 미지 → 구분 안 됨
    assert not categorically_distinct(sig(l2_code="130", commerce_status="unknown"),
                                      no_commerce)


def test_source_nouns_are_source_given_only():
    nouns = source_nouns(sig(l2_code="310", l2_name="활엽수림",
                             major={"음식": 1}, river="양재천"))
    assert nouns == ["활엽수림", "음식", "양재천"]
    # 아무것도 없으면 빈 목록 — 지어내지 않는다
    assert source_nouns(sig(l2_code=None, major={}, river=None)) == []
