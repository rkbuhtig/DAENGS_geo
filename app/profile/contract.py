"""반려견 프로필 — 외부 계약. docs/contracts/dog-profile.md

이 레포는 프로필을 소유하지 않는다. 이 형태로 받는다고 가정하고 소비만 한다.
"""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

SizeClass = Literal["small", "medium", "large"]
Activity = Literal["low", "mid", "high"]

BRACHY_BREEDS = {"pug", "bulldog", "french bulldog", "boston terrier", "shih tzu", "pekingese", "boxer"}


class BreedMix(BaseModel):
    breed: str
    ratio: float = 1.0


class DogProfile(BaseModel):
    dog_id: str
    name: str
    breed: list[BreedMix]
    birth_date: date
    sex: Literal["M", "F"]
    neutered: bool
    weight_kg: float
    size_class: SizeClass
    profile_version: int = 1

    brachycephalic: bool | None = None
    health_flags: list[str] = Field(default_factory=list)  # joint, heart, obesity, senior ...
    activity_level: Activity | None = None
    temperament: list[str] = Field(default_factory=list)
    has_car: bool | None = None

    @computed_field  # type: ignore[misc]
    @property
    def age_years(self) -> float:
        today = datetime.now(UTC).date()
        return round((today - self.birth_date).days / 365.25, 1)

    @computed_field  # type: ignore[misc]
    @property
    def is_brachy(self) -> bool:
        if self.brachycephalic is not None:
            return self.brachycephalic
        return any(b.breed.lower() in BRACHY_BREEDS for b in self.breed)

    @computed_field  # type: ignore[misc]
    @property
    def is_senior(self) -> bool:
        return "senior" in self.health_flags or self.age_years >= 10

    @computed_field  # type: ignore[misc]
    @property
    def has_joint_issue(self) -> bool:
        return "joint" in self.health_flags
