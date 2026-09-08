"""Many events per scene, immutable source scopes, explicit ownership and shared context."""

from .candidates import catalog_for


def check_composition(plan, catalog):
    candidates = {c.id: c for c in catalog.candidates}
    scenes = {s.scene_id: s for s in plan.outline}
    groups = plan.selection.compositions
    group_ids = [g.scene_id for g in groups]
    if len(group_ids) != len(set(group_ids)) or set(group_ids) != set(scenes):
        raise ValueError("every scene needs exactly one composition")
    owners, contexts = {}, {i: set() for i in candidates}
    for group in groups:
        ids = group.included_candidate_ids + group.context_candidate_ids
        if len(ids) != len(set(ids)) or not set(ids) <= set(candidates):
            raise ValueError("composition has duplicate or unknown event IDs")
        if group.primary_candidate_id not in group.included_candidate_ids:
            raise ValueError("representative event must be included, not context-only")
        primary = candidates[group.primary_candidate_id]
        events = [candidates[i] for i in ids]
        if len({c.chain for c in events}) > 1:
            raise ValueError("composition cannot join GPS chains")
        start, end = min(c.start_at for c in events), max(c.end_at for c in events)
        if any(start < gap.end_at and end > gap.start_at for gap in catalog.gaps):
            raise ValueError("composition cannot bridge GPS gap")
        for event_id in group.included_candidate_ids:
            if not candidates[event_id].card_eligible:
                raise ValueError("connection cannot be an included event")
            if event_id in owners:
                raise ValueError("an event cannot be included in two scenes")
            owners[event_id] = group.scene_id
        for event_id in group.context_candidate_ids:
            contexts[event_id].add(group.scene_id)
        scene = scenes[group.scene_id]
        if (scene.start_at, scene.end_at) != (primary.start_at, primary.end_at):
            raise ValueError("scene must preserve representative event bounds")
        allowed = {i for c in events for i in c.evidence_ids + c.subject_ids}
        refs = scene.evidence_ids
        if len(refs) != len(set(refs)) or not set(refs) <= allowed:
            raise ValueError("composition cites evidence outside its events")
        required = {candidates[i].primary_evidence_id for i in group.included_candidate_ids}
        if not required <= set(refs):
            raise ValueError("composition must cite every included event's primary evidence")
    for decision in plan.selection.decisions:
        event_id = decision.candidate_id
        candidate = candidates[event_id]
        context_ids = decision.context_scene_ids
        if len(context_ids) != len(set(context_ids)) or set(context_ids) != contexts[event_id]:
            raise ValueError("context decisions disagree with composition membership")
        if event_id in owners:
            if decision.code != "selected" or decision.scene_id != owners[event_id]:
                raise ValueError("included decision disagrees with scene ownership")
        elif contexts[event_id]:
            if decision.code != "context" or decision.scene_id is not None:
                raise ValueError("context-only event must have context decision")
        else:
            if decision.scene_id is not None or decision.code in ("selected", "context"):
                raise ValueError("omitted event has a scene mapping")
            if not candidate.card_eligible and decision.code != "connection":
                raise ValueError("omitted connection needs connection reason")
            if candidate.card_eligible and decision.code == "connection":
                raise ValueError("eligible event is not a connection")
            if decision.code == "budget" and len(scenes) < catalog.max_scenes:
                raise ValueError("budget omission while scene capacity remains")
        if candidate.required and event_id not in owners:
            raise ValueError("required record must be included, not only context")
    starts = [s.start_at for s in plan.outline]
    if starts != sorted(starts):
        raise ValueError("scenes must follow representative event chronology")


def scene_context(state, scene_id, evidence):
    """Resolve source records for writing/export; never invent coordinates or union action times."""
    catalog = catalog_for(evidence)
    group = next(g for g in state.selection.compositions if g.scene_id == scene_id)
    ids = group.included_candidate_ids + group.context_candidate_ids
    candidates = {c.id: c for c in catalog.candidates}
    pieces = {p.id: p for p in evidence.pieces}
    records = []
    for event in sorted((candidates[i] for i in ids), key=lambda c: (c.start_at, c.id)):
        records.append(
            {
                "candidate_id": event.id,
                "membership": "included" if event.id in group.included_candidate_ids else "context",
                "role": event.role,
                "time_kind": event.time_kind,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat(),
                "chain": event.chain,
                "source_event_id": event.source_event_id,
                "source_input_sha256": event.source_input_sha256,
                "location_status": event.location_status,
                "evidence_ids": event.evidence_ids,
                "subject_ids": event.subject_ids,
                "primary_evidence_id": event.primary_evidence_id,
                "source_text": pieces[event.primary_evidence_id].meaning
                if event.primary_evidence_id
                else None,
            }
        )
    return {
        "composition": group.model_dump(mode="json"),
        "events": records,
        "time_semantics": "outline bounds describe the representative event only",
    }


def check_composed_scene(scene, state, evidence):
    context = scene_context(state, scene.scene_id, evidence)
    events = context["events"]
    refs = {i for c in scene.observed_facts + scene.interpretations for i in c.evidence_ids}
    allowed = {i for e in events for i in e["evidence_ids"] + e["subject_ids"]}
    if not refs <= allowed:
        raise ValueError("scene claims cite evidence outside composition")
    required = {e["primary_evidence_id"] for e in events if e["membership"] == "included"}
    if not required <= refs:
        raise ValueError("scene claims must retain every included event's primary evidence")
