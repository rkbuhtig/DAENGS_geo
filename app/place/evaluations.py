"""요청 조건과 Place 사실을 대조하는 결정론적 평가.

평가는 장소 자체의 사실이 아니다. 같은 시설도 데려가는 개에 따라 답이 달라지므로
`PlaceResult.facts`에 섞지 않고 검색 hit에 붙인다. None은 불가가 아니라 미상이다.
"""

from typing import Literal

from pydantic import BaseModel

from app.place.contracts import PetAccessFacts
from app.profile.contract import SizeClass

DogAccessState = Literal["compatible", "incompatible", "unknown"]
DogAccessReason = Literal[
    "size_allowed",
    "size_exceeded",
    "dog_disallowed",
    "missing_restriction",
]

_SIZE_ORDER = {"small": 0, "medium": 1, "large": 2, "any": 3}


class DogAccessEvaluation(BaseModel):
    state: DogAccessState
    reason: DogAccessReason


def evaluate_dog_access(
    pet_access: PetAccessFacts | None,
    dog_size: SizeClass,
) -> DogAccessEvaluation:
    """원천에서 파생한 입장 축만으로 이 크기의 개와 시설을 대조한다."""
    if pet_access is None:
        return DogAccessEvaluation(state="unknown", reason="missing_restriction")
    if pet_access.allowed is False or pet_access.dog_ok is False:
        return DogAccessEvaluation(state="incompatible", reason="dog_disallowed")

    facility_limit = pet_access.size_class
    if facility_limit not in _SIZE_ORDER:
        return DogAccessEvaluation(state="unknown", reason="missing_restriction")
    if _SIZE_ORDER[dog_size] <= _SIZE_ORDER[facility_limit]:
        return DogAccessEvaluation(state="compatible", reason="size_allowed")
    return DogAccessEvaluation(state="incompatible", reason="size_exceeded")
