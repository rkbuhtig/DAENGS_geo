"""Recompute a saved dataset using observed exports and caches; no generator or LLM call."""

import argparse
from pathlib import Path

from .geo_adapter import QueryPolicy, build_evidence
from .storage import digest, read, save


def verify(dataset: Path, cache_dir: Path):
    receipt = read(dataset / "acquisition_receipt.json")
    recipe = read(dataset / "evaluation/recipe.json")
    assert digest(recipe) == receipt["recipe_sha256"]
    current = read(dataset / "observations/diary-current-01.json")
    history = [read(p) for p in sorted((dataset / "observations").glob("diary-history-*.json"))]
    pins = read(dataset / "pins.json")
    assert digest(current) == receipt["current_observation_sha256"]
    assert digest(history) == receipt["history_observation_sha256"]
    assert digest(pins) == receipt["pins_sha256"]
    snapshots = [read(cache_dir / entry["file"]) for entry in receipt["environment_snapshots"]]
    assert [digest(s) for s in snapshots] == [
        entry["snapshot_sha256"] for entry in receipt["environment_snapshots"]
    ]
    evidence, audit = build_evidence(
        current, history, pins, QueryPolicy.model_validate(recipe["query_policy"]), snapshots
    )
    assert evidence.model_dump(mode="json") == read(dataset / "evidence.json")
    assert audit == read(dataset / "calculation_audit.json")
    assert digest(evidence.model_dump(mode="json")) == receipt["evidence_sha256"]
    encoded = evidence.model_dump_json()
    for field in ('"seed"', '"holds"', '"fatigue"', '"latent_state"', '"truth_duration_s"'):
        assert field not in encoded
    result = {
        "observations_and_cache_fingerprints_verified": True,
        "recomputed_evidence_matches": True,
        "recomputed_audit_matches": True,
        "generator_truth_fields_absent": True,
        "history_count": len(history),
        "piece_count": len(evidence.pieces),
        "spatial_readings": len(audit["spatial_readings"]),
    }
    save(dataset / "verification.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.dataset, args.cache_dir)
    print(f"recomputed {result['piece_count']} pieces from saved observations and cached responses")


if __name__ == "__main__":
    main()
