"""Checkpointed stage machine. Model meaning is never promoted into source evidence."""

from pathlib import Path

from .candidates import (
    candidate_for_scene,
    catalog_for,
    check_candidate_scene,
    check_selection,
)
from .composition import scene_context
from .contracts import (
    Diary,
    Edit,
    Evidence,
    Plan,
    Reconciliation,
    Review,
    Revision,
    SceneUpdate,
    SelectionPlan,
    State,
    check_plan,
    check_references,
)
from .evidence import from_scenario
from .prompts import COMMON, STAGES
from .selection_prompts import selection_instructions
from .storage import checkpoint, digest, export, latest, read, save


def initialize(run: Path, source: dict, model: str):
    evidence = from_scenario(source)
    catalog = catalog_for(evidence)
    if run.exists() and any(run.iterdir()):
        raise ValueError("start requires a new empty run directory")
    run.mkdir(parents=True, exist_ok=True)
    snapshot = evidence.model_dump(mode="json")
    save(run / "evidence_snapshot.json", snapshot)
    save(
        run / "config.json",
        {
            "model": model,
            "evidence_sha256": digest(snapshot),
            "prompt_sha256": digest({"common": COMMON, "stages": STAGES}),
            "contract_version": "diary-skeleton-v1",
            **({"selection_prompt_sha256": digest(selection_instructions(catalog)),
                "selection_schema_sha256": digest(SelectionPlan.model_json_schema())}
               if catalog is not None else {}),
        },
    )


def load(run: Path):
    config = read(run / "config.json")
    snapshot = read(run / "evidence_snapshot.json")
    if digest(snapshot) != config["evidence_sha256"]:
        raise ValueError("evidence snapshot changed; start a new run")
    if config["prompt_sha256"] != digest({"common": COMMON, "stages": STAGES}):
        raise ValueError("prompts changed; start a new run")
    evidence = Evidence.model_validate(snapshot)
    catalog = catalog_for(evidence)
    if catalog is not None and (
        config.get("selection_prompt_sha256") != digest(selection_instructions(catalog))
        or config.get("selection_schema_sha256") != digest(SelectionPlan.model_json_schema())
    ):
        raise ValueError("selection prompt or schema changed; start a new run")
    state = latest(run)
    if state and state.evidence_sha256 != config["evidence_sha256"]:
        raise ValueError("state and evidence snapshot differ")
    if state and catalog is not None:
        if state.selection is None:
            raise ValueError("candidate run is missing selection metadata")
        check_selection(SelectionPlan(
            understanding=state.understanding, outline=state.outline, selection=state.selection
        ), evidence)
    return config, evidence, state


def step(run: Path, provider) -> State:
    try:
        result = _step(run, provider)
        if hasattr(provider, "record_validation"):
            provider.record_validation()
        return result
    except ValueError as exc:
        if hasattr(provider, "record_validation"):
            provider.record_validation(exc)
        errors = run / "stage_errors"
        errors.mkdir(exist_ok=True)
        save(
            errors / f"{len(list(errors.glob('*.json'))) + 1:06d}.json",
            {
                "error": str(exc),
                "last_completed_revision": latest(run).revision if latest(run) else None,
                "attempted_call_count": len(list((run / "calls").glob("*"))),
            },
        )
        raise


def _step(run: Path, provider) -> State:
    config, evidence, previous = load(run)
    if previous and previous.status in ("awaiting_review", "reviewed"):
        export(run, previous)
        return previous
    payload = {"evidence_snapshot": evidence.model_dump(mode="json")}
    if previous is None:
        catalog = catalog_for(evidence)
        stage = "select" if catalog is not None else "understand"
        if catalog is not None and catalog.composition_mode == "grouped":
            stage = "compose"
        result = provider.call(stage, payload, SelectionPlan if catalog is not None else Plan)
        if catalog is not None:
            check_selection(result, evidence)
        else:
            check_plan(result, evidence)
        state = State(
            revision=0,
            status="filling" if result.outline else "awaiting_review",
            evidence_sha256=config["evidence_sha256"],
            understanding=result.understanding,
            outline=result.outline,
            scenes=[],
            revisit_scene_ids=[],
            findings=[],
            revisions=[],
            selection=result.selection if catalog is not None else None,
        )
        reason = "전체 자료에서 잠정 이해와 장면 개요 작성"
        sources = sorted({i for s in result.outline for i in s.evidence_ids})
        affected = [s.scene_id for s in result.outline]
    else:
        state = previous.model_copy(deep=True)
        state.revision += 1
        payload["board_before"] = previous.model_dump(mode="json")
        if previous.status == "filling":
            target = previous.outline[len(previous.scenes)]
            payload["target_scene"] = target.model_dump(mode="json")
            if previous.selection is not None:
                payload["target_candidate"] = candidate_for_scene(
                    previous, target.scene_id, evidence
                ).model_dump(mode="json")
                if catalog_for(evidence).composition_mode == "grouped":
                    payload["scene_context"] = scene_context(previous, target.scene_id, evidence)
            result = provider.call("scene", payload, SceneUpdate)
            check_references(result, evidence)
            if result.scene.scene_id != target.scene_id:
                raise ValueError("model returned a different target scene")
            if previous.selection is not None:
                check_candidate_scene(result.scene, previous, evidence)
            if not set(result.revisit_scene_ids) <= {s.scene_id for s in previous.scenes}:
                raise ValueError("revisit must refer to already completed scenes")
            state.scenes.append(result.scene)
            state.understanding = result.understanding
            state.revisit_scene_ids = sorted(
                set(state.revisit_scene_ids) | set(result.revisit_scene_ids)
            )
            if len(state.scenes) == len(state.outline):
                state.status = "reconciling"
            stage, reason = "scene", result.change_reason
            sources, affected = result.evidence_ids, [target.scene_id]
        else:
            result = provider.call("reconcile", payload, Reconciliation)
            check_references(result, evidence)
            known = {s.scene_id for s in state.scenes}
            replacements = {s.scene_id: s for s in result.replacement_scenes}
            if len(replacements) != len(result.replacement_scenes):
                raise ValueError("duplicate reconciliation replacements")
            referenced = set(replacements) | {i for f in result.findings for i in f.scene_ids}
            if not referenced <= known:
                raise ValueError("reconciliation refers to an unknown scene")
            if previous.selection is not None:
                for replacement in result.replacement_scenes:
                    check_candidate_scene(replacement, previous, evidence)
            state.scenes = [replacements.get(s.scene_id, s) for s in state.scenes]
            state.understanding = result.understanding
            state.findings = result.findings
            state.status = "awaiting_review"
            stage, reason = "reconcile", result.change_reason
            sources, affected = result.evidence_ids, list(replacements)
    state.revisions.append(
        Revision(
            revision=state.revision,
            stage=stage,
            reason=reason,
            evidence_ids=sources,
            affected_scene_ids=affected,
        )
    )
    checkpoint(run, state)
    return state


def build(run: Path, provider) -> State:
    while True:
        state = step(run, provider)
        if state.status in ("awaiting_review", "reviewed"):
            return state


def review(run: Path, expected_revision: int, actor: str, reviewer: str, edits: list[Edit]):
    _, _, previous = load(run)
    if previous is None or previous.status not in ("awaiting_review", "reviewed"):
        raise ValueError("complete and reconcile the storyboard before review")
    if previous.revision != expected_revision:
        raise ValueError("stale review revision")
    ids = [e.scene_id for e in edits]
    if len(ids) != len(set(ids)) or not set(ids) <= {s.scene_id for s in previous.scenes}:
        raise ValueError("duplicate or unknown edited scene")
    # Edits supplied here patch previous user edits, preserving untouched edits.
    merged = {e.scene_id: e for e in previous.review.edits} if previous.review else {}
    for edit in edits:
        if edit.scene_id in merged:
            merged[edit.scene_id] = merged[edit.scene_id].model_copy(
                update=edit.model_dump(exclude_unset=True)
            )
        else:
            merged[edit.scene_id] = edit
    state = previous.model_copy(deep=True)
    state.revision += 1
    state.review = Review(
        actor=actor, reviewer=reviewer, base_revision=expected_revision, edits=list(merged.values())
    )
    state.status = "reviewed"
    state.revisions.append(
        Revision(
            revision=state.revision,
            stage="review",
            reason=f"{actor}: {reviewer}",
            evidence_ids=[],
            affected_scene_ids=ids,
        )
    )
    checkpoint(run, state)
    return state


def reviewed_snapshot(state: State, evidence: Evidence | None = None) -> dict:
    grouped = state.selection is not None and bool(state.selection.compositions)
    if grouped and evidence is None:
        raise ValueError("grouped review requires source event snapshot")
    edits = {e.scene_id: e for e in state.review.edits}
    outlines = {s.scene_id: s for s in state.outline}
    scenes = []
    for scene in state.scenes:
        edit = edits.get(scene.scene_id)
        if edit and not edit.included:
            continue
        effective = scene.model_dump(mode="json")
        if edit:
            if edit.title is not None:
                effective["title"] = edit.title
            if edit.text is not None:
                effective["text"] = edit.text
                # Old model claims can conflict with a user's corrected prose.
                for key in (
                    "observed_facts",
                    "interpretations",
                    "open_questions",
                    "connection_to_previous",
                ):
                    effective.pop(key)
        outline = outlines[scene.scene_id]
        effective.update(start_at=outline.start_at.isoformat(), end_at=outline.end_at.isoformat())
        if grouped:
            effective["scene_context"] = scene_context(state, scene.scene_id, evidence)
        scenes.append(effective)
    return {
        "storyboard_revision": state.revision,
        "storyboard_sha256": digest(state.model_dump(mode="json")),
        "evidence_sha256": state.evidence_sha256,
        "review": state.review.model_dump(mode="json", exclude={"edits"}),
        "scenes": scenes,
    }


def decide(run: Path, expected_revision: int, choice: str, provider=None):
    _, evidence, state = load(run)
    if state is None or state.status != "reviewed" or state.revision != expected_revision:
        raise ValueError("decision requires the exact reviewed revision")
    if choice not in ("skip", "generate"):
        raise ValueError("unknown decision")
    snapshot = reviewed_snapshot(state, evidence)
    destination = run / "decisions" / f"{state.revision:06d}-{choice}"
    result_path = destination / "result.json"
    if result_path.exists():
        prior_snapshot = read(destination / "reviewed_snapshot.json")
        if digest(prior_snapshot) != digest(snapshot):
            raise ValueError("reviewed version changed after decision")
        return read(result_path)
    save(destination / "reviewed_snapshot.json", snapshot)
    save(
        destination / "decision.json",
        {
            "choice": choice,
            "reviewed_revision": state.revision,
            "reviewed_snapshot_sha256": digest(snapshot),
            "review_actor": state.review.actor,
        },
    )
    if choice == "skip":
        result = {"status": "kept_without_diary", "diary_calls": 0}
    else:
        if not snapshot["scenes"]:
            raise ValueError("no included scenes to generate a diary from")
        if provider is None:
            raise ValueError("generation requires a provider")
        diary = provider.call("diary", {"reviewed_snapshot": snapshot}, Diary)
        if not set(diary.used_scene_ids) <= {s["scene_id"] for s in snapshot["scenes"]}:
            if hasattr(provider, "record_validation"):
                provider.record_validation("diary references a hidden or unknown scene")
            raise ValueError("diary references a hidden or unknown scene")
        if hasattr(provider, "record_validation"):
            provider.record_validation()
        result = {
            "status": "generated",
            "storyboard_revision": state.revision,
            "reviewed_snapshot_sha256": digest(snapshot),
            "diary": diary.model_dump(),
        }
        (destination / "diary.md").write_text(
            f"# {diary.title}\n\n{diary.text}\n",
            encoding="utf-8",
        )
    save(result_path, result)
    return result
