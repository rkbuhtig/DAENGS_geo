"""Deterministic v2 observation fixtures. Synthetic; no network, cache or credentials."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.features.storyboard.scenes import build_storyboard
from app.features.storyboard.selection import SelectionPolicy, select_nodes


def bundles():
    start = datetime(2026, 9, 6, tzinfo=UTC)

    def make(length, entries):
        nodes = [{"route_m": m, "block": 0, "elapsed_s": m,
                  "location": {"lat": 37.5, "lng": 127 + m / 88000},
                  "speed": 1.0, "duration_s": 10, "start_s": max(0, m - 10)}
                 for m in range(0, length + 1, 10)]
        selection = select_nodes(nodes, entries, SelectionPolicy(), [], session_id="v2-review",
                                 pet_id=None, started_at=start)
        contexts = {a["id"]: {"facts": [], "sources": [{"source": "fixture", "status": "unavailable",
                    "captured_at": None, "source_url": None}]} for a in selection["anchors"]}
        return build_storyboard("v2-review", start, start + timedelta(seconds=length), length,
                                entries, selection, contexts, synthetic=True)

    def action(i, at, pet="pet-a", revision=1):
        return {"id": f"record-{i}", "revision": revision, "pet_id": pet,
                "accepted": True, "kind": "behavior", "behavior_code": "sniffing",
                "label": "킁킁", "note": "", "elapsed_s": at, "accepted_distance_m": at,
                "location": {"lat": 37.5, "lng": 127 + at / 88000}, "route_known": True}

    return {
        "v2-before": make(600, [action(1, 40)]),
        "v2-after": make(600, [action(1, 40, "pet-b", 2)]),
        "v2-short": make(60, []),
        "v2-budget": make(3000, [action(i, i * 150) for i in range(9)]),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, bundle in bundles().items():
        (args.out / f"{name}.json").write_text(
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
