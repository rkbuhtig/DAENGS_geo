"""데려가는 개에 맞춰 조건 칩을 거르고, **증명 가능한 것만** 판정한다.

[결정 #70](../../docs/decisions/2026-08-27-place-row-tags.md) §3 이 "넓게 적고 좁게
판정한다" 고 정했다. 판독표는 원문이 말한 것을 전부 술어로 적고, 그 술어 중 무엇을
`incompatible` 로 승격할지는 **여기가** 정한다.

## 두 가지 다른 일

    투영   `applies_to` 를 이 개에 대고 걸러 남길 칩을 정한다 (표시)
    판정   남은 것 중 "못 간다" 가 증명되는 것만 골라낸다 (평가)

둘을 섞으면 안 된다. `require:muzzle@size:large` 는 대형견에게 **표시**되지만
`incompatible` 이 아니다 — 입마개를 채우면 갈 수 있다.

## 무엇을 판정하고 무엇을 안 하나

판정한다 (원문이 "못 들어온다" 고 말했고 프로필로 대조 가능):

    deny:size@size:large   × 대형견        원문이 크기로 배제했다
    deny:age@age:senior    × 10살 이상     `DogProfile.age_years` 로 대조된다

판정하지 않는다 — 술어로 **보여주기만** 한다:

    require:carrier · require:hold   초대형 케이지가 있을 수도 있고 시설이 말하는
                                     "케이지" 의 규격을 우리는 모른다. 34kg 이면
                                     사실상 불가일 때가 많지만 그건 추론이다
    deny:behavior · deny:health      이 개가 공격적인지 아픈지 우리는 모른다
    deny:breed                       열거된 견종 이름을 술어가 안 담는다 (`breed:named`)
    require:vaccination · admin:*    보호자가 챙길 것이지 못 가는 이유가 아니다

`evaluate_dog_access` 가 `weight_boundary_unknown` 으로 경계값을 지어내지 않는 것과
같은 규율이다. 모르는 것을 불가로 바꾸면 갈 수 있는 곳이 조용히 사라진다.

`owner.can_carry_kg` 가 살아나면 `require:hold` 는 그때 판정 대상이 된다 — 재료가
생기기 전에 추론으로 메우지 않는다.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.place.contracts import RestrictionChip, RestrictionFacts
from app.profile.contract import SizeClass

# `applies_to` 중 프로필로 대조할 수 있는 것. 여기 없는 대상은 **거르지 않는다** —
# 판단 재료가 없으면 칩을 남기는 쪽이 안전하다(보호자가 읽고 판단한다).
_SIZE_SUBJECTS: dict[str, frozenset[SizeClass]] = {
    "size:large": frozenset({"large"}),
    "size:medium_up": frozenset({"medium", "large"}),
    "size:small": frozenset({"small"}),
}

# 이 술어들만 `incompatible` 로 승격한다. 모듈 docstring 의 근거를 지킨다.
_BLOCKING_CODES = frozenset({"deny:size", "deny:age"})

SENIOR_YEARS = 10.0  # 원문 어휘가 "10살 이상 노령견" 으로 반복된다

RestrictionState = Literal["compatible", "incompatible", "unknown"]
RestrictionReason = Literal[
    "size_denied",
    "age_denied",
    "no_blocking_condition",
    "missing_dog_size",
    "missing_dog_age",
    "restrictions_unknown",
]


class DogRestrictionEvaluation(BaseModel):
    """조건 술어를 이 개에 대고 본 결과. `dog_access` 와 다른 축이다.

    `dog_access` 는 `pet_size_class`·`max_kg`(원천 축)를 보고, 이쪽은 **문장에서
    파생한 술어**를 본다. 같은 시설이 두 축에서 다른 답을 낼 수 있고, 그건 원천이
    두 곳에 다르게 적었다는 사실이므로 합치지 않는다.
    """

    state: RestrictionState
    reason: RestrictionReason
    # **이 개에게 보여줄 칩.** `facts.restrictions.chips` 는 장소 사실이라 전부 들고 있고,
    # 이쪽은 그중 해당하는 것만이다 — 소형견 요청에서 `#입마개·대형견` 이 여기서 사라진다.
    chips: list[RestrictionChip] = Field(default_factory=list)
    # 판정 근거가 된 술어 코드. 왜 못 가는지 화면이 설명할 수 있어야 한다.
    blocking: list[str] = Field(default_factory=list)


def applies_to_dog(
    chip: RestrictionChip,
    *,
    dog_size: SizeClass | None,
    dog_age_years: float | None,
) -> bool:
    """이 칩을 **이 개에게 보여야 하는가.**

    모르면 `True` 다. 조건을 숨기는 실수가 보여주는 실수보다 나쁘다 — 보호자는
    본 것을 확인할 수 있지만 안 보인 것은 확인할 방법이 없다.
    """
    subject = chip.applies_to
    if subject == "all":
        return True
    if subject in _SIZE_SUBJECTS:
        if dog_size is None:
            return True
        return dog_size in _SIZE_SUBJECTS[subject]
    if subject == "age:senior":
        return dog_age_years is None or dog_age_years >= SENIOR_YEARS
    # sex · 중성화 · 생리 · 견종 · 어린 개: 프로필로 못 가른다. 남긴다.
    return True


def project(
    facts: RestrictionFacts | None,
    *,
    dog_size: SizeClass | None,
    dog_age_years: float | None,
) -> DogRestrictionEvaluation:
    """이 개 기준의 칩과 판정. **원본 `facts` 는 건드리지 않는다.**

    장소 사실(`facts.restrictions`)과 요청별 파생(`evaluations`)을 가르는 것은
    결정 #68 의 규율 그대로다 — 같은 시설도 데려가는 개에 따라 답이 달라진다.
    """
    if facts is None or facts.state == "unknown":
        return DogRestrictionEvaluation(
            state="unknown", reason="restrictions_unknown",
        )

    visible = [
        chip for chip in facts.chips
        if applies_to_dog(chip, dog_size=dog_size, dog_age_years=dog_age_years)
    ]

    for chip in visible:
        if chip.code not in _BLOCKING_CODES:
            continue
        if chip.code == "deny:size":
            if dog_size is None:
                return DogRestrictionEvaluation(
                    state="unknown", reason="missing_dog_size",
                    chips=visible, blocking=[chip.code],
                )
            return DogRestrictionEvaluation(
                state="incompatible", reason="size_denied",
                chips=visible, blocking=[chip.code],
            )
        if dog_age_years is None:
            return DogRestrictionEvaluation(
                state="unknown", reason="missing_dog_age",
                chips=visible, blocking=[chip.code],
            )
        return DogRestrictionEvaluation(
            state="incompatible", reason="age_denied",
            chips=visible, blocking=[chip.code],
        )

    return DogRestrictionEvaluation(
        state="compatible", reason="no_blocking_condition", chips=visible,
    )
