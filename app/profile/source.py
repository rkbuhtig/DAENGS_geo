"""프로필 원천. Fake = 가상 페르소나 3마리, HTTP = 팀 API (미구현)."""

from datetime import date
from typing import Protocol

from app.profile.contract import BreedMix, DogProfile


class ProfileSource(Protocol):
    async def get(self, dog_id: str) -> DogProfile | None: ...


PERSONAS: dict[str, DogProfile] = {
    "kong": DogProfile(
        dog_id="kong", name="콩이",
        breed=[BreedMix(breed="border collie", ratio=0.6), BreedMix(breed="mix", ratio=0.4)],
        birth_date=date(2024, 5, 1), sex="M", neutered=True, weight_kg=18, size_class="medium",
        activity_level="high", temperament=["curious", "reactive_to_dogs"], has_car=True,
    ),
    "dubu": DogProfile(
        dog_id="dubu", name="두부",
        breed=[BreedMix(breed="pug")],
        birth_date=date(2021, 3, 15), sex="F", neutered=True, weight_kg=9, size_class="small",
        brachycephalic=True, health_flags=["obesity"], activity_level="mid", has_car=False,
    ),
    "halmae": DogProfile(
        dog_id="halmae", name="할매",
        breed=[BreedMix(breed="maltese")],
        birth_date=date(2013, 7, 1), sex="F", neutered=False, weight_kg=3.2, size_class="small",
        health_flags=["senior", "joint"], activity_level="low", temperament=["timid"], has_car=False,
    ),
}


class FakeProfileSource:
    async def get(self, dog_id: str) -> DogProfile | None:
        return PERSONAS.get(dog_id)


def profile_source() -> ProfileSource:
    return FakeProfileSource()
