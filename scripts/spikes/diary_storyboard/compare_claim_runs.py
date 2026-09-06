"""Verify paired artifacts and count actual transport costs; does not score narrative quality."""

import argparse
import json
from collections import Counter
from pathlib import Path

from .claim_experiment import AUDIT, REPAIR, ClaimAudit, inventory, validate_audit
from .contracts import State
from .prompts import COMMON, STAGES
from .runner import load
from .storage import digest, read, save
from .verify_run import verify


def compare(root):
    manifest = read(root / "experiment.json")
    assert manifest["prompts"] == {
        "common": COMMON,
        "stages": STAGES,
        "audit": AUDIT,
        "repair": REPAIR,
    }
    normalized = read(root / "normalized_evidence.json")
    assert digest(normalized) == manifest["normalized_sha256"]
    rows = []
    for pair in (1, 2, 3):
        normal = root / f"pair-{pair:02d}-normalized"
        audited = root / f"pair-{pair:02d}-audited"
        paths = sorted((normal / "states").glob("*.json"))
        draft = State.model_validate(read(paths[-2]))
        audit_input = read(audited / "audit_input.json")
        assert audit_input == {
            "evidence_snapshot": normalized,
            "board_before": draft.model_dump(mode="json"),
            "inventory": inventory(draft),
        }
        audit = ClaimAudit.model_validate(read(audited / "claim_audit.json"))
        validate_audit(audit, inventory(draft), load(normal)[1])
        for branch, path in (("normalized", normal), ("audited", audited)):
            verify(path)
            config, evidence, final = load(path)
            assert config["model"] == manifest["model"]
            assert evidence.model_dump(mode="json") == normalized
            assert final.status == "awaiting_review" and final.review is None
            assert not (path / "decisions").exists()
            saved = sorted((path / "states").glob("*.json"))
            assert len(saved) == len(paths)
            assert all(read(a) == read(b) for a, b in zip(paths[:-1], saved[:-1], strict=True))
            receipts, audit_matches, repair_matches = [], 0, 0
            for receipt_path in sorted((path / "calls").glob("*/receipt.json")):
                receipt = read(receipt_path)
                request = read(receipt_path.parent / "request.json")
                stage = receipt["stage"]
                instruction = STAGES.get(stage)
                if branch == "audited" and stage in ("claim_audit", "reconcile"):
                    instruction = AUDIT if stage == "claim_audit" else REPAIR
                assert (
                    request["systemInstruction"]["parts"][0]["text"] == COMMON + "\n" + instruction
                )
                payload = json.loads(request["contents"][0]["parts"][0]["text"])
                if stage == "claim_audit":
                    assert payload == audit_input
                    response = receipt_path.parent / "response.json"
                    if response.exists() and receipt.get("validation") == "accepted":
                        audit_matches += read(response) == audit.model_dump(mode="json")
                if branch == "audited" and stage == "reconcile":
                    assert payload["claim_audit"] == audit.model_dump(mode="json")
                    assert payload["board_before"] == draft.model_dump(mode="json")
                    repair_matches += receipt.get("validation") == "accepted"
                receipts.append(receipt)
            if branch == "audited":
                assert audit_matches and repair_matches
                assert all(
                    r["transport"] == "replay"
                    for r in receipts
                    if r["stage"] in ("understand", "scene")
                )
            live = [r for r in receipts if r["transport"] == "gemini"]
            old = {s.scene_id: s for s in draft.scenes}
            rows.append(
                {
                    "pair": pair,
                    "condition": branch,
                    "scene_count": len(final.scenes),
                    "live_attempts": len(live),
                    "failed_attempts": sum(r["status"] == "failed" for r in live),
                    "failure_http_statuses": dict(
                        Counter(str(r.get("http_status")) for r in live if r["status"] == "failed")
                    ),
                    "live_tokens": sum(
                        (r.get("usage") or {}).get("totalTokenCount", 0) for r in live
                    ),
                    "live_api_latency_s": round(sum(r["latency_s"] for r in live), 3),
                    "replayed_calls": sum(r["transport"] == "replay" for r in receipts),
                    "changed_scene_ids": [s.scene_id for s in final.scenes if s != old[s.scene_id]],
                    "audit_entries": len(audit.items) if branch == "audited" else 0,
                    "audit_actions": dict(Counter(i.action for i in audit.items))
                    if branch == "audited"
                    else {},
                }
            )
    result = {
        "paired_inputs_drafts_prompts_audits_verified": True,
        "rows": rows,
        "actual_attempts": sum(r["live_attempts"] for r in rows),
        "actual_failed_attempts": sum(r["failed_attempts"] for r in rows),
        "actual_reported_tokens": sum(r["live_tokens"] for r in rows),
        "actual_api_latency_sum_s": round(sum(r["live_api_latency_s"] for r in rows), 3),
    }
    save(root / "comparison.json", result)
    lines = [
        "# 동일 초안의 재검토 조건 비교",
        "",
        "자동 집계는 호출·변경 여부를 확인하며 문장의 의미 정확성을 판정하지 않는다.",
        "",
        "| 회차 | 조건 | 장면 | 실제 호출(실패) | 보고 토큰 | 추가 대조 항목 | 수정 장면 |",
        "|---|---|---:|---:|---:|---:|---|",
        *[
            f"| {r['pair']} | {r['condition']} | {r['scene_count']} | {r['live_attempts']}({r['failed_attempts']}) | {r['live_tokens']} | {r['audit_entries']} | {r['changed_scene_ids']} |"
            for r in rows
        ],
        "",
        "정규화 조건이 초안 작성 비용을 부담하고, 대조 조건은 같은 초안을 무료 재생한다.",
        "조건 전체 비용을 비교할 때는 대조 조건에도 같은 초안 작성 비용이 필요하다.",
    ]
    (root / "COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.root), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
