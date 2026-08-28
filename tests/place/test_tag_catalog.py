"""이름 → 유형 태그 사전이 함정에 안 걸리고, 겹침을 버리지 않는가.

Decision: #72

이 사전은 **이름에서 추론한다** — 근거 등급표(#70 §3)에서 가장 약한 칸이다.
그래서 두 가지를 잠근다.

  kind 제약   유형어가 이름에 있다고 그 유형인 것이 아니다. `번동숲속카페` 는
              카페이고 `공원약국` 은 약국이다. 규칙마다 붙을 수 있는 kind 를 적는다
  겹침 보존   `일산호수공원 반려견놀이터` 는 공원이면서 놀이터다. 태그는 배타
              분류가 아니므로 하나를 고르지 않는다 — 어느 facet 을 눌러도 나와야 한다

픽스처는 규칙별 대표 + 함정을 사람이 검토한 기대값이다. `restrictions` gold set 과
같은 역할이며, 나중에 이름 추출기를 잴 때 기준이 된다.
"""

import json
from pathlib import Path

import pytest

from app.place.tag_catalog import (
    KNOWN_CODES,
    LABELS,
    TAG_RULES_VERSION,
    Evidence,
    rules_for_kind,
    tags_for,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "place_tag_cases.json"


def _cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_fixture_matches_the_current_rules_version():
    """규칙을 고치고 픽스처를 안 고치면 기대값이 조용히 낡는다."""
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert payload["rules_version"] == TAG_RULES_VERSION


@pytest.mark.parametrize("case", _cases(), ids=lambda c: f"{c['kind']}:{c['name']}")
def test_gold_cases(case: dict):
    got = [tag.code for tag in tags_for(case["name"], case["kind"])]
    assert got == case["tags"], case["name"]


# ------------------------------------------------------------------ kind 제약
@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("번동숲속카페", "cafe"),      # 숲이 아니라 카페다
        ("숲속애견랜드", "cafe"),
        ("멍숲", "cafe"),
        ("공원약국", "pharmacy"),      # 공원이 아니라 약국이다
        ("숲속아지양이", "grooming"),
    ],
)
def test_type_words_outside_travel_are_not_tagged(name: str, kind: str):
    """**실측된 함정이다.** kind 제약이 없으면 이 이름들이 전부 유형 태그를 받는다."""
    assert [t.code for t in tags_for(name, kind) if t.code.startswith("type:")] == []


def test_dog_first_rule_reaches_beyond_travel():
    """반려견 전용은 `travel` 밖에도 있다 — 애견카페가 같은 규칙을 탄다."""
    assert any(
        t.code == "type:dog_park" for t in tags_for("○○ 애견파크", "cafe")
    )


def test_no_rule_applies_to_every_kind():
    """kind 를 안 적은 규칙이 생기면 함정 테스트가 통째로 무력해진다."""
    for kind in ("hospital", "pharmacy", "shopping", "grooming"):
        assert not rules_for_kind(kind), f"{kind} 에 붙는 규칙이 생겼다"


# ------------------------------------------------------------------ 겹침
def test_overlapping_types_are_both_kept():
    """`애견공원` 은 놀이터이면서 공원이다. 하나를 고르면 다른 facet 에서 사라진다."""
    codes = [t.code for t in tags_for("삼막애견공원", "travel")]
    assert "type:dog_park" in codes
    assert "type:park" in codes


def test_rest_area_dog_park_keeps_both():
    """발견 축(휴게소 놀이터)이 두 유형을 다 갖는다."""
    codes = [t.code for t in tags_for("진주휴게소반려견놀이터", "travel")]
    assert {"type:dog_park", "type:rest_area"} <= set(codes)


# ------------------------------------------------------------------ 함의
def test_implications_ride_along_and_are_not_duplicated():
    codes = [t.code for t in tags_for("강문해변", "travel")]
    assert codes == ["type:beach", "environment:natural", "activity:water"]
    assert len(codes) == len(set(codes))


def test_dog_park_implies_role_and_activity():
    codes = {t.code for t in tags_for("성곡반려견놀이터", "travel")}
    assert {"role:dog_primary", "activity:run"} <= codes


# ------------------------------------------------------------------ 어휘 규율
def test_every_emitted_code_is_declared_and_labelled():
    for case in _cases():
        for tag in tags_for(case["name"], case["kind"]):
            assert tag.code in KNOWN_CODES, tag.code
            assert tag.code in LABELS, tag.code
            assert tag.label == LABELS[tag.code]


def test_evidence_grade_is_recorded():
    """이름 추론은 가장 약한 근거다. 그 사실이 태그에 남아야 한다 (#70 §3)."""
    for tag in tags_for("강문해변", "travel"):
        assert tag.evidence is Evidence.NAME_RULE


def test_absence_is_not_a_negative_signal():
    """**#72 §2.** 태그가 없는 것은 "그 유형이 아니다" 가 아니라 "이름이 말하지 않았다".

    이 테스트가 지키는 것은 코드가 아니라 계약이다 — `tags_for` 는 부재를 나타내는
    값을 만들지 않는다. 음성 태그가 생기면 소비자가 `NOT` 필터를 만들 수 있게 된다.
    """
    assert tags_for("이름이 아무것도 말하지 않는 곳", "travel") == ()
    for case in _cases():
        for tag in tags_for(case["name"], case["kind"]):
            assert not tag.code.startswith("not:"), "음성 태그가 생겼다"
            assert "없음" not in tag.code
