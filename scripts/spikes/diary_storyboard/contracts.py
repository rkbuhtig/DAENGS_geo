"""Experimental wire contracts, independent of the model transport."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Piece(Contract):
    id: str
    kind: str
    session_links: dict[str, Any]
    value: dict[str, Any]
    meaning: str
    provenance: dict[str, Any]
    measurement_status: str


class Evidence(Contract):
    schema_version: Literal["diary-evidence-v1"] = "diary-evidence-v1"
    session_id: str
    started_at: datetime
    ended_at: datetime
    context: dict[str, Any]
    pieces: list[Piece]

    @model_validator(mode="after")
    def valid_snapshot(self):
        if self.started_at.tzinfo is None or self.ended_at.tzinfo is None:
            raise ValueError("session timestamps require timezone")
        if self.started_at >= self.ended_at:
            raise ValueError("session end must follow start")
        ids = [p.id for p in self.pieces]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be nonempty and unique")
        return self


class Claim(Contract):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class Understanding(Contract):
    summary: str
    observed_flow: list[Claim]
    interpretations: list[Claim]
    open_questions: list[str]


class Outline(Contract):
    scene_id: str
    start_at: datetime
    end_at: datetime
    focus: str
    evidence_ids: list[str] = Field(min_length=1)


class Plan(Contract):
    understanding: Understanding
    outline: list[Outline] = Field(min_length=1)


class SelectionDecision(Contract):
    candidate_id: str
    scene_id: str | None
    code: Literal[
        "selected", "context", "connection", "redundant", "low_signal", "insufficient", "budget"
    ]
    reason: str = Field(min_length=1)
    context_scene_ids: list[str] = Field(default_factory=list)


class SceneComposition(Contract):
    """Editorial membership only; event times and locations stay in the source catalog."""

    scene_id: str
    primary_candidate_id: str
    included_candidate_ids: list[str] = Field(min_length=1)
    context_candidate_ids: list[str]
    reason: str = Field(min_length=1)


class SelectionMetadata(Contract):
    title_draft: Claim | None
    decisions: list[SelectionDecision]
    compositions: list[SceneComposition] = Field(default_factory=list)


class SelectionPlan(Contract):
    understanding: Understanding
    outline: list[Outline]
    selection: SelectionMetadata


class Scene(Contract):
    scene_id: str
    title: str
    text: str
    observed_facts: list[Claim]
    interpretations: list[Claim]
    open_questions: list[str]
    connection_to_previous: str


class SceneUpdate(Contract):
    scene: Scene
    understanding: Understanding
    change_reason: str
    evidence_ids: list[str] = Field(min_length=1)
    revisit_scene_ids: list[str]


class Finding(Contract):
    scene_ids: list[str]
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class Reconciliation(Contract):
    understanding: Understanding
    replacement_scenes: list[Scene]
    change_reason: str
    evidence_ids: list[str] = Field(min_length=1)
    findings: list[Finding]


class Diary(Contract):
    title: str
    text: str
    used_scene_ids: list[str] = Field(min_length=1)


class Edit(Contract):
    scene_id: str
    title: str | None = None
    text: str | None = None
    included: bool = True


class Review(Contract):
    actor: Literal["human", "simulated"]
    reviewer: str = Field(min_length=1)
    base_revision: int
    edits: list[Edit]


class Revision(Contract):
    revision: int
    stage: str
    reason: str
    evidence_ids: list[str]
    affected_scene_ids: list[str]


class State(Contract):
    revision: int
    status: Literal["filling", "reconciling", "awaiting_review", "reviewed"]
    evidence_sha256: str
    understanding: Understanding
    outline: list[Outline]
    scenes: list[Scene]
    revisit_scene_ids: list[str]
    findings: list[Finding]
    revisions: list[Revision]
    review: Review | None = None
    selection: SelectionMetadata | None = None


def check_references(value: Contract, evidence: Evidence) -> None:
    """Check identity, not whether a cited observation entails the claim."""
    known = {p.id for p in evidence.pieces}

    def visit(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "evidence_ids" and not set(child) <= known:
                    raise ValueError(f"unknown evidence IDs: {set(child) - known}")
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value.model_dump(mode="json"))


def check_plan(plan: Plan, evidence: Evidence) -> None:
    check_references(plan, evidence)
    ids = [s.scene_id for s in plan.outline]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scene IDs")
    starts = []
    for s in plan.outline:
        if s.start_at.tzinfo is None or s.end_at.tzinfo is None:
            raise ValueError("scene timestamps require timezone")
        if not evidence.started_at <= s.start_at < s.end_at <= evidence.ended_at:
            raise ValueError("scene outside session or invalid duration")
        starts.append(s.start_at)
    if starts != sorted(starts):
        raise ValueError("outline must be chronological")
