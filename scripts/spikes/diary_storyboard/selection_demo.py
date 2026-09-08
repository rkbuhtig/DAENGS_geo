"""Offline candidate-to-storyboard walkthrough. Fixture text is not an LLM experiment."""

import argparse
import time
from datetime import datetime
from pathlib import Path

from .candidates import catalog_for
from .contracts import Evidence, SelectionPlan
from .provider import Provider
from .runner import build, initialize, load, step
from .selection_adapter import from_selection_case
from .storage import digest, read, save

ARCHIVE = (
    Path(__file__).resolve().parents[3]
    / "docs/research"
    / "2026-09-07-walk-diary-evidence/gemini-03.json"
)


class FixtureProvider(Provider):
    """Records the same request format, but has no path to network transport."""

    def __init__(self, run: Path):
        super().__init__(run, "offline-selection-fixture-v1")

    def answer(self, stage, payload):
        evidence = Evidence.model_validate(payload["evidence_snapshot"])
        catalog = catalog_for(evidence)
        pieces = {p.id: p for p in evidence.pieces}
        if stage == "compose":
            return grouped_fixture(self.answer("select", payload), catalog)
        if stage == "select":
            chosen = [c for c in catalog.candidates if c.required]
            # Deliberately simple fixture policy, never presented as quality selection.
            for candidate in catalog.candidates:
                if (
                    candidate.card_eligible
                    and candidate not in chosen
                    and len(chosen) < catalog.max_scenes
                ):
                    chosen.append(candidate)
            chosen.sort(key=lambda c: c.start_at)
            chosen_ids = {c.id for c in chosen}
            outline, decisions = [], []
            for candidate in catalog.candidates:
                selected = candidate.id in chosen_ids
                scene_id = f"scene-{candidate.id}" if selected else None
                code = (
                    "selected"
                    if selected
                    else "connection"
                    if not candidate.card_eligible
                    else "low_signal"
                )
                decisions.append(
                    {
                        "candidate_id": candidate.id,
                        "scene_id": scene_id,
                        "code": code,
                        "reason": f"[가짜 모델 검산·고정 비교 대상] {code}",
                    }
                )
                if selected:
                    outline.append(
                        {
                            "scene_id": scene_id,
                            "start_at": candidate.start_at,
                            "end_at": candidate.end_at,
                            "focus": candidate.why_keep,
                            "evidence_ids": [candidate.primary_evidence_id],
                        }
                    )
            outline.sort(key=lambda s: s["start_at"])
            return {
                "understanding": {
                    "summary": "가짜 모델로 상태 연결을 검산한 합성 산책",
                    "observed_flow": [],
                    "interpretations": [],
                    "open_questions": [],
                },
                "outline": outline,
                "selection": {"title_draft": None, "decisions": decisions},
            }
        previous = payload["board_before"]
        if stage == "scene":
            if "scene_context" in payload:
                events = payload["scene_context"]["events"]
                included = [e for e in events if e["membership"] == "included"]
                claims = [
                    {"text": e["source_text"], "evidence_ids": [e["primary_evidence_id"]]}
                    for e in included
                ]
                return {
                    "scene": {
                        "scene_id": payload["target_scene"]["scene_id"],
                        "title": "[검산용 묶음] " + payload["target_candidate"]["id"],
                        "text": " / ".join(c["text"] for c in claims),
                        "observed_facts": claims,
                        "interpretations": [],
                        "open_questions": [],
                        "connection_to_previous": "대표 사건 순서; 원본 시각은 구성표 참조",
                    },
                    "understanding": previous["understanding"],
                    "change_reason": "검산용 포함 기록 복사",
                    "evidence_ids": [i for c in claims for i in c["evidence_ids"]],
                    "revisit_scene_ids": [],
                }
            target = payload["target_candidate"]
            primary = target["primary_evidence_id"]
            text = pieces[primary].meaning
            return {
                "scene": {
                    "scene_id": payload["target_scene"]["scene_id"],
                    "title": f"[검산] {target['id']}",
                    "text": text,
                    "observed_facts": [{"text": text, "evidence_ids": [primary]}],
                    "interpretations": [],
                    "open_questions": [],
                    "connection_to_previous": "원본 사건 시각 순서",
                },
                "understanding": previous["understanding"],
                "change_reason": "검산용 근거 문구 복사",
                "evidence_ids": [primary],
                "revisit_scene_ids": [],
            }
        if stage == "reconcile":
            return {
                "understanding": previous["understanding"],
                "replacement_scenes": [],
                "change_reason": "가짜 모델은 의미 검토를 수행하지 않음",
                "evidence_ids": previous["outline"][0]["evidence_ids"],
                "findings": [],
            }
        raise ValueError("offline fixture supports only selection/storyboard stages")

    def call(self, stage, payload, contract):
        request = self.request(stage, payload, contract)
        root = self.run / "calls"
        root.mkdir(exist_ok=True)
        attempt = root / f"{len(list(root.iterdir())) + 1:06d}"
        attempt.mkdir()
        self.last_attempt = attempt
        save(attempt / "request.json", request)
        receipt = {
            "stage": stage,
            "requested_model": self.model,
            "request_sha256": digest(request),
            "transport": "fixture",
            "usage": None,
        }
        began = time.perf_counter()
        try:
            result = contract.model_validate(self.answer(stage, payload))
            save(attempt / "response.json", result.model_dump(mode="json"))
            receipt["status"] = "parsed"
            return result
        except ValueError as exc:
            receipt.update(status="failed", error=str(exc))
            raise
        finally:
            receipt["latency_s"] = round(time.perf_counter() - began, 3)
            save(attempt / "receipt.json", receipt)


def grouped_fixture(individual, catalog):
    """Pair the same selected events within chains. A plumbing fixture, not a scene policy."""
    plan = SelectionPlan.model_validate(individual)
    candidates = {c.id: c for c in catalog.candidates}
    chosen = [candidates[d.candidate_id] for d in plan.selection.decisions if d.code == "selected"]
    chosen.sort(key=lambda c: (c.start_at, c.id))
    groups = []
    for candidate in chosen:
        if not groups or len(groups[-1]) == 3 or groups[-1][0].chain != candidate.chain:
            groups.append([])
        groups[-1].append(candidate)
    outline, compositions, owners, contexts = [], [], {}, {i: [] for i in candidates}
    previous = None
    for index, events in enumerate(groups):
        primary = next((e for e in events if e.role == "action"), events[0])
        included = [e for e in events if e.role == "action"] or [primary]
        contextual = [e for e in events if e not in included]
        # Exposes shared context without counting that transition as a new occurrence.
        if previous and previous.chain == primary.chain and previous not in contextual:
            contextual.append(previous)
        scene_id = f"group-{index + 1}"
        for event in included:
            owners[event.id] = scene_id
        for event in contextual:
            contexts[event.id].append(scene_id)
        compositions.append(
            {
                "scene_id": scene_id,
                "primary_candidate_id": primary.id,
                "included_candidate_ids": [e.id for e in included],
                "context_candidate_ids": [e.id for e in contextual],
                "reason": "[오프라인 검산] 같은 chain의 최대 3사건을 묶은 배선용 예시",
            }
        )
        outline.append(
            {
                "scene_id": scene_id,
                "start_at": primary.start_at,
                "end_at": primary.end_at,
                "focus": primary.why_keep,
                "evidence_ids": [e.primary_evidence_id for e in included],
            }
        )
        previous = next((e for e in reversed(events) if e.role == "transition"), None)
    for decision in plan.selection.decisions:
        decision.context_scene_ids = contexts[decision.candidate_id]
        if decision.candidate_id in owners:
            decision.scene_id = owners[decision.candidate_id]
        elif decision.context_scene_ids:
            decision.code, decision.scene_id = "context", None
    result = plan.model_dump(mode="json")
    result["outline"] = outline
    result["selection"]["compositions"] = compositions
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--case", choices=["movement", "actions", "gap"], default="actions")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--started-at",
        type=datetime.fromisoformat,
        default=datetime.fromisoformat("2026-09-07T09:00:00+09:00"),
        help="Synthetic absolute time for relative-offset archive",
    )
    parser.add_argument("--steps", type=int, help="Stop after this many completed steps")
    parser.add_argument("--composition", choices=["individual", "grouped"], default="individual")
    args = parser.parse_args()
    if args.steps is not None and args.steps < 1:
        parser.error("--steps must be positive")
    case = next(c for c in read(args.archive)["cases"] if c["id"] == args.case)
    evidence = from_selection_case(
        case,
        started_at=args.started_at,
        session_id=f"archived-v3-{args.case}",
        composition_mode=args.composition,
    )
    provider = FixtureProvider(args.run)
    if not (args.run / "config.json").exists():
        initialize(args.run, evidence.model_dump(mode="json"), provider.model)
    config, saved, state = load(args.run)
    if config["model"] != provider.model or saved != evidence:
        raise ValueError("demo input/model changed; use a new run directory")
    if args.steps is None:
        state = build(args.run, provider)
    else:
        for _ in range(args.steps):
            state = step(args.run, provider)
            if state.status in ("awaiting_review", "reviewed"):
                break
    print(
        f"offline fixture: {state.status}; revision={state.revision}; "
        f"scenes={len(state.scenes)}; no model API calls"
    )


if __name__ == "__main__":
    main()
