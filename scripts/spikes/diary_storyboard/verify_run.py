"""Audit saved stage inputs and optionally compare an exact-request replay; no network."""

import argparse
import json
from pathlib import Path

from .candidates import check_candidate_scene, check_selection
from .contracts import Plan, SelectionPlan, State, check_plan, check_references
from .runner import load
from .storage import digest, read, save


def verify(run: Path, compare_replay: Path | None = None):
    _, evidence, current = load(run)
    if current is None:
        raise ValueError("no completed states")
    states = [State.model_validate(read(p)) for p in sorted((run / "states").glob("*.json"))]
    calls = []
    rejected_plans = []
    for path in sorted((run / "calls").glob("*/receipt.json")):
        receipt = read(path)
        request = read(path.parent / "request.json")
        assert digest(request) == receipt["request_sha256"]
        payload = json.loads(request["contents"][0]["parts"][0]["text"])
        answer_path = path.parent / "response.json"
        if not answer_path.exists() or receipt["status"] != "parsed":
            continue
        answer = read(answer_path)
        calls.append((receipt, payload, answer))
        if receipt["stage"] in ("understand", "select", "compose"):
            try:
                if receipt["stage"] in ("select", "compose"):
                    check_selection(SelectionPlan.model_validate(answer), evidence)
                else:
                    check_plan(Plan.model_validate(answer), evidence)
            except ValueError as exc:
                rejected_plans.append({"call": path.parent.name, "error": str(exc)})
    checks = []
    for index, state in enumerate(states):
        assert state.revision == index
        assert state.evidence_sha256 == current.evidence_sha256
        check_references(state, evidence)
        if state.selection is not None:
            check_selection(SelectionPlan(understanding=state.understanding,
                                         outline=state.outline, selection=state.selection), evidence)
            for scene in state.scenes:
                check_candidate_scene(scene, state, evidence)
        revision = state.revisions[-1]
        assert revision.revision == index
        if revision.stage == "review":
            assert state.review.base_revision == index - 1
            continue
        candidates = [(r, p, a) for r, p, a in calls if r["stage"] == revision.stage]
        matching = []
        for receipt, payload, answer in candidates:
            if payload.get("evidence_snapshot") != evidence.model_dump(mode="json"):
                continue
            if index and payload.get("board_before") != states[index - 1].model_dump(mode="json"):
                continue
            if answer["understanding"] != state.understanding.model_dump(mode="json"):
                continue
            if revision.stage == "scene" and answer["scene"] != state.scenes[-1].model_dump(
                mode="json"
            ):
                continue
            matching.append(receipt["request_sha256"])
        assert matching, f"no matching saved request/output for revision {index}"
        checks.append(
            {"revision": index, "stage": revision.stage, "source_and_previous_state_verified": True}
        )
    decisions = []
    for path in sorted((run / "decisions").glob("*/result.json")):
        decision = read(path.parent / "decision.json")
        snapshot = read(path.parent / "reviewed_snapshot.json")
        result = read(path)
        assert digest(snapshot) == decision["reviewed_snapshot_sha256"]
        state = states[decision["reviewed_revision"]]
        assert snapshot["storyboard_sha256"] == digest(state.model_dump(mode="json"))
        if decision["choice"] == "generate":
            assert any(
                r["stage"] == "diary"
                and p == {"reviewed_snapshot": snapshot}
                and a == result["diary"]
                for r, p, a in calls
            )
        else:
            assert result["diary_calls"] == 0
            assert not (path.parent / "diary.md").exists()
        decisions.append(
            {
                "revision": state.revision,
                "choice": decision["choice"],
                "snapshot_verified": True,
                "actor": snapshot["review"]["actor"],
            }
        )
    receipts = [read(p) for p in sorted((run / "calls").glob("*/receipt.json"))]
    report = {
        "model_calls": len([r for r in receipts if r["transport"] == "gemini"]),
        "replay_calls": len([r for r in receipts if r["transport"] == "replay"]),
        "fixture_calls": len([r for r in receipts if r["transport"] == "fixture"]),
        "total_tokens": sum((r.get("usage") or {}).get("totalTokenCount", 0) for r in receipts),
        "summed_latency_s": round(sum(r["latency_s"] for r in receipts), 3),
        "outline_count": len(current.outline),
        "verified_transitions": checks,
        "invalid_plan_attempts": rejected_plans,
        "decisions": decisions,
    }
    if compare_replay:
        replay_state = load(compare_replay)[2]
        assert current == replay_state
        prefix = f"{current.revision:06d}"
        for choice in ("skip", "generate"):
            relative = f"decisions/{prefix}-{choice}/result.json"
            original_path, replay_path = run / relative, compare_replay / relative
            assert original_path.exists() == replay_path.exists()
            if original_path.exists():
                assert read(original_path) == read(replay_path)
        assert all(
            read(p)["transport"] == "replay"
            for p in (compare_replay / "calls").glob("*/receipt.json")
        )
        report["replay_matches_current_state_and_decisions"] = True
    save(run / "verification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--compare-replay", type=Path)
    args = parser.parse_args()
    result = verify(args.run, args.compare_replay)
    print(
        f"verified {len(result['verified_transitions'])} recorded transitions; "
        f"{len(result['decisions'])} decisions"
    )


if __name__ == "__main__":
    main()
