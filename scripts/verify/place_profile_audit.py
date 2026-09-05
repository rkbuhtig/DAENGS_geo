# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic>=2.12,<3"]
# ///
"""Read-only profile evaluation probes against sibling DAENGS_dev/app checkouts.

Run with uv run scripts/verify/place_profile_audit.py. No API, auth or DB access.
Requires sibling DAENGS_dev and DAENGS_app checkouts only when executed.
Synthetic probes describe current behavior; they are not multi-dog acceptance tests.
"""

import json
import sys
from collections import Counter
from pathlib import Path


def main():
    workspace = Path(__file__).resolve().parents[3]
    backend_src = workspace / "DAENGS_dev/backend/src"
    fixture_path = workspace / "DAENGS_app/app/src/debug/assets/place_search_lab.json"
    if not (backend_src / "daengs_place").is_dir():
        raise SystemExit(
            f"Required sibling DAENGS_dev checkout is missing: {backend_src / 'daengs_place'}"
        )
    if not fixture_path.is_file():
        raise SystemExit(f"Required sibling DAENGS_app fixture is missing: {fixture_path}")

    sys.path.insert(0, str(backend_src))
    from daengs_place.place.contracts import PetAccessFacts, RestrictionChip, RestrictionFacts
    from daengs_place.place.evaluations import evaluate_dog_access
    from daengs_place.place.restriction_projection import project

    probes = {}
    for weight in (9, 10, 11):
        probes[f"weight_{weight}_max_10"] = evaluate_dog_access(
            PetAccessFacts(allowed=True, max_kg=10), None, weight
        ).model_dump()
    probes["weight_only_any_size"] = evaluate_dog_access(
        PetAccessFacts(allowed=True, size_class="any"), None, 9
    ).model_dump()
    limit = RestrictionFacts(
        state="restricted",
        parse_state="mapped",
        chips=[RestrictionChip(code="limit:max_dogs", label="count limit", params={"max": "2"})],
    )
    probes["count_limit"] = project(limit, dog_size="small", dog_age_years=2).model_dump()
    chips = [
        RestrictionChip(code="deny:size", label="large denied", applies_to="size:large"),
        RestrictionChip(code="deny:species_dog", label="dogs denied"),
    ]
    for name, ordered in (("unknown_first", chips), ("blocker_first", list(reversed(chips)))):
        probes[name] = project(
            RestrictionFacts(state="restricted", parse_state="mapped", chips=ordered),
            dog_size=None,
            dog_age_years=2,
        ).model_dump()

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    places = {}
    for name, response in fixture["cases"].items():
        if not name.endswith("-baseline"):
            continue
        for group in response["groups"]:
            for hit in group["results"]:
                place = hit["place"]
                key = place["key"]
                places[(key["source"], key["ref"])] = place
    facts = [place["facts"] for place in places.values()]
    counts = {
        "unique_baseline_places": len(places),
        "with_size_class": sum(bool((f.get("pet_access") or {}).get("size_class")) for f in facts),
        "with_max_kg": sum((f.get("pet_access") or {}).get("max_kg") is not None for f in facts),
        "restriction_states": dict(
            Counter((f.get("restrictions") or {}).get("state", "absent") for f in facts)
        ),
        "with_count_chip": sum(
            any(
                c["code"].startswith("limit:")
                for c in (f.get("restrictions") or {}).get("chips", [])
            )
            for f in facts
        ),
    }
    print(json.dumps({"probes": probes, "saved_fixture_coverage": counts}, indent=2))


if __name__ == "__main__":
    main()
