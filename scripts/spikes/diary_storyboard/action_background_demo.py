"""Inspect rule-chosen action/background stamps without generating diary text."""

import argparse
import json
from pathlib import Path

from .how_demo import route, scenarios
from .how_stamp_demo import source_with_records
from .stamp_tool import StampTool


def run(out: Path, *, target_scene_count: int):
    if out.exists() and any(out.iterdir()):
        raise ValueError("use an empty output directory")
    walk = route("action-background-demo", [
        (0, 0, 0), (120, 120, 0), (180, 120, 0),
        (300, 240, 0), (340, 320, 0), (460, 440, 0),
    ])
    conditions = {
        "records_enough": source_with_records(walk, [
            (6, "note", "  산책 시작 후 남긴 메모\n"), (50, "photo", ""), (84, "note", "후반 메모")]),
        "one_record": source_with_records(walk, [(6, "note", "이때 남긴 메모")]),
        "no_record": source_with_records(walk),
        "record_at_dwell": source_with_records(walk, [(30, "note", "여기서 남긴 메모")]),
        "ordinary_turn": source_with_records(scenarios()["right"]["source"]),
        "gps_gap": source_with_records(scenarios()["gap"]["source"]),
    }
    report = {"schema_version": "action-background-demo-v1", "evidence_origin": "synthetic",
              "llm_calls": 0, "cases": {}}
    for name, source in conditions.items():
        tool = StampTool("action_background", source, {"target_scene_count": target_scene_count})
        book = tool.dump()
        if StampTool.load(book).query() != tool.query():
            raise ValueError("stamp replay differs")
        folder = out / name
        folder.mkdir(parents=True)
        for filename, value in (("stamp_book.json", book), ("prepared_stamps.json", tool.query())):
            (folder / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        report["cases"][name] = {
            **book["slot_audit"]["scene_counts"], "stamp_count": len(tool.refs),
            "supplement_kinds": [tool.project(r)["action"]["kind"] for r in tool.refs
                                 if tool.project(r)["action"]["origin"] == "derived_observation"],
            "replay_equal": True,
        }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    lines = ["# 행위 기록 우선 · 부족분 보충", "",
             f"합성 입력, 목표 {target_scene_count}개(실행 인자), LLM 호출 0회. 완성 일기가 아닌 조립 결과다.",
             "", "| 조건 | 사용자 기록 | 보충 | 남은 부족분 | 보충 관측 |",
             "| --- | ---: | ---: | ---: | --- |"]
    for name, row in report["cases"].items():
        lines.append(f"| {name} | {row['user_records']} | {row['supplemented']} | "
                     f"{row['remaining_deficit']} | {', '.join(row['supplement_kinds']) or '없음'} |")
    lines += ["", "각 폴더의 `prepared_stamps.json`에서 action과 background를 따로 확인한다.",
              "`stamp_book.json`에는 원본·후보 풀·선택/제외 이유·정책·버전이 보존된다.", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target-scene-count", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out, target_scene_count=args.target_scene_count), ensure_ascii=False))
