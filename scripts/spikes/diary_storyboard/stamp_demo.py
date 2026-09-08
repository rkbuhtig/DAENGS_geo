"""Offline record-to-stamp preparation and replay of three preserved model outputs."""

import argparse
import json
from pathlib import Path

from .stamp_storyboard import (
    SELECT_PROMPT,
    WRITE_PROMPT,
    accept_selection,
    accept_writing,
    render,
    selection_request,
    writing_request,
)
from .stamp_tool import StampTool

REPO = Path(__file__).resolve().parents[3]
ARCHIVE = REPO / "docs/research/2026-09-08-slot-stamp-gemini"
RECORDS = Path(__file__).with_name("fixtures") / "record_envelopes.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def prepare(records=RECORDS, archive=ARCHIVE):
    files = {}
    tool = StampTool("record_envelopes", read(records))
    files["records/stamp_book.json"] = tool.dump()
    payload, contract = selection_request(tool)
    files["records/select_request.json"] = {
        "prompt": SELECT_PROMPT, "payload": payload, "schema": contract.model_json_schema(),
        "source_version": tool.source_version,
        "call_needed": bool(payload["optional"]) and payload["remaining_cards"] > 0,
    }
    # All original records are required under record-stamp-v1; no selection call.
    refs = accept_selection(tool, {"optional_stamp_ids": []})
    if refs:
        payload, contract = writing_request(tool, refs)
        files["records/write_request.json"] = {
            "prompt": WRITE_PROMPT, "payload": payload, "schema": contract.model_json_schema(),
            "source_version": tool.source_version,
            "stamp_refs": [r.model_dump(mode="json") for r in refs],
        }
    report = {"new_model_calls": 0, "record_stamps": len(refs), "archive_replays": {}}
    for name in ("movement", "actions", "gap"):
        source = read(archive / name / "source.json")
        tool = StampTool("archived_v1", source)
        refs = accept_selection(tool, read(archive / name / "select/calls/000001/response.json"))
        raw = read(archive / name / "write/calls/000001/response.json")
        board = accept_writing(tool, refs, raw)
        view = render(tool, board)
        baseline = read(archive / name / "write/accepted.json")
        expected = [{"id": c["stamp_id"], "title": c["title"], "text": c["text"],
                     "anchor": {**c["anchor"], "chain": c["chain"], "location": None}}
                    for c in baseline["cards"]]
        actual = [{"id": c["stamp_ref"]["id"], "title": c["title"], "text": c["text"],
                   "anchor": c["anchor"]} for c in view["cards"]]
        if actual != expected or board.title != baseline["title"]:
            raise ValueError(f"{name}: historical text or anchor changed")
        files[f"{name}/stamp_book.json"] = tool.dump()
        files[f"{name}/storyboard.json"] = board.model_dump(mode="json")
        files[f"{name}/rendered.json"] = view
        report["archive_replays"][name] = {
            "cards": len(board.cards), "text_and_anchor_preserved": True,
            "semantic_status": board.semantic_status,
        }
    files["report.json"] = report
    return files


def run(out, records=RECORDS, archive=ARCHIVE):
    files = prepare(records, archive)
    if out.exists() and any(out.iterdir()):
        raise ValueError("use an empty output directory; existing results are immutable")
    for relative, value in files.items():
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 스탬프 툴 분리 · 오프라인 결과", "",
        "새 모델 호출 0회. 합성 기록으로 새 입력을 만들고, 보존한 모델 응답을 재생했다.", "",
        (f"원본 기록 {files['report.json']['record_stamps']}개 → 버전이 고정된 스탬프. "
         "records/write_request.json에서 모델에 전달할 딕셔너리를 확인할 수 있다."), "",
        "카드에는 stamp_ref·title·text만 저장한다. 시간·위치는 표시 시 스탬프에서 읽는다.", "",
        "아래 문구는 이전 실제 Gemini 출력 그대로다. 의미 과장이 해결됐다는 결과가 아니다.",
    ]
    for name in ("movement", "actions", "gap"):
        view = files[f"{name}/rendered.json"]
        lines += ["", f"## {name} · {view['title']}", ""]
        for card in view["cards"]:
            lines += [(f"- **{card['title']}** — {card['text']} "
                       f"(원본 구간 {card['anchor']['support_s']}, chain {card['anchor']['chain']})")]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return files["report.json"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--records", type=Path, default=RECORDS)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    print(json.dumps(run(args.out, args.records, args.archive), ensure_ascii=False))


if __name__ == "__main__":
    main()
