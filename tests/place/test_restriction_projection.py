"""조건 술어를 이 개에 대고 볼 때 — 무엇을 숨기고 무엇을 판정하는가.

Decision: #70

**두 가지 다른 일을 한다.** 섞으면 안 된다.

    투영   `applies_to` 로 걸러 이 개에게 보여줄 칩을 정한다
    판정   그중 "못 간다" 가 증명되는 것만 `incompatible` 로 올린다

`require:muzzle@size:large` 는 대형견에게 **보이지만** 곧바로 못 가는 이유는 아니다.
반대로 실제로 준비했는지 모르므로 가능하다고 확정하지도 않는다.
"""

from app.place.contracts import RestrictionChip, RestrictionFacts
from app.place.restriction_projection import project


def _facts(
    *chips: tuple[str, str, str],
    state: str = "restricted",
    parse_state: str = "mapped",
) -> RestrictionFacts:
    return RestrictionFacts(
        state=state,
        parse_state=parse_state,
        chips=[
            RestrictionChip(code=code, label=label, applies_to=applies_to)
            for code, label, applies_to in chips
        ],
    )


MUZZLE_LARGE = ("require:muzzle", "입마개·대형견", "size:large")
LEASH_ALL = ("require:leash", "목줄", "all")
DENY_LARGE = ("deny:size", "크기 제한·대형견", "size:large")
DENY_SENIOR = ("deny:age", "나이 제한·노령견", "age:senior")
DENY_PUPPY = ("deny:age", "나이 제한·어린 개", "age:puppy")
DENY_DOG = ("deny:species_dog", "개 불가", "all")
CARRIER = ("require:carrier", "케이지", "all")
BEHAVIOR = ("deny:behavior", "성격 제한", "all")
VACCINATION = ("require:vaccination", "접종 필수", "all")


# ---------------------------------------------------------------- 투영
def test_conditional_chip_disappears_for_a_dog_it_does_not_apply_to():
    """2kg 개 보호자가 "입마개 필요" 를 보면 안 된다."""
    result = project(_facts(MUZZLE_LARGE, LEASH_ALL), dog_size="small", dog_age_years=3)
    assert [chip.code for chip in result.chips] == ["require:leash"]


def test_conditional_chip_stays_for_the_dog_it_applies_to():
    result = project(_facts(MUZZLE_LARGE, LEASH_ALL), dog_size="large", dog_age_years=3)
    assert [chip.code for chip in result.chips] == ["require:muzzle", "require:leash"]


def test_unknown_dog_size_keeps_every_chip():
    """숨기는 실수가 보여주는 실수보다 나쁘다 — 보호자는 본 것만 확인할 수 있다."""
    result = project(_facts(MUZZLE_LARGE, LEASH_ALL), dog_size=None, dog_age_years=None)
    assert len(result.chips) == 2


def test_subjects_the_profile_cannot_judge_are_kept():
    """수컷·중성화·생리·견종은 프로필로 못 가른다. 걸러내면 조건을 숨기는 것이다."""
    facts = _facts(
        ("require:manner_belt", "매너벨트·수컷", "sex:male"),
        ("deny:breed", "견종 제한·일부 견종", "breed:named"),
    )
    result = project(facts, dog_size="small", dog_age_years=2)
    assert len(result.chips) == 2


def test_medium_up_subject_covers_medium_and_large():
    facts = _facts(("require:muzzle", "입마개·중대형견", "size:medium_up"))
    assert project(facts, dog_size="medium", dog_age_years=3).chips
    assert project(facts, dog_size="large", dog_age_years=3).chips
    assert not project(facts, dog_size="small", dog_age_years=3).chips


# ---------------------------------------------------------------- 판정
def test_size_denial_blocks_only_the_denied_size():
    denied = project(_facts(DENY_LARGE), dog_size="large", dog_age_years=3)
    allowed = project(_facts(DENY_LARGE), dog_size="small", dog_age_years=3)

    assert denied.state == "incompatible"
    assert denied.reason == "size_denied"
    assert denied.blocking == ["deny:size"]
    # 소형견에게는 칩 자체가 안 보이므로 판정할 것도 없다.
    assert allowed.state == "compatible"
    assert allowed.chips == []


def test_age_rules_stay_unknown_until_the_source_threshold_is_preserved():
    """어린 개·노령견을 한 고정 나이로 발명하지 않는다."""
    for chip, age in ((DENY_PUPPY, 3), (DENY_SENIOR, 12)):
        result = project(_facts(chip), dog_size="small", dog_age_years=age)
        assert (result.state, result.reason) == ("unknown", "unresolved_condition")
        assert result.blocking == []


def test_explicit_dog_denial_blocks_without_more_profile_data():
    result = project(_facts(DENY_DOG), dog_size="small", dog_age_years=3)
    assert (result.state, result.reason) == ("incompatible", "species_denied")
    assert result.blocking == ["deny:species_dog"]


def test_unresolved_conditions_are_shown_without_claiming_compatibility():
    """장비·접종·행동 상태를 요청에서 모르므로 보이되 가능으로 확정하지 않는다."""
    result = project(
        _facts(MUZZLE_LARGE, CARRIER, VACCINATION, BEHAVIOR),
        dog_size="large",
        dog_age_years=3,
    )
    assert (result.state, result.reason) == ("unknown", "unresolved_condition")
    assert {chip.code for chip in result.chips} == {
        "require:muzzle", "require:carrier", "require:vaccination", "deny:behavior",
    }
    assert result.blocking == []


# ---------------------------------------------------------------- 미상
def test_unknown_restrictions_stay_unknown():
    result = project(
        RestrictionFacts(state="unknown"), dog_size="small", dog_age_years=3,
    )
    assert result.state == "unknown"
    assert result.reason == "restrictions_unknown"
    assert result.chips == []


def test_incomplete_parse_without_a_known_blocker_stays_unknown():
    partial = project(
        _facts(DENY_LARGE, parse_state="partial"),
        dog_size="medium",
        dog_age_years=3,
    )
    raw_only = project(
        _facts(parse_state="raw_only"), dog_size="medium", dog_age_years=3,
    )
    assert (partial.state, partial.reason) == ("unknown", "incomplete_restrictions")
    assert (raw_only.state, raw_only.reason) == ("unknown", "incomplete_restrictions")


def test_none_confirmed_is_compatible_with_no_chips():
    result = project(
        _facts(state="none_confirmed"), dog_size="large", dog_age_years=12,
    )
    assert result.state == "compatible"
    assert result.chips == []


def test_missing_facts_are_unknown_not_compatible():
    """아직 파생 안 된 행을 "조건 없음" 으로 읽으면 안 된다."""
    result = project(None, dog_size="small", dog_age_years=3)
    assert result.state == "unknown"
