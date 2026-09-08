"""Bounded live A/B planning experiment. Never advances into scene writing."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from .contracts import SelectionPlan
from .provider import Provider
from .runner import initialize, load, step
from .selection_adapter import from_selection_case
from .selection_demo import ARCHIVE
from .storage import digest, read, save

MODEL = "gemini-3.1-flash-lite"
SETTINGS = {"temperature": 0.2, "maxOutputTokens": 8192}
ORDER = [
    ("movement", "individual"),
    ("movement", "grouped"),
    ("actions", "grouped"),
    ("actions", "individual"),
    ("gap", "individual"),
    ("gap", "grouped"),
]
COMMON_EXPERIMENT = """이번 실행은 구성안 비교다. 장면 본문은 쓰지 않는다.
자료가 지지하는 관측과 잠정 해석을 구분한다. 냄새 기록은 정지·휴식의 근거가 아니며,
사진 기록은 촬영 목적·사진 내용의 근거가 아니다. 장소 근접은 내부 진입·이용의 근거가 아니다.
같은 공간 유형의 재등장을 동일 장소로의 복귀로 쓰지 않는다. 감정·선호·익숙함을 단정하지 않는다.
선정/묶기/생략은 전체 산책에서 추가로 전달하는 내용과 반복을 고려한다. 원본 사건 시간은 보존한다.
"""


class PlanningProvider(Provider):
    def request(self, stage, payload, contract):
        if stage not in ("select", "compose"):
            raise ValueError("experiment permits planning only")
        request = super().request(stage, payload, contract)
        request["generationConfig"].update(SETTINGS)
        request["systemInstruction"]["parts"][0]["text"] += "\n" + COMMON_EXPERIMENT
        return request


def prepare(root, archive=ARCHIVE, model=MODEL, provider_type=PlanningProvider):
    cases = {c["id"]: c for c in read(archive)["cases"]}
    inputs, requests, comparisons = {}, {}, {}
    for name, mode in ORDER:
        run_id = f"{name}-{mode}"
        evidence = from_selection_case(
            cases[name],
            started_at=datetime.fromisoformat("2026-09-07T09:00:00+09:00"),
            session_id=f"archived-v3-{name}",
            composition_mode=mode,
        )
        source = evidence.model_dump(mode="json")
        common = evidence.model_dump(mode="json")
        common["context"]["candidate_catalog"].pop("composition_mode")
        if name in comparisons and comparisons[name] != digest(common):
            raise ValueError("paired source evidence differs")
        comparisons[name] = digest(common)
        stage = "select" if mode == "individual" else "compose"
        request = provider_type(root / run_id, model).request(
            stage,
            {"evidence_snapshot": source},
            SelectionPlan,
        )
        if len(str(request).encode("utf-8")) > 150_000:
            raise ValueError("request exceeds preflight byte bound")
        inputs[run_id], requests[run_id] = source, request
    manifest = {
        "version": getattr(provider_type, "EXPERIMENT_VERSION", "event-scene-planning-ab-v1"),
        "model": model,
        "settings": SETTINGS,
        "order": [f"{name}-{mode}" for name, mode in ORDER],
        "shared_evidence_sha256": comparisons,
        "requests": {key: digest(value) for key, value in requests.items()},
        "max_attempts": 6,
        "automatic_retries": 0,
        "max_request_bytes": 150_000,
        "observed_token_stop_threshold": 100_000,
        "budget_note": "Known usage checked before next request; not a hard total token cap. "
        "Unknown failed-call usage remains unknown.",
        "comparison_note": "Input differs only in composition mode. Instructions grant different "
        "editorial rights; common factual guidance and generation settings match.",
        **getattr(provider_type, "experiment_metadata", dict)(),
    }
    path = root / "experiment.json"
    if path.exists():
        if read(path) != manifest:
            raise ValueError("experiment inputs/settings/prompts/schema changed; use new output")
    elif root.exists() and any(root.iterdir()):
        raise ValueError("experiment requires an empty output directory")
    else:
        save(path, manifest)
    for run_id in manifest["order"]:
        run = root / run_id
        if not (run / "config.json").exists():
            initialize(run, inputs[run_id], model)
        _, evidence, _ = load(run)
        if evidence.model_dump(mode="json") != inputs[run_id]:
            raise ValueError("saved source differs from experiment")
        save(run / "planned_request.json", requests[run_id])
    return manifest


def summarize(root):
    manifest = read(root / "experiment.json")
    rows = []
    for run_id in manifest["order"]:
        run = root / run_id
        calls = sorted((run / "calls").glob("*/receipt.json"))
        attempts = list((run / "calls").glob("*"))
        receipt = read(calls[-1]) if calls else {}
        state = load(run)[2]
        result = read(run / "attempt_result.json") if (run / "attempt_result.json").exists() else {}
        response = calls[-1].parent / "response.json" if calls else None
        output = read(response) if response and response.exists() else None
        resolved = (
            read(run / "resolved_plan.json") if (run / "resolved_plan.json").exists() else None
        )
        proposed = output.get("outline", output.get("scenes")) if isinstance(output, dict) else None
        rows.append(
            {
                "id": run_id,
                "status": "accepted"
                if state is not None
                else result.get("status", "interrupted_unknown" if attempts else "prepared"),
                "error": result.get("error"),
                "attempts": len(attempts),
                "receipt": receipt,
                "output": output,
                "resolved_output": resolved,
                "scene_count": len(state.outline) if state else None,
                "proposed_scene_count": len(proposed) if isinstance(proposed, list) else None,
                "semantic_status": "not_evaluated" if output else "no_parsed_output",
            }
        )
    usage = [r["receipt"].get("usage") for r in rows if r["attempts"]]
    summary = {
        "rows": rows,
        "attempts": sum(r["attempts"] for r in rows),
        "accepted": sum(r["status"] == "accepted" for r in rows),
        "known_total_tokens": sum((u or {}).get("totalTokenCount", 0) for u in usage),
        "unknown_usage_attempts": sum(u is None for u in usage),
        "semantic_note": "Structural acceptance is not narrative quality or factual certification.",
    }
    save(root / "results.json", summary)
    lines = [
        "# 실제 모델의 사건별 / 묶음 구성 비교",
        "",
        "본문 작성 전 구성만 비교한다. 아래 문구는 모델 원문이며 구조 통과가 의미 승인은 아니다.",
        "거부된 출력은 진단용이다. 반환 시각과 구성은 정상 장면이나 지도 표시 데이터로 사용하지 않는다.",
        "",
        (
            f"요청 시도 {summary['attempts']} · 구조 통과 {summary['accepted']} · "
            f"확인된 토큰 {summary['known_total_tokens']} · 사용량 미상 {summary['unknown_usage_attempts']}"
        ),
        "",
        "| 실행 | 상태 | 원문 제안 수 | 승인된 장면 수 |",
        "| --- | --- | ---: | ---: |",
    ]
    lines += [
        f"| [{r['id']}]({r['id']}/planned_request.json) | {r['status']} | "
        f"{r['proposed_scene_count'] if r['proposed_scene_count'] is not None else '—'} | "
        f"{r['scene_count'] if r['scene_count'] is not None else '—'} |"
        for r in rows
    ]
    for row in rows:
        lines += ["", f"## {row['id']}", "", f"구조 상태: {row['status']}"]
        if row["error"]:
            lines += ["", row["error"]]
        output = row["resolved_output"] or row["output"]
        if not output:
            continue
        try:
            SelectionPlan.model_validate(output)
        except ValueError:
            lines += [
                "",
                "정상 내부 구성이 생성되지 않았다. 원문은 results.json과 해당 calls에 보존했다.",
            ]
            if isinstance(output, dict) and "scenes" in output:
                lines += [
                    "",
                    "### 모델의 미승인 제안 원문",
                    "",
                    "```json",
                    json.dumps(output, ensure_ascii=False, indent=2),
                    "```",
                ]
            continue
        lines += ["", "### 모델의 전체 이해", "", output["understanding"]["summary"]]
        title = output["selection"].get("title_draft")
        if title:
            lines += ["", "대표 제목 초안: " + title["text"]]
        groups = {g["scene_id"]: g for g in output["selection"].get("compositions", [])}
        for scene in output["outline"]:
            lines += [
                "",
                f"### {scene['scene_id']} · {scene['focus']}",
                "",
                (
                    "시스템이 복원한 대표 사건 시각: "
                    if row["resolved_output"]
                    else "모델 반환 시각(원문): "
                )
                + f"{scene['start_at']} → {scene['end_at']}",
            ]
            if scene["scene_id"] in groups:
                group = groups[scene["scene_id"]]
                lines += [
                    "",
                    f"중심: {group['primary_candidate_id']}",
                    "",
                    "포함: " + ", ".join(group["included_candidate_ids"]),
                    "",
                    "맥락: " + ", ".join(group["context_candidate_ids"]),
                    "",
                    group["reason"],
                ]
        lines += ["", "### 모델의 선택·맥락·생략 이유", ""]
        for decision in output["selection"]["decisions"]:
            lines += [
                (
                    f"- {decision['candidate_id']} ({decision['code']}, "
                    f"{decision['scene_id']}): {decision['reason']}"
                )
            ]
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def execute(root, archive=ARCHIVE, model=MODEL, env_file=None, provider_type=PlanningProvider):
    manifest = prepare(root, archive, model, provider_type)
    for run_id in manifest["order"]:
        run = root / run_id
        # An attempted or interrupted request is never automatically sent again.
        if list((run / "calls").glob("*")):
            continue
        summary = summarize(root)
        if (
            summary["attempts"] >= manifest["max_attempts"]
            or summary["known_total_tokens"] >= manifest["observed_token_stop_threshold"]
        ):
            break
        provider = provider_type(run, model, env_file=env_file)
        save(run / "attempt_result.json", {"status": "dispatching"})
        try:
            state = step(run, provider)
            result = {"status": "accepted", "revision": state.revision}
        except ValueError as exc:
            result = {"status": "rejected_or_failed", "error": str(exc)}
        save(run / "attempt_result.json", result)
        summary = summarize(root)
        print(
            f"{run_id}: {result['status']}; known tokens={summary['known_total_tokens']}",
            flush=True,
        )
    return summarize(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run", action="store_true", help="Make at most six planning requests")
    args = parser.parse_args()
    if args.run:
        execute(args.out, args.archive, args.model, args.env_file)
    else:
        prepare(args.out, args.archive, args.model)
        summarize(args.out)
        print("Prepared six planning requests; no API calls")


if __name__ == "__main__":
    main()
