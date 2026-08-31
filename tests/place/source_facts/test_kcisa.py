import json
from pathlib import Path

from app.place.source_facts.kcisa import project_kcisa

FIXTURE = Path(__file__).parent / "fixtures" / "kcisa.json"


def _cases() -> dict[str, dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {item["id"]: item["row"] for item in payload["cases"]}


def test_purpose_and_zone_hints_preserve_source_meaning():
    projection = project_kcisa(_cases()["outdoor-only-museum"])

    assert projection.purpose.primary == "museum"
    assert [node.label for node in projection.purpose.taxonomy_path] == [
        "반려동물업",
        "반려동반여행",
        "박물관",
    ]
    assert projection.pet_access.source_indoor is False
    assert projection.pet_access.source_outdoor is True
    assert projection.pet_access.zone_hints == ("outdoor",)
    assert "zone:outdoor_only" in {item.code for item in projection.restrictions.predicates}


def test_explicit_zone_sentence_wins_by_exposing_a_conflict():
    projection = project_kcisa(_cases()["zone-conflict"])

    assert projection.pet_access.zone_hints == ("indoor", "outdoor")
    assert "zone:outdoor_only" in {item.code for item in projection.restrictions.predicates}
    assert "zone_flag_conflict" in {issue.code for issue in projection.issues}
    assert projection.state.value == "partial"


def test_denied_record_is_projectable_even_though_current_ingest_excludes_it():
    projection = project_kcisa(_cases()["explicit-denied"])

    assert projection.pet_access.allowed is False
    assert projection.pet_access.zone_hints == ()
    assert projection.restrictions.state == "not_applicable"
    assert projection.evidence["pet_access.allowed"].state.value == "known"


def test_size_condition_and_fee_are_separate_facts():
    projection = project_kcisa(_cases()["size-and-fee"])
    predicates = {item.code: item for item in projection.restrictions.predicates}

    assert predicates["deny:size"].applies_to == "size:medium_up"
    assert predicates["deny:size"].params == {"max_kg": "10.0"}
    assert predicates["require:vaccination"].applies_to == "all"
    assert projection.pet_access.exclusive is True
    assert projection.pet_fee.amount_krw == 10_000


def test_species_denial_is_not_lost_inside_size_text():
    projection = project_kcisa(_cases()["dog-denied-by-species"])
    codes = [item.code for item in projection.restrictions.predicates]

    assert codes.count("deny:species_dog") == 1
