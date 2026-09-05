"""Save reproducible synthetic cases and result receipts, using optional live public data."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from scripts.spikes.storyboard_and_regions.sources import service_key
from scripts.spikes.walk_record_lab.context import ContextReader
from scripts.spikes.walk_record_lab.core import Experiment, prepare, summarize
from scripts.spikes.walk_record_lab.selection import select


def cases():
    root = Path(__file__).resolve().parents[3]
    base = json.loads((root / "scripts/sim/walk/examples/sniff-and-go.json").read_text())
    base.update(origin={"lat": 37.48928, "lng": 127.0545},
                sensor={"kind": "perfect", "sample_interval_s": 5, "accuracy_m": 3},
                faults=[], delivery={})
    taps = [{"id": "sniff-1", "at_s": 60, "code": "sniffing"},
            {"id": "toilet-1", "at_s": 100, "code": "excretion"},
            {"id": "bark-1", "at_s": 170, "code": "barking"},
            {"id": "memo-1", "at_s": 180, "code": "note", "note": "잠깐 쉬었다. (합성)"}]
    for name in ("normal", "gap", "delay", "pinless", "memo-only", "deleted", "repeat",
                 "profile-change"):
        spec, entries = deepcopy(base), deepcopy(taps)
        spec["session_id"] = "record-lab-"+name
        if name == "gap":
            spec["faults"] = [{"kind": "dropout", "id": "gap", "start_s": 40, "end_s": 80},
                              {"kind": "accuracy", "id": "bad", "start_s": 160,
                               "end_s": 180, "accuracy_m": 85}]
        if name == "delay":
            spec["delivery"] = {"batch_size": 3, "reverse_within_batch": True,
                                "duplicate_at_s": [20], "base_latency_s": 1,
                                "delay_windows": [{"id": "late", "start_s": 30,
                                                   "end_s": 80, "delay_s": 45}]}
        if name == "pinless":
            entries = []
        if name == "memo-only":
            entries = entries[-1:]
        if name == "deleted":
            entries = entries[1:]
        if name == "repeat":
            spec["started_at"] = "2026-09-04T18:30:00+09:00"
        references = []
        if name == "profile-change":
            entries = []
            references = [{"walk_id": f"past-{i}", "pet_id": spec["dog_id"],
                           "started_at": f"2026-09-0{i}T18:00:00+09:00",
                           "median_speed_mps": 3} for i in (1, 2, 3)]
            spec["started_at"] = "2026-09-05T18:00:00+09:00"
        for minimum in (3, 4):
            yield name+f"-min{minimum}", Experiment(
                scenario=spec, taps=entries, policy="common", selection={"minimum": minimum},
                reference_walks=references)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    key = service_key(args.env_file) if args.fetch else ""
    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    for name, experiment in cases():
        artifacts, entries = prepare(experiment)
        selection = select(artifacts, entries, experiment.selection, experiment.reference_walks)
        contexts, metrics = ContextReader(args.cache_dir, key).selected_contexts(selection, args.fetch)
        result = summarize(experiment, artifacts, entries, contexts, selection)
        result["queries"] = metrics
        bundle = {"format": "walk-record-lab-bundle-v1",
                  "experiment": experiment.model_dump(mode="json"), "result": result}
        (args.out / f"{name}.json").write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        report.append({"case": name, "accepted": sum(e["accepted"] for e in entries),
                       "rejected": sum(not e["accepted"] for e in entries),
                       "scenes": len(result["scenes"]),
                       "context_rows": sum(bool(c["facts"]) for c in contexts.values()),
                       "selected_anchors": len(selection["anchors"]),
                       "minimum_met": selection["minimum_met"],
                       "longest_unread_m": selection["longest_unread_m"],
                       "selection_reasons": [a["reasons"] for a in selection["anchors"]],
                       "queries": metrics, "result_revision": result["result_revision"]})
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
