"""Typed candidate catalog and selection checks; no narrative quality scoring."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .contracts import Contract, Evidence, SelectionPlan, check_references

CATALOG_KEY = "candidate_catalog"


class Candidate(Contract):
    id: str = Field(min_length=1)
    role: Literal["action", "transition", "connection"]
    time_kind: Literal["point", "interval"]
    start_at: datetime
    end_at: datetime
    chain: int = Field(ge=0)
    card_eligible: bool
    required: bool
    why_keep: str
    evidence_ids: list[str]
    subject_ids: list[str]
    primary_evidence_id: str | None
    # An archived event reference is not a resolved observation coordinate.
    source_event_id: str
    source_input_sha256: str
    location_status: Literal["unresolved"] = "unresolved"


class Gap(Contract):
    start_at: datetime
    end_at: datetime


class CandidateCatalog(Contract):
    version: Literal["candidate-catalog-v1"] = "candidate-catalog-v1"
    policy_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    max_scenes: int = Field(ge=0)
    candidates: list[Candidate]
    gaps: list[Gap]
    composition_mode: Literal["individual", "grouped"] = "individual"


def catalog_for(evidence: Evidence) -> CandidateCatalog | None:
    raw = evidence.context.get(CATALOG_KEY)
    if raw is None:
        return None
    catalog = CandidateCatalog.model_validate(raw)
    pieces = {p.id: p for p in evidence.pieces}
    ids = [c.id for c in catalog.candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate IDs")
    if (catalog.composition_mode == "individual"
            and sum(c.required for c in catalog.candidates) > catalog.max_scenes):
        raise ValueError("required candidates exceed scene budget")
    for gap in catalog.gaps:
        if gap.start_at.tzinfo is None or gap.end_at.tzinfo is None:
            raise ValueError("gap timestamps require timezone")
        if not evidence.started_at <= gap.start_at < gap.end_at <= evidence.ended_at:
            raise ValueError("invalid gap bounds")
    starts = []
    for candidate in catalog.candidates:
        start, end = candidate.start_at, candidate.end_at
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("candidate timestamps require timezone")
        if not evidence.started_at <= start <= end <= evidence.ended_at:
            raise ValueError("candidate outside session")
        if (candidate.time_kind == "point") != (start == end):
            raise ValueError("candidate time kind disagrees with bounds")
        if any(start < gap.end_at and end > gap.start_at for gap in catalog.gaps):
            raise ValueError("candidate crosses GPS gap")
        refs = candidate.evidence_ids + candidate.subject_ids
        if len(refs) != len(set(refs)) or not set(refs) <= set(pieces):
            raise ValueError("candidate evidence IDs are duplicate or unknown")
        if any(pieces[i].kind != "who" for i in candidate.subject_ids):
            raise ValueError("candidate subjects must refer to actors")
        if candidate.role == "connection" and (candidate.card_eligible or candidate.required):
            raise ValueError("connection cannot be a card or required")
        if candidate.required and not candidate.card_eligible:
            raise ValueError("required candidate must be eligible")
        if candidate.card_eligible and candidate.primary_evidence_id not in candidate.evidence_ids:
            raise ValueError("eligible candidate requires a primary evidence ID")
        starts.append(start)
    if starts != sorted(starts):
        raise ValueError("candidates must be chronological")
    return catalog


def check_selection(plan: SelectionPlan, evidence: Evidence) -> None:
    check_references(plan, evidence)
    catalog = catalog_for(evidence)
    if catalog is None:
        raise ValueError("selection requires a candidate catalog")
    candidates = {c.id: c for c in catalog.candidates}
    decisions = plan.selection.decisions
    decision_ids = [d.candidate_id for d in decisions]
    if len(decision_ids) != len(set(decision_ids)) or set(decision_ids) != set(candidates):
        raise ValueError("selection must account for every candidate exactly once")
    scene_ids = [s.scene_id for s in plan.outline]
    if len(scene_ids) != len(set(scene_ids)) or len(scene_ids) > catalog.max_scenes:
        raise ValueError("duplicate scene ID or exceeded scene budget")
    if catalog.composition_mode == "grouped":
        from .composition import check_composition

        check_composition(plan, catalog)
        return
    if plan.selection.compositions or any(d.context_scene_ids for d in decisions):
        raise ValueError("individual mode cannot contain grouped composition")
    selected = [d for d in decisions if d.code == "selected"]
    if len(selected) != len(scene_ids) or {d.scene_id for d in selected} != set(scene_ids):
        raise ValueError("selected decisions must map one-to-one to scenes")
    outlines = {s.scene_id: s for s in plan.outline}
    for decision in decisions:
        candidate = candidates[decision.candidate_id]
        if decision.code != "selected":
            if decision.code == "context":
                raise ValueError("individual mode cannot use context-only decisions")
            if decision.scene_id is not None or candidate.required:
                raise ValueError("omitted candidate has scene ID or is required")
            if not candidate.card_eligible and decision.code != "connection":
                raise ValueError("ineligible connection needs connection omission reason")
            if candidate.card_eligible and decision.code == "connection":
                raise ValueError("eligible event is not a connection")
            if decision.code == "budget" and len(scene_ids) < catalog.max_scenes:
                raise ValueError("budget omission while scene capacity remains")
            continue
        if not candidate.card_eligible:
            raise ValueError("connection cannot be selected")
        scene = outlines[decision.scene_id]
        if scene.start_at != candidate.start_at or scene.end_at != candidate.end_at:
            raise ValueError("scene must preserve candidate point or interval bounds")
        refs = scene.evidence_ids
        allowed = set(candidate.evidence_ids + candidate.subject_ids)
        if len(refs) != len(set(refs)) or not set(refs) <= allowed:
            raise ValueError("scene references another candidate's evidence")
        if candidate.primary_evidence_id not in refs:
            raise ValueError("scene must cite its primary evidence")
    starts = [s.start_at for s in plan.outline]
    if starts != sorted(starts):
        raise ValueError("selected scenes must be chronological")


def candidate_for_scene(state, scene_id: str, evidence: Evidence) -> Candidate:
    catalog = catalog_for(evidence)
    if catalog.composition_mode == "grouped":
        composition = next(c for c in state.selection.compositions if c.scene_id == scene_id)
        return next(c for c in catalog.candidates if c.id == composition.primary_candidate_id)
    decision = next(d for d in state.selection.decisions if d.scene_id == scene_id)
    return next(c for c in catalog.candidates if c.id == decision.candidate_id)


def check_candidate_scene(scene, state, evidence: Evidence) -> None:
    if catalog_for(evidence).composition_mode == "grouped":
        from .composition import check_composed_scene

        check_composed_scene(scene, state, evidence)
        return
    candidate = candidate_for_scene(state, scene.scene_id, evidence)
    claims = scene.observed_facts + scene.interpretations
    references = {i for claim in claims for i in claim.evidence_ids}
    if not references <= set(candidate.evidence_ids + candidate.subject_ids):
        raise ValueError("scene claims reference another candidate's evidence")
    if candidate.primary_evidence_id not in references:
        raise ValueError("scene claims must retain primary evidence")
