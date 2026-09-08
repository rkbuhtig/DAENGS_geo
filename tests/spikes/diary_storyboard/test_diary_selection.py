"""Candidate identity, point events, empty boards and durable resume; no live model."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from scripts.spikes.diary_storyboard.candidates import (
    CATALOG_KEY,
    catalog_for,
    check_selection,
)
from scripts.spikes.diary_storyboard.contracts import Edit, SelectionPlan
from scripts.spikes.diary_storyboard.runner import (
    build,
    decide,
    initialize,
    load,
    review,
    step,
)
from scripts.spikes.diary_storyboard.selection_adapter import from_selection_case
from scripts.spikes.diary_storyboard.selection_demo import ARCHIVE, FixtureProvider
from scripts.spikes.diary_storyboard.storage import latest, read, save
from scripts.spikes.diary_storyboard.verify_run import verify

START = datetime.fromisoformat("2026-09-07T09:00:00+09:00")


def evidence_for(name="actions"):
    case = next(c for c in read(ARCHIVE)["cases"] if c["id"] == name)
    return from_selection_case(case, started_at=START, session_id=f"synthetic-{name}")


def setup_run(tmp_path, evidence=None):
    run = tmp_path / "run"
    provider = FixtureProvider(run)
    evidence = evidence or evidence_for()
    initialize(run, evidence.model_dump(mode="json"), provider.model)
    return run, provider, evidence


def plan_for(provider, evidence):
    return SelectionPlan.model_validate(provider.answer(
        "select", {"evidence_snapshot": evidence.model_dump(mode="json")}
    ))


@pytest.mark.parametrize("name,counts", [
    ("movement", (0, 7, 4)), ("actions", (2, 7, 6)), ("gap", (2, 8, 8)),
])
def test_archived_inputs_preserve_roles_sources_and_point_pins(name, counts):
    case = next(c for c in read(ARCHIVE)["cases"] if c["id"] == name)
    original = deepcopy(case)
    evidence = evidence_for(name)
    catalog = catalog_for(evidence)
    assert tuple(sum(c.role == r for c in catalog.candidates)
                 for r in ("action", "transition", "connection")) == counts
    assert all(c.source_input_sha256 == case["input_sha256"] for c in catalog.candidates)
    assert all(c.location_status == "unresolved" for c in catalog.candidates)
    actions = [c for c in catalog.candidates if c.role == "action"]
    assert [c.start_at for c in actions] == ([START + timedelta(seconds=s) for s in (600, 900)]
                                           if name != "movement" else [])
    assert all(c.start_at == c.end_at and c.time_kind == "point" for c in actions)
    assert case == original
    case["output"] = {"title": "MODEL OUTPUT MUST NOT BECOME EVIDENCE"}
    case["editorial_review"] = {"text": "REVIEW MUST NOT BECOME EVIDENCE"}
    assert from_selection_case(case, started_at=START, session_id=f"synthetic-{name}") == evidence


def test_modified_archive_hash_and_naive_synthetic_time_are_rejected():
    case = deepcopy(read(ARCHIVE)["cases"][0])
    case["input"]["events"][0]["why_keep"] = "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        from_selection_case(case, started_at=START, session_id="test")
    with pytest.raises(ValueError, match="timezone-aware"):
        from_selection_case(read(ARCHIVE)["cases"][0], started_at=START.replace(tzinfo=None),
                            session_id="test")


@pytest.mark.parametrize("mutation,expected", [
    ("inventory", "every candidate"),
    ("point", "preserve candidate"),
    ("primary", "primary evidence"),
    ("foreign", "another candidate"),
    ("budget", "capacity remains"),
    ("required", "is required"),
    ("order", "chronological"),
])
def test_invalid_selection_never_becomes_completed_state(tmp_path, mutation, expected):
    run, provider, evidence = setup_run(tmp_path)
    plan = plan_for(provider, evidence)
    catalog = catalog_for(evidence)
    candidate_by_id = {c.id: c for c in catalog.candidates}
    if mutation == "inventory":
        plan.selection.decisions.pop()
    elif mutation == "point":
        point = next(d for d in plan.selection.decisions
                     if candidate_by_id[d.candidate_id].role == "action")
        next(s for s in plan.outline if s.scene_id == point.scene_id).end_at += timedelta(seconds=1)
    elif mutation == "primary":
        plan.outline[0].evidence_ids = ["who:guardian"]
    elif mutation == "foreign":
        plan.outline[0].evidence_ids += [plan.outline[-1].evidence_ids[0]]
    elif mutation in ("budget", "required"):
        decision = next(d for d in plan.selection.decisions if d.code == "selected" and
                        candidate_by_id[d.candidate_id].required == (mutation == "required"))
        plan.outline = [s for s in plan.outline if s.scene_id != decision.scene_id]
        decision.scene_id = None
        decision.code = "budget" if mutation == "budget" else "low_signal"
    elif mutation == "order":
        plan.outline.reverse()

    class InvalidProvider(FixtureProvider):
        def answer(self, stage, payload):
            return plan.model_dump(mode="json")

    with pytest.raises(ValueError, match=expected):
        step(run, InvalidProvider(run))
    assert latest(run) is None
    assert read(run / "calls/000001/receipt.json")["validation"] == "rejected"
    assert read(run / "stage_errors/000001.json")["last_completed_revision"] is None


def test_gap_crossing_and_ineligible_connection_rejected(tmp_path):
    evidence = evidence_for("gap")
    catalog = catalog_for(evidence)
    gap = catalog.gaps[0]
    candidate = next(c for c in catalog.candidates if c.role == "transition")
    candidate.start_at = gap.start_at - timedelta(seconds=1)
    candidate.end_at = gap.end_at + timedelta(seconds=1)
    evidence.context[CATALOG_KEY] = catalog.model_dump(mode="json")
    with pytest.raises(ValueError, match="crosses GPS gap"):
        setup_run(tmp_path, evidence)
    assert not (tmp_path / "run/config.json").exists()
    evidence = evidence_for()
    evidence.context[CATALOG_KEY]["candidates"][0]["card_eligible"] = True
    with pytest.raises(ValueError, match="connection cannot"):
        catalog_for(evidence)


def test_selected_connection_is_rejected(tmp_path):
    _, provider, evidence = setup_run(tmp_path)
    plan = plan_for(provider, evidence)
    decision = next(d for d in plan.selection.decisions if d.code == "connection")
    selected = next(d for d in plan.selection.decisions if d.code == "selected")
    decision.code, decision.scene_id = "selected", selected.scene_id
    selected.code, selected.scene_id = "low_signal", None
    with pytest.raises(ValueError, match="connection cannot be selected"):
        check_selection(plan, evidence)


def test_empty_board_is_complete_without_scene_or_reconcile_call(tmp_path):
    evidence = evidence_for("movement")
    catalog = catalog_for(evidence)
    candidate = catalog.candidates[0]
    candidate.time_kind, candidate.end_at = "interval", START + timedelta(minutes=12)
    catalog.candidates = [candidate]
    evidence.context[CATALOG_KEY] = catalog.model_dump(mode="json")
    run, provider, _ = setup_run(tmp_path, evidence)
    state = build(run, provider)
    assert state.status == "awaiting_review" and not state.outline and not state.scenes
    assert len(list((run / "calls").iterdir())) == 1
    assert build(run, provider) == state
    reviewed = review(run, state.revision, "simulated", "test", [])
    assert decide(run, reviewed.revision, "skip")["diary_calls"] == 0
    with pytest.raises(ValueError, match="no included scenes"):
        decide(run, reviewed.revision, "generate", provider)
    report = verify(run)
    assert report["fixture_calls"] == 1 and report["model_calls"] == 0


def test_failed_scene_resume_keeps_selection_pins_and_user_edits(tmp_path):
    run, provider, _ = setup_run(tmp_path)
    selected = step(run, provider)
    step(run, provider)

    class FailingProvider(FixtureProvider):
        def answer(self, stage, payload):
            raise ValueError("simulated transport failure")

    with pytest.raises(ValueError, match="transport failure"):
        step(run, FailingProvider(run))
    assert latest(run).revision == 1
    failed = read(run / "calls/000003/request.json")
    state = build(run, FixtureProvider(run))
    assert read(run / "calls/000004/request.json") == failed
    assert state.selection == selected.selection
    assert state.status == "awaiting_review"
    assert sum(o.start_at == o.end_at for o in state.outline) == 2
    count = len(list((run / "calls").iterdir()))
    assert build(run, FixtureProvider(run)) == state
    assert len(list((run / "calls").iterdir())) == count
    report = verify(run)
    assert report["model_calls"] == 0 and report["fixture_calls"] == count
    reviewed = review(run, state.revision, "simulated", "test",
                      [Edit(scene_id=state.scenes[0].scene_id, text="사용자 편집")])
    assert build(run, FixtureProvider(run)) == reviewed
    assert reviewed.selection == selected.selection


def test_snapshot_and_selection_schema_change_prevent_resume(tmp_path):
    run, provider, _ = setup_run(tmp_path)
    step(run, provider)
    config = read(run / "config.json")
    config["selection_schema_sha256"] = "modified"
    save(run / "config.json", config)
    with pytest.raises(ValueError, match="schema changed"):
        load(run)


def test_structural_pass_does_not_certify_invented_behavior(tmp_path):
    run, provider, _ = setup_run(tmp_path)
    step(run, provider)

    class UnsupportedText(FixtureProvider):
        def answer(self, stage, payload):
            answer = super().answer(stage, payload)
            answer["scene"]["text"] = "두부가 신나게 멈춰 쉬었다"
            return answer

    state = step(run, UnsupportedText(run))
    assert "신나게" in state.scenes[0].text
    # This first skeleton checks references, not the entailment of every text claim.
    assert state.status == "filling"
