"""요청별 평가는 Place 사실을 지우거나 부풀리지 않고 3상태로만 말한다."""

import pytest

from app.place.contracts import PetAccessFacts
from app.place.evaluations import evaluate_dog_access


@pytest.mark.parametrize("pet_access", [None, PetAccessFacts(), PetAccessFacts(allowed=True)])
def test_missing_restriction_is_unknown(pet_access):
    evaluation = evaluate_dog_access(pet_access, "large")
    assert (evaluation.state, evaluation.reason) == ("unknown", "missing_restriction")


@pytest.mark.parametrize(
    "pet_access",
    [PetAccessFacts(allowed=False, size_class="any"), PetAccessFacts(dog_ok=False)],
)
def test_an_explicit_dog_exclusion_wins_over_other_axes(pet_access):
    evaluation = evaluate_dog_access(pet_access, "small")
    assert (evaluation.state, evaluation.reason) == ("incompatible", "dog_disallowed")


@pytest.mark.parametrize("facility_limit", ["large", "any"])
def test_a_large_dog_is_compatible_with_large_or_unrestricted_places(facility_limit):
    evaluation = evaluate_dog_access(
        PetAccessFacts(allowed=True, size_class=facility_limit), "large",
    )
    assert (evaluation.state, evaluation.reason) == ("compatible", "size_allowed")


def test_a_large_dog_exceeds_a_small_only_place():
    evaluation = evaluate_dog_access(
        PetAccessFacts(allowed=True, size_class="small"), "large",
    )
    assert (evaluation.state, evaluation.reason) == ("incompatible", "size_exceeded")
