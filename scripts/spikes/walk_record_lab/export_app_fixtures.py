"""Produce app-ready scenes from synthetic GPS and real, explicitly fetched/cached context."""
import argparse
import json
from copy import deepcopy
from pathlib import Path

from app.features.storyboard.scenes import StoryboardBundleV2
from scripts.spikes.storyboard_and_regions.sources import service_key
from scripts.spikes.walk_record_lab.context import ContextReader
from scripts.spikes.walk_record_lab.core import Experiment, prepare
from scripts.spikes.walk_record_lab.selection import select
from scripts.spikes.walk_record_lab.storyboard_contract import export_storyboard


def fixture_experiments():
    spec = {"session_id": "geo-storyboard-pinless", "dog_id": "synthetic-dog",
            "started_at": "2026-09-05T09:00:00Z", "origin": {"lat": 37.48928, "lng": 127.0545},
            "route": {"name": "synthetic-line", "points_xy": [[0, 0], [1000, 0]]},
            "motion": {"name": "steady", "base_speed_mps": 1},
            "sensor": {"kind": "perfect", "sample_interval_s": 5, "accuracy_m": 3}}
    for name in ("pinless", "clustered", "gap", "movement", "updated"):
        s = deepcopy(spec)
        s["session_id"] = "geo-storyboard-"+("clustered" if name == "updated" else name)
        taps = []
        if name in {"clustered", "updated"}:
            taps = [{"id": "sniff", "code": "sniffing", "at_s": 450},
                    {"id": "bark", "code": "barking", "at_s": 470},
                    {"id": "memo", "code": "note", "at_s": 480, "note": "잠깐 쉬었다. (합성 메모)"}]
        if name == "movement":
            s["motion"]["holds"] = [{"progress_m": 300, "duration_s": 40}]
        if name == "gap":
            s["faults"] = [{"kind": "dropout", "id": "gap", "start_s": 400, "end_s": 600}]
        if name == "updated":
            taps = [t for t in taps if t["id"] != "bark"]
            taps[-1]["note"] = "벤치에서 잠깐 쉬었다. (정정한 합성 메모)"
        yield name, Experiment(scenario=s, taps=taps, policy="common")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    key = service_key(args.env_file) if args.fetch else ""
    args.out.mkdir(parents=True, exist_ok=True)
    reports = []
    for name, exp in fixture_experiments():
        artifacts, entries = prepare(exp)
        selection = select(artifacts, entries, exp.selection, [])
        contexts, metrics = ContextReader(args.cache_dir, key).selected_contexts(selection, args.fetch)
        bundle = export_storyboard(artifacts, entries, selection, contexts)
        (args.out / f"{name}.json").write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        reports.append({"case": name, "scenes": len(bundle.scenes), "queries": metrics,
                        "source_revision": bundle.source_revision})
    (args.out / "schema.json").write_text(json.dumps(StoryboardBundleV2.model_json_schema(),
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False))


if __name__ == "__main__":
    main()
