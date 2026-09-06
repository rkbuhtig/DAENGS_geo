"""Paired normalization / claim-audit experiment; stops before human review and diary."""

import argparse
import time
from pathlib import Path
from typing import Literal

from .contracts import Contract, Evidence, check_references
from .prompts import COMMON, STAGES
from .provider import Provider
from .runner import initialize, load, step
from .storage import digest, read, save
from .verify_run import verify

AUDIT = """현재 단계는 완성된 장면 초안의 주장과 원자료 사이 근거 관계를 대조하는 단계다.
inventory의 모든 항목을 정확히 한 번씩 검토한다. 한 항목에 여러 주장이 있으면 supported_content와
additional_assumptions에서 각각 구별한다. 관찰 목록뿐 아니라 본문·제목·전체 이해·질문에
포함된 전제도 확인한다. 주장 내용은 원자료가 직접 확인하는 내용, 근거 있는 잠정 해석,
뒷받침이 부족한 주장, 원자료와 모순되는 주장으로 구별한다. 단순한 제목이나 사실 전제가
없는 질문은 not_assertion으로 표시할 수 있다. 인용 ID가 존재한다는 것만으로 지지되는 것은 아니다.
이전 모델 문구는 새 관측 근거가 아니다. 수치의 정의·공간 범위·시간·표본 조건을 확인한다.
함께 읽을 때 유효한 사건 연결과 잠정 해석은 유지한다. 모든 해석을 없애는 작업이 아니다.
원자료가 지지하는 내용, 추가 가정, 필요한 처리와 이유, 같은 주장이 영향을 준 다른 inventory
항목 ID를 기록한다. evidence_ids는 실제 대조한 원자료를 가리킨다. 이 단계에서 장면을 고쳐 쓰거나
일기를 만들지 않는다. 감사 결과도 모델의 판단이며 확정된 정답이 아니다."""

REPAIR = (
    STAGES["reconcile"]
    + """
claim_audit에는 별도 호출에서 원자료와 대조한 결과가 있다. 이것을 원자료와 함께 확인한 뒤
필요한 수정을 실행한다. 감사 결과를 무조건 따르지 말고 잘못된 지적은 근거와 함께 거절할 수 있다.
해석에서 관찰로 변질된 주장은 본문·제목·관찰 목록·전체 이해·후속 장면·질문의 전제까지
일관되게 수정한다. 원자료가 지지하는 사건 연결과 관련된 공간 경향은 유지한다.
change_reason에 주요 처리 결과와 이유를 적는다. 수정 필요성을 지적하는 것만으로 끝내지 않는다.
"""
)


class AuditItem(Contract):
    target_id: str
    judgment: Literal["supported", "plausible", "unsupported", "contradicted", "not_assertion"]
    supported_content: str
    additional_assumptions: str
    evidence_ids: list[str]
    action: Literal["keep", "rephrase", "remove", "ask"]
    reason: str
    affected_target_ids: list[str]


class ClaimAudit(Contract):
    items: list[AuditItem]


def normalize(source):
    evidence = Evidence.model_validate(source).model_copy(deep=True)
    for piece in evidence.pieces:
        if piece.kind == "behavior_pin" and piece.value.get("type") == "sniffing":
            piece.value["normalized_observation"] = "냄새 맡기"
            piece.meaning = (
                "보호자가 기록한 관찰 행동은 냄새 맡기다. memo는 보호자의 원문 메모다. "
                "탐색은 이 행동보다 넓은 해석이며 관찰 행동의 동의어로 확정하지 않는다."
            )
            piece.provenance["normalization"] = {
                "version": "diary-behavior-label-experiment-v1",
                "source_piece_sha256": digest(
                    next(p for p in source["pieces"] if p["id"] == piece.id)
                ),
            }
    return evidence.model_dump(mode="json")


def inventory(state):
    """Enumerate every authored text field; paragraph entries can contain several claims."""
    items = []

    def visit(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key not in ("scene_id", "evidence_ids"):
                    visit(child, f"{path}/{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f"{path}/{i}")
        elif isinstance(value, str) and value.strip():
            items.append({"target_id": path, "text": value})

    visit(state.understanding.model_dump(mode="json"), "/understanding")
    for scene in state.scenes:
        visit(scene.model_dump(mode="json"), f"/scenes/{scene.scene_id}")
    return items


def validate_audit(audit, entries, evidence):
    check_references(audit, evidence)
    known = {item["target_id"] for item in entries}
    ids = [item.target_id for item in audit.items]
    if len(ids) != len(set(ids)) or set(ids) != known:
        raise ValueError("audit must cover each inventory entry exactly once")
    if any(not set(item.affected_target_ids) <= known for item in audit.items):
        raise ValueError("audit references an unknown affected target")


class AuditProvider(Provider):
    def instruction(self, stage):
        return COMMON + "\n" + (AUDIT if stage == "claim_audit" else REPAIR)

    def call(self, stage, payload, contract):
        if stage == "reconcile":
            payload = {**payload, "claim_audit": read(self.run / "claim_audit.json")}
        return super().call(stage, payload, contract)


def retry(operation, attempts=3):
    # Finite experiment attempt budget; every failed request stays on disk.
    for index in range(attempts):
        try:
            return operation()
        except ValueError as exc:
            print(f"attempt {index + 1}/{attempts}: {str(exc)[:180]}", flush=True)
            if index + 1 == attempts:
                raise
            if "HTTP 429" in str(exc) or "HTTP 503" in str(exc):
                print("transient API limit: waiting 30s before retry", flush=True)
                time.sleep(30)


def paired_run(source, root, pair, env_file, model):
    root.mkdir(parents=True, exist_ok=True)
    experiment = {
        "version": "diary-claim-comparison-v1",
        "model": model,
        "source_sha256": digest(source),
        "normalized_sha256": digest(normalize(source)),
        "normalization_version": "diary-behavior-label-experiment-v1",
        "prompts": {"common": COMMON, "stages": STAGES, "audit": AUDIT, "repair": REPAIR},
        "design": "3 paired drafts; normalized standard reconciliation vs audit then repair",
        "attempts_per_stage": 3,
    }
    manifest = root / "experiment.json"
    if manifest.exists():
        if read(manifest) != experiment:
            raise ValueError("experiment inputs or instructions changed; use a new root")
    else:
        save(manifest, experiment)
        save(root / "normalized_evidence.json", normalize(source))
    baseline = root / f"pair-{pair:02d}-normalized"
    audited = root / f"pair-{pair:02d}-audited"
    if not (baseline / "config.json").exists():
        initialize(baseline, normalize(source), model)
    provider = Provider(baseline, model, env_file)
    while True:
        state = retry(lambda: step(baseline, provider))
        if state.status == "reviewed":
            raise ValueError("paired experiment requires an unreviewed run")
        if state.status == "awaiting_review":
            break
    verify(baseline)
    if not (audited / "config.json").exists():
        initialize(audited, normalize(source), model)
    # Replay only the shared drafting stages: no duplicated live calls or resampled draft.
    replay = Provider(audited, model, replay_from=baseline)
    state = load(audited)[2]
    while state is None or state.status == "filling":
        state = step(audited, replay)
    if state.status == "reconciling":
        _, evidence, state = load(audited)
        entries = inventory(state)
        payload = {
            "evidence_snapshot": evidence.model_dump(mode="json"),
            "board_before": state.model_dump(mode="json"),
            "inventory": entries,
        }
        save(audited / "audit_input.json", payload)
        provider = AuditProvider(audited, model, env_file)

        def audit_call():
            try:
                result = provider.call("claim_audit", payload, ClaimAudit)
                validate_audit(result, entries, evidence)
                provider.record_validation()
                return result
            except ValueError as exc:
                provider.record_validation(exc)
                raise

        if not (audited / "claim_audit.json").exists():
            result = retry(audit_call)
            save(audited / "claim_audit.json", result.model_dump(mode="json"))
        validate_audit(
            ClaimAudit.model_validate(read(audited / "claim_audit.json")), entries, evidence
        )
        state = retry(lambda: step(audited, provider))
    verify(audited)
    normal_states = sorted((baseline / "states").glob("*.json"))
    audited_states = sorted((audited / "states").glob("*.json"))
    assert len(normal_states) == len(audited_states)
    assert all(
        read(a) == read(b) for a, b in zip(normal_states[:-1], audited_states[:-1], strict=True)
    )
    assert state.status == "awaiting_review" and state.review is None
    assert not (audited / "decisions").exists() and not (baseline / "decisions").exists()
    save(
        root / f"pair-{pair:02d}-verification.json",
        {
            "shared_draft_exact_match": True,
            "prefix_revisions": len(normal_states) - 1,
            "scene_count": len(state.scenes),
            "audit_entries": len(read(audited / "claim_audit.json")["items"]),
            "no_review_or_diary": True,
        },
    )
    print(f"pair {pair}: both conditions awaiting_review, {len(state.scenes)} scenes", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pair", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3.1-flash-lite")
    args = parser.parse_args()
    paired_run(read(args.input), args.root, args.pair, args.env_file, args.model)


if __name__ == "__main__":
    main()
