"""Model edits event membership; the system resolves immutable source fields."""

from typing import Literal

from pydantic import Field

from .candidates import catalog_for, check_selection
from .composition import scene_context
from .contracts import (
    Claim,
    Contract,
    Outline,
    SceneComposition,
    SelectionDecision,
    SelectionMetadata,
    SelectionPlan,
    Understanding,
)


class EventClaim(Contract):
    text: str = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=1)


class EditorialUnderstanding(Contract):
    summary: str
    observed_flow: list[EventClaim]
    interpretations: list[EventClaim]
    open_questions: list[str]


class Omission(Contract):
    candidate_id: str
    code: Literal["redundant", "low_signal", "insufficient", "budget"]
    reason: str = Field(min_length=1)


class IndividualScene(Contract):
    candidate_id: str
    focus: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class GroupedScene(Contract):
    primary_candidate_id: str
    included_candidate_ids: list[str] = Field(min_length=1)
    context_candidate_ids: list[str]
    focus: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class IndividualEditorialPlan(Contract):
    understanding: EditorialUnderstanding
    title_draft: EventClaim | None
    scenes: list[IndividualScene]
    omissions: list[Omission]


class GroupedEditorialPlan(Contract):
    understanding: EditorialUnderstanding
    title_draft: EventClaim | None
    scenes: list[GroupedScene]
    omissions: list[Omission]


def wire_contract(mode):
    if mode == "individual":
        return IndividualEditorialPlan
    if mode == "grouped":
        return GroupedEditorialPlan
    raise ValueError("unknown editorial mode")


def resolve_plan(proposal, evidence):
    """Reject invalid choices; never repair them, invent locations or extend actions."""
    catalog = catalog_for(evidence)
    if catalog is None or not isinstance(proposal, wire_contract(catalog.composition_mode)):
        raise ValueError("editorial proposal does not match evidence mode")
    candidates = {c.id: c for c in catalog.candidates}
    grouped = catalog.composition_mode == "grouped"

    def events(ids):
        if len(ids) != len(set(ids)) or not set(ids) <= set(candidates):
            raise ValueError("duplicate or unknown event reference")
        return [candidates[i] for i in ids]

    def refs(ids):
        return sorted({ref for c in events(ids) for ref in c.evidence_ids + c.subject_ids})

    def claim(value):
        return Claim(text=value.text, evidence_ids=refs(value.candidate_ids))

    entries = []
    for scene in proposal.scenes:
        primary_id = scene.primary_candidate_id if grouped else scene.candidate_id
        included = scene.included_candidate_ids if grouped else [primary_id]
        context = scene.context_candidate_ids if grouped else []
        events(included + context)
        if primary_id not in included:
            raise ValueError("primary must be included")
        entries.append((candidates[primary_id], included, context, scene))
    # Chronology and stable IDs are presentation mechanics, not another model decision.
    entries.sort(key=lambda entry: (entry[0].start_at, entry[0].id))
    owners, contexts, outlines, compositions = {}, {}, [], []
    for index, (primary, included, context, scene) in enumerate(entries, 1):
        scene_id = f"scene_{index:02d}"
        for event_id in included:
            if event_id in owners:
                raise ValueError("duplicate event ownership")
            owners[event_id] = (scene_id, scene.reason)
        for event_id in context:
            contexts.setdefault(event_id, []).append(scene_id)
        outlines.append(
            Outline(
                scene_id=scene_id,
                start_at=primary.start_at,
                end_at=primary.end_at,
                focus=scene.focus,
                evidence_ids=refs(included + context),
            )
        )
        if grouped:
            compositions.append(
                SceneComposition(
                    scene_id=scene_id,
                    primary_candidate_id=primary.id,
                    included_candidate_ids=included,
                    context_candidate_ids=context,
                    reason=scene.reason,
                )
            )
    omissions = {o.candidate_id: o for o in proposal.omissions}
    if len(omissions) != len(proposal.omissions):
        raise ValueError("duplicate omission")
    expected = {
        c.id
        for c in candidates.values()
        if c.card_eligible and c.id not in owners and c.id not in contexts
    }
    if set(omissions) != expected:
        raise ValueError("omissions must cover exactly unused eligible events")
    decisions = []
    for candidate in catalog.candidates:
        event_id = candidate.id
        if event_id in owners:
            scene_id, reason = owners[event_id]
            code = "selected"
        elif event_id in contexts:
            scene_id, code, reason = None, "context", "구성의 맥락 참조에서 파생"
        elif not candidate.card_eligible:
            scene_id, code, reason = None, "connection", "원본의 카드 비대상 연결 구간"
        else:
            omission = omissions[event_id]
            scene_id, code, reason = None, omission.code, omission.reason
        decisions.append(
            SelectionDecision(
                candidate_id=event_id,
                scene_id=scene_id,
                code=code,
                reason=reason,
                context_scene_ids=contexts.get(event_id, []),
            )
        )
    title = proposal.title_draft
    if title and not set(title.candidate_ids) <= set(owners) | set(contexts):
        raise ValueError("title must refer to selected scene events")
    understanding = proposal.understanding
    result = SelectionPlan(
        understanding=Understanding(
            summary=understanding.summary,
            observed_flow=[claim(c) for c in understanding.observed_flow],
            interpretations=[claim(c) for c in understanding.interpretations],
            open_questions=understanding.open_questions,
        ),
        outline=outlines,
        selection=SelectionMetadata(
            title_draft=claim(title) if title else None,
            decisions=decisions,
            compositions=compositions,
        ),
    )
    check_selection(result, evidence)
    return result


def resolved_scopes(plan, evidence):
    """Keep editorial extent separate from representative and each observation's time."""
    candidates = {c.id: c for c in catalog_for(evidence).candidates}
    scopes = []
    for scene in plan.outline:
        if plan.selection.compositions:
            records = scene_context(plan, scene.scene_id, evidence)["events"]
        else:
            decision = next(d for d in plan.selection.decisions if d.scene_id == scene.scene_id)
            records = [
                {
                    **candidates[decision.candidate_id].model_dump(mode="json"),
                    "candidate_id": decision.candidate_id,
                    "membership": "included",
                }
            ]
        included = [candidates[r["candidate_id"]] for r in records if r["membership"] == "included"]
        scopes.append(
            {
                "scene_id": scene.scene_id,
                "representative_start_at": scene.start_at.isoformat(),
                "representative_end_at": scene.end_at.isoformat(),
                "included_extent": {
                    "start_at": min(c.start_at for c in included).isoformat(),
                    "end_at": max(c.end_at for c in included).isoformat(),
                    "meaning": "editorial envelope only; not action duration or continuous observation",
                },
                "source_events": records,
            }
        )
    return scopes
