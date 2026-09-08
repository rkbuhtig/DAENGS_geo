"""Same synthetic walk, different records: inspect rule-assembled stamps, no LLM."""

import argparse
import json
from collections import Counter
from pathlib import Path

from app.features.walk.facts import compute_facts

from .how_demo import route, scenarios
from .how_stamps import HowStampSource, observation_ref
from .stamp_storyboard import selection_request
from .stamp_tool import StampTool


def source_with_records(walk, entries=()):
    """Entries are (source sequence, kind, original text); anchors use that exact fix."""
    records, attachments = [], []
    fixes = {f.client_seq: f for f in walk.fixes}
    for index, (seq, kind, text) in enumerate(entries):
        fix = fixes[seq]
        ref = {"store": "walk_photo" if kind == "photo" else "walk_entry",
               "id": f"synthetic-record-{index + 1}", "version": "1", "version_kind": "revision"}
        records.append({
            "ref": ref, "owner_id": "synthetic-owner", "session_id": walk.session_id,
            "session_pet_ids": [walk.dog_id], "event_at": fix.at.isoformat(),
            "time_basis": "photo_capture" if kind == "photo" else "recorded_at",
            "authored_at": fix.at.isoformat(),
            "location": {"point": {"lat": fix.lat, "lng": fix.lng},
                         "captured_at": fix.at.isoformat(), "accuracy_m": fix.accuracy_m,
                         "basis": "device_fix", "observation_ref": observation_ref(walk, fix)},
            "content": {"kind": "photo", "media_ref": "synthetic-photo"} if kind == "photo"
            else {"kind": "note", "text": text},
        })
        attachments.append({"record_ref": ref, "client_seq": seq})
    return HowStampSource.model_validate({
        "route": walk.model_dump(mode="json"),
        "records": {"schema_version": "walk-record-envelopes-v1", "synthetic": True,
                    "owner_id": "synthetic-owner", "records": records,
                    "envelopes": [], "selected_envelope_ids": []},
        "attachments": attachments,
    }).model_dump(mode="json")


def cases():
    walk = route("stamp-comparison", [(0, 0, 0), (90, 0, 90), (180, 90, 90),
                                       (240, 90, 90), (330, 180, 90), (410, 100, 90)], noise_m=1)
    conditions = {
        "photo_turn": ("회전 지점에 사진", [(18, "photo", "")],
                       "1분 30초 사진은 그 시각에 남고, 가까운 회전과 연결 동선이 맥락으로 붙는다."),
        "note_stay": ("체류 중 메모", [(42, "note", "여기서 잠깐 주변을 봤다.")],
                      "3분 30초 메모를 중심에 둔다. 체류 판정 구간은 메모의 지속시간이 아니다."),
        "note_return": ("되짚기 시작 근처 기록", [(67, "note", "이쯤에서 사진을 확인했다.")],
                        "5분 35초 기록에 방향 반전과 되짚기가 함께 붙는다. 돌아선 이유는 추론하지 않는다."),
        "no_record": ("사용자 기록 없음", [],
                      "같은 HOW 조각에서 움직임 중심 후보를 만든다. 직선마다 카드를 만들지 않는다."),
        "all_records": ("기록 세 개 함께", [(18, "photo", ""),
                        (42, "note", "여기서 잠깐 주변을 봤다."),
                        (67, "note", "이쯤에서 사진을 확인했다.")],
                        "기록은 모두 보존하고, 이미 기록에 붙은 움직임 후보는 별도 카드로 중복 생성하지 않는다."),
        "far_photo": ("검산: 회전보다 이른 사진", [(6, "photo", "")],
                      "30초 사진은 긴 회전 판정 구간 안에 있지만 회전 지점과 멀다. 직선 맥락만 연결한다."),
    }
    result = {name: {"label": label, "description": description,
                     "source": source_with_records(walk, entries)}
              for name, (label, entries, description) in conditions.items()}
    gap = scenarios()["gap"]["source"]
    result["gap"] = {"label": "검산: GPS 공백", "description":
                     "공백 앞뒤 기록은 각자 동선만 연결한다. 끊어진 모서리를 회전으로 만들지 않는다.",
                     "source": source_with_records(gap, [(18, "photo", ""),
                                                         (42, "note", "기록이 다시 잡혔다.")])}
    return result


def run(out, *, writing_comparison=False):
    if out.exists() and any(out.iterdir()):
        raise ValueError("use an empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    report, views = {}, {}
    for name, case in cases().items():
        source = HowStampSource.model_validate(case["source"])
        tool = StampTool("record_how", case["source"])
        book = tool.dump()
        replay = StampTool.load(book)
        if replay.query() != tool.query():
            raise ValueError("projection replay differs")
        rows = [{"ref": ref.model_dump(mode="json"), "frame": tool.resolve(ref),
                 "material": tool.project(ref), "anchor": tool.anchor(ref)} for ref in tool.refs]
        walk = source.route
        trail = compute_facts(walk.session_id, walk.dog_id, walk.started_at,
                              walk.ended_at, list(walk.fixes)).trail
        view = {"label": case["label"], "description": case["description"],
                "started_at": walk.started_at.isoformat(),
                "fixes": [{"seq": f.client_seq, "lat": f.lat, "lng": f.lng,
                           "at": f.at.isoformat()} for f in walk.fixes],
                "segments": [[s.a.client_seq, s.b.client_seq] for s in trail.segments],
                "stamps": rows, "catalog": book["how_catalog"], "audit": book["slot_audit"]}
        folder = out / name
        folder.mkdir()
        if writing_comparison:
            from .writing_projection import (
                comparison_display,
                prepare_comparison,
                verify_comparison,
            )

            # Fix all existing candidates for a material-only comparison. This
            # is not a model selection or a product rule to retain every card.
            comparison = prepare_comparison(tool, tool.refs)
            verify_comparison(replay, comparison)
            view["comparison"] = comparison
            view["writing_display"] = comparison_display(comparison)
            (folder / "writing_comparison.json").write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        request, contract = selection_request(tool)
        for filename, value in (("source.json", case["source"]), ("stamp_book.json", book),
                                ("view.json", view), ("selection_request.json", {
                                    "status": "not_sent", "input": request,
                                    "response_schema": contract.model_json_schema()})):
            (folder / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        counts = dict(Counter(m["kind"] for m in book["how_catalog"]["materials"]))
        report[name] = {"records": len(source.records.records), "how_counts": counts,
                        "stamps": len(rows), "required": sum(r["frame"]["required"] for r in rows),
                        "replay_equal": True, "llm_calls": 0}
        if writing_comparison:
            report[name]["writing"] = view["comparison"]["statistics"]
        views[name] = view
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    template_name = "writing_projection_preview.html" if writing_comparison else "how_stamp_preview.html"
    template = Path(__file__).with_name(template_name).read_text(encoding="utf-8")
    data = json.dumps(views, ensure_ascii=False).replace("<", "\\u003c")
    (out / "index.html").write_text(template.replace("__CASE_DATA__", data), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--writing-comparison", action="store_true",
                        help="Freeze every stamp and compare full/compact writing inputs; no LLM")
    args = parser.parse_args()
    run(args.out, writing_comparison=args.writing_comparison)


if __name__ == "__main__":
    main()
