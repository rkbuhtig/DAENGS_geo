"""Saved synthetic background through prepare -> cache -> common stamp assembly.

This demonstrates the collector boundary with declared fixtures, not real API
responses or generated diary prose. Every source and response stays in the run.
"""

import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from .how_demo import route
from .how_stamp_demo import cases, source_with_records
from .record_envelopes import payload_hash
from .scene_background import BackgroundEnvelope
from .scene_pipeline import ScenePolicy, background_requests, prepare_scene_plan, source_from_how
from .stamp_tool import StampTool


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def synthetic_response(request, index, *, unavailable=False):
    """Explicit fictional lookup; not a retargeted real or historic response."""
    target, domain = request["target"], request["domain"]
    at = datetime.fromisoformat(target["event_at"])
    status = "unavailable" if unavailable else "known"
    if request["status"] == "not_requested":
        status = "not_requested"
    payload = ({"features": [{"id": f"synthetic-park-{index}", "name": f"합성 공원 {index}",
                              "distance_m": 40, "geometry_reference": "representative_point"}]}
               if domain == "space" else {"temperature_c": 21, "precipitation_mm": 0})
    return BackgroundEnvelope.model_validate({
        "id": f"synthetic-response-{index}", "target": target,
        "tags": ["space.park" if domain == "space" else "environment.weather"],
        "status": status, "reason": None if status == "known" else request["reason"] or "fixture_timeout",
        "provenance": {
            "provider": "synthetic-provider", "operation": domain, "synthetic": True,
            "retrieved_at": None if status == "not_requested" else at + timedelta(hours=1),
            "temporal_basis": "unknown" if status != "known" else
            "event_observation" if domain == "environment" else "lookup_snapshot",
            "valid_time": {"start_at": at, "end_at": at + timedelta(minutes=1)}
            if domain == "environment" and status == "known" else None,
            "policy_version": "scene-pipeline-synthetic-v1",
        },
        "payload_format": "synthetic-provider-response-v1",
        "payload": payload if status == "known" else None,
        "payload_sha256": payload_hash(payload) if status == "known" else None,
    }).model_dump(mode="json")


def run(out, *, target_scene_count):
    if out.exists() and any(out.iterdir()):
        raise ValueError("use an empty output directory")
    walk = route("scene-pipeline-demo", [
        (0, 0, 0), (120, 120, 0), (180, 120, 0),
        (300, 240, 0), (340, 320, 0), (460, 440, 0),
    ])
    mixed = source_from_how(source_with_records(walk, [(6, "note", "  오늘 남긴 메모\n원문 보존  ")]))
    missing = deepcopy(mixed)
    missing.update(route=None, attachments=[], route_status="unavailable", route_reason="fixture_missing_route")
    unlocated = deepcopy(missing)
    unlocated["records"]["records"][0].update(location=None, time_basis="session_fallback")
    conditions = {
        "mixed": mixed,
        "observations_only": source_from_how(source_with_records(walk)),
        "missing_route": missing,
        "unlocated_note": unlocated,
        "background_unavailable": deepcopy(mixed),
        "gap": source_from_how(cases()["gap"]["source"]),
    }
    policy = ScenePolicy(target_scene_count=target_scene_count)
    report = {"schema_version": "scene-pipeline-demo-v2", "evidence_origin": "synthetic",
              "external_calls": 0, "llm_calls": 0, "cases": {}}
    for name, source in conditions.items():
        folder = out / name
        folder.mkdir(parents=True)
        plan = prepare_scene_plan(source, policy)
        requests = background_requests(plan)
        bare = StampTool("action_background_v2", source, policy.model_dump(mode="json"))
        _save(folder / "source_before_background.json", source)
        _save(folder / "scene_plan.json", plan)
        _save(folder / "background_requests.json", requests)
        _save(folder / "background_snapshot.json", [
            synthetic_response(r, i, unavailable=name == "background_unavailable")
            for i, r in enumerate(requests)
        ])
        # Read persisted results through the exact input surface of a future collector.
        saved = json.loads((folder / "background_snapshot.json").read_text(encoding="utf-8"))
        source["background_envelopes"] = saved
        source["selected_background_ids"] = [e["id"] for e in saved]
        tool = StampTool("action_background_v2", source, policy.model_dump(mode="json"))
        _save(folder / "stamp_book.json", tool.dump())
        _save(folder / "prepared_stamps.json", tool.query())
        book = json.loads((folder / "stamp_book.json").read_text(encoding="utf-8"))
        if StampTool.load(book).query() != tool.query():
            raise ValueError("saved book replay differs")
        if any(bare.project(a)["action"] != tool.project(b)["action"]
               or bare.resolve(a)["core_ref"] != tool.resolve(b)["core_ref"]
               for a, b in zip(bare.refs, tool.refs, strict=True)):
            raise ValueError("background changed scene core/action")
        report["cases"][name] = {
            **plan["selection"]["scene_counts"], "scene_count": len(tool.refs),
            "motion_status": plan["motion"]["status"], "core_and_action_unchanged": True,
            "replay_equal": True,
            "direct_background": [{"origin": row["material"]["action"]["origin"],
                                   **row["material"]["background"]["current_query_status"]}
                                  for row in tool.query()],
        }
    _save(out / "report.json", report)
    lines = ["# 중심 생성과 공통 배경 조립", "",
             "선언된 합성 산책·배경 응답이다. 실제 API·LLM 호출은 0회이며 완성 일기 품질 실험이 아니다.",
             "", "| 조건 | 사용자 기록 | 관측 보충 | 남은 부족분 | 중심·행위 보존 | 저장 재생 |",
             "| --- | ---: | ---: | ---: | --- | --- |"]
    for name, row in report["cases"].items():
        lines.append(f"| {name} | {row['user_records']} | {row['supplemented']} | "
                     f"{row['remaining_deficit']} | 통과 | 통과 |")
    lines += ["", "각 조건에서 다음 흐름을 확인할 수 있다.", "",
              "1. `scene_plan.json`: 배경 조회 전의 중심·보충 선택·동선 연결.",
              "2. `background_requests.json`: 두 출처가 공유하는 조회 대상. 위치 없는 메모는 미조회.",
              "3. `background_snapshot.json`: 저장된 합성 조회 응답과 출처·시각·해시.",
              "4. `prepared_stamps.json`: 원래 행위에 공간·환경·동선 배경을 따로 붙인 결과.",
              "5. `stamp_book.json`: 입력과 정책까지 포함해 다시 읽을 수 있는 책.", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--target-scene-count", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out, target_scene_count=args.target_scene_count), ensure_ascii=False))
