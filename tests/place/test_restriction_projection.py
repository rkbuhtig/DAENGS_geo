"""조건 술어를 이 개에 대고 볼 때 — 무엇을 숨기고 무엇을 판정하는가.

Decision: #70

**두 가지 다른 일을 한다.** 섞으면 안 된다.

    투영   `applies_to` 로 걸러 이 개에게 보여줄 칩을 정한다
    판정   그중 "못 간다" 가 증명되는 것만 `incompatible` 로 올린다

`require:muzzle@size:large` 는 대형견에게 **보이지만** 못 가는 이유가 아니다 —
입마개를 채우면 간다. 이 구분이 무너지면 갈 수 있는 곳이 조용히 사라진다.
"""

from app.place.contracts import RestrictionChip, RestrictionFacts
from app.place.restriction_projection import SENIOR_YEARS, project


def _facts(*chips: tuple[str, str, str], state: str = "restricted") -> RestrictionFacts:
    return RestrictionFacts(
        state=state,
        parse_state="mapped",
        chips=[
            RestrictionChip(code=code, label=label, applies_to=applies_to)
            for code, label, applies_to in chips
        ],
    )


MUZZLE_LARGE = ("require:muzzle", "입마개·대형견", "size:large")
LEASH_ALL = ("require:leash", "목줄", "all")
DENY_LARGE = ("deny:size", "크기 제한·대형견", "size:large")
DENY_SENIOR = ("deny:age", "나이 제한·노령견", "age:senior")
CARRIER = ("require:carrier", "케이지", "all")
BEHAVIOR = ("deny:behavior", "성격 제한", "all")


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


def test_age_denial_uses_the_profile_age():
    senior = project(_facts(DENY_SENIOR), dog_size="small", dog_age_years=SENIOR_YEARS)
    young = project(_facts(DENY_SENIOR), dog_size="small", dog_age_years=3)

    assert senior.state == "incompatible"
    assert senior.reason == "age_denied"
    assert young.state == "compatible"


def test_missing_age_is_unknown_not_incompatible():
    """모르는 것을 불가로 바꾸면 갈 수 있는 곳이 조용히 사라진다."""
    result = project(_facts(DENY_SENIOR), dog_size="small", dog_age_years=None)
    assert result.state == "unknown"
    assert result.reason == "missing_dog_age"
    assert result.blocking == ["deny:age"]


def test_carrier_and_hold_are_shown_but_never_judged():
    """초대형 케이지가 있을 수도 있고 시설이 말하는 규격을 우리는 모른다."""
    result = project(_facts(CARRIER), dog_size="large", dog_age_years=3)
    assert result.state == "compatible"
    assert [chip.code for chip in result.chips] == ["require:carrier"]


def test_behavior_is_shown_but_never_judged():
    """이 개가 공격적인지 우리는 모른다."""
    result = project(_facts(BEHAVIOR), dog_size="large", dog_age_years=3)
    assert result.state == "compatible"
    assert result.chips


def test_muzzle_requirement_is_not_a_denial():
    """입마개를 채우면 간다. 요구를 배제로 읽으면 후보가 잘못 사라진다."""
    result = project(_facts(MUZZLE_LARGE), dog_size="large", dog_age_years=3)
    assert result.state == "compatible"
    assert [chip.code for chip in result.chips] == ["require:muzzle"]


# ---------------------------------------------------------------- 미상
def test_unknown_restrictions_stay_unknown():
    result = project(
        RestrictionFacts(state="unknown"), dog_size="small", dog_age_years=3,
    )
    assert result.state == "unknown"
    assert result.reason == "restrictions_unknown"
    assert result.chips == []


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
