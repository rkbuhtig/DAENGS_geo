"""Render saved writing pairs and separate reviewer notes; never calls a model."""

import argparse
import json
from pathlib import Path

from .how_writing_experiment import ARMS, CASES, context, report, verify
from .storage import read, save

LABELS = {"all_records": "사진·메모 세 개", "no_record": "움직임만", "gap": "GPS 공백"}


def build(root):
    verify(root)
    results = report(root)
    review_path = root / "review.json"
    review = read(review_path) if review_path.exists() else {"cases": {}}
    cases = {}
    for case in CASES:
        tool, refs, _, _ = context(root, case, "baseline")
        book = tool.dump()
        comparison = read(root / case / "writing_comparison.json")
        records = []
        for ref in refs:
            projected = tool.project(ref)
            records.append({"ref": ref.model_dump(mode="json"), "anchor": tool.anchor(ref),
                            "record": projected.get("record"), "how": projected.get("how", [])})
        cases[case] = {
            "label": LABELS[case], "stamps": records, "comparison": comparison,
            "runs": {arm: next(r for r in results["rows"] if r["case"] == case and
                               r["arm"] == arm) for arm in ARMS},
            "requests": {arm: read(root / case / arm / "planned_request.json") for arm in ARMS},
            "catalog": book["how_catalog"], "review": review.get("cases", {}).get(case, {}),
        }
    view = {"cases": cases, "results": results, "review": review}
    save(root / "view.json", view)
    template = Path(__file__).with_name("how_writing_results.html").read_text(encoding="utf-8")
    data = json.dumps(view, ensure_ascii=False).replace("<", "\\u003c")
    (root / "index.html").write_text(template.replace("__DATA__", data), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
