"""Editorial groups preserve individual event scopes; fixtures do not evaluate LLM quality."""

from datetime import datetime, timedelta

import pytest

from scripts.spikes.diary_storyboard.candidates import CATALOG_KEY, catalog_for, check_selection
from scripts.spikes.diary_storyboard.composition import scene_context
from scripts.spikes.diary_storyboard.contracts import Edit, SelectionPlan
from scripts.spikes.diary_storyboard.provider import Provider
from scripts.spikes.diary_storyboard.runner import (
    build,
    decide,
    initialize,
    load,
    review,
    reviewed_snapshot,
    step,
)
from scripts.spikes.diary_storyboard.selection_adapter import from_selection_case
from scripts.spikes.diary_storyboard.selection_demo import ARCHIVE, FixtureProvider
from scripts.spikes.diary_storyboard.storage import latest, read
from scripts.spikes.diary_storyboard.verify_run import verify

START = datetime.fromisoformat("2026-09-07T09:00:00+09:00")


def test_empty_grouped_board_uses_one_call_and_shared_context_is_not_double_owned(tmp_path):
    _, _, evidence = setup(tmp_path, "movement")
    catalog = catalog_for(evidence)
    catalog.candidates = [c for c in catalog.candidates if c.role == "connection"]
    evidence.context[CATALOG_KEY] = catalog.model_dump(mode="json")
    run = tmp_path / "empty"
    provider = FixtureProvider(run)
    initialize(run, evidence.model_dump(mode="json"), provider.model)
    state = build(run, provider)
    assert not state.scenes and not state.outline and not state.selection.compositions
    assert state.status == "awaiting_review"
    assert verify(run)["fixture_calls"] == 1

    _, provider, evidence = setup(tmp_path / "shared")
    plan = proposed(provider, evidence)
    check_selection(plan, evidence)
    shared = [d for d in plan.selection.decisions if len(d.context_scene_ids) > 1]
    assert shared and all(d.code == "context" and d.scene_id is None for d in shared)
    owned = [i for g in plan.selection.compositions for i in g.included_candidate_ids]
    assert len(owned) == len(set(owned))


def setup(tmp_path, name="actions"):
    archived = next(c for c in read(ARCHIVE)["cases"] if c["id"] == name)
    evidence = from_selection_case(
        archived, started_at=START, session_id=name, composition_mode="grouped"
    )
    run = tmp_path / "grouped"
    provider = FixtureProvider(run)
    initialize(run, evidence.model_dump(mode="json"), provider.model)
    return run, provider, evidence


def proposed(provider, evidence):
    return SelectionPlan.model_validate(
        provider.answer("compose", {"evidence_snapshot": evidence.model_dump(mode="json")})
    )


@pytest.mark.parametrize("name", ["movement", "actions", "gap"])
def test_grouped_pipeline_keeps_events_and_exposes_prewrite_composition(tmp_path, name):
    run, provider, evidence = setup(tmp_path, name)
    original = evidence.model_dump(mode="json")
    payload = {"evidence_snapshot": original}
    baseline = SelectionPlan.model_validate(provider.answer("select", payload))
    selected = step(run, provider)
    baseline_ids = {d.candidate_id for d in baseline.selection.decisions if d.code == "selected"}
    used = {
        d.candidate_id for d in selected.selection.decisions if d.code in ("selected", "context")
    }
    assert used == baseline_ids
    assert 0 < len(selected.outline) < len(baseline.outline)
    assert not selected.scenes and "원본 사건의 범위" in (run / "storyboard.md").read_text("utf-8")
    catalog = catalog_for(evidence)
    for group in selected.selection.compositions:
        records = scene_context(selected, group.scene_id, evidence)["events"]
        assert len({r["chain"] for r in records}) == 1
        for record in records:
            event = next(c for c in catalog.candidates if c.id == record["candidate_id"])
            assert record["start_at"] == event.start_at.isoformat()
            assert record["end_at"] == event.end_at.isoformat()
            assert record["location_status"] == "unresolved"
    state = build(run, provider)
    assert state.status == "awaiting_review" and state.selection == selected.selection
    assert read(run / "evidence_snapshot.json") == original
    assert verify(run)["model_calls"] == 0


def test_two_required_actions_share_one_card_without_combining_action_times(tmp_path):
    run, provider, evidence = setup(tmp_path)
    catalog = catalog_for(evidence)
    catalog.candidates = [c for c in catalog.candidates if c.role == "action"]
    catalog.max_scenes = 1
    evidence.context[CATALOG_KEY] = catalog.model_dump(mode="json")
    run = tmp_path / "two-actions"
    provider = FixtureProvider(run)
    initialize(run, evidence.model_dump(mode="json"), provider.model)
    state = build(run, provider)
    assert len(state.outline) == 1
    representative = state.outline[0]
    assert representative.start_at == representative.end_at == START + timedelta(minutes=10)
    records = scene_context(state, representative.scene_id, evidence)["events"]
    assert [r["start_at"] for r in records] == [c.start_at.isoformat() for c in catalog.candidates]
    assert all(r["start_at"] == r["end_at"] for r in records)
    assert len(state.scenes[0].observed_facts) == 2
    assert all(c.primary_evidence_id in representative.evidence_ids for c in catalog.candidates)


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("unknown", "unknown event"),
        ("duplicate", "duplicate or unknown"),
        ("representative", "representative event must be included"),
        ("time_union", "representative event bounds"),
        ("context_inventory", "context decisions disagree"),
        ("required_context", "required record must be included"),
        ("double_owner", "included in two scenes"),
        ("foreign_evidence", "outside its events"),
        ("budget", "capacity remains"),
    ],
)
def test_invalid_group_never_becomes_checkpoint(tmp_path, mutation, message):
    run, provider, evidence = setup(tmp_path)
    plan = proposed(provider, evidence)
    group = plan.selection.compositions[0]
    if mutation == "unknown":
        group.context_candidate_ids.append("missing")
    elif mutation == "duplicate":
        group.context_candidate_ids.append(group.included_candidate_ids[0])
    elif mutation == "representative":
        group.primary_candidate_id = group.context_candidate_ids[0]
    elif mutation == "time_union":
        plan.outline[0].end_at += timedelta(minutes=24)
    elif mutation == "context_inventory":
        decision = next(d for d in plan.selection.decisions if d.context_scene_ids)
        decision.context_scene_ids = []
    elif mutation == "required_context":
        action_id = group.primary_candidate_id
        transition_id = group.context_candidate_ids.pop(0)
        group.included_candidate_ids = [transition_id]
        group.primary_candidate_id = transition_id
        group.context_candidate_ids.append(action_id)
        event = next(c for c in catalog_for(evidence).candidates if c.id == transition_id)
        plan.outline[0].start_at, plan.outline[0].end_at = event.start_at, event.end_at
        plan.outline[0].evidence_ids = [event.primary_evidence_id]
        for d in plan.selection.decisions:
            if d.candidate_id == action_id:
                d.code, d.scene_id, d.context_scene_ids = "context", None, [group.scene_id]
            if d.candidate_id == transition_id:
                d.code, d.scene_id, d.context_scene_ids = "selected", group.scene_id, []
    elif mutation == "double_owner":
        plan.selection.compositions[1].included_candidate_ids.append(
            group.included_candidate_ids[0]
        )
    elif mutation == "foreign_evidence":
        plan.outline[0].evidence_ids.append(plan.outline[-1].evidence_ids[0])
    elif mutation == "budget":
        next(d for d in plan.selection.decisions if d.code == "low_signal").code = "budget"

    class Invalid(FixtureProvider):
        def answer(self, stage, payload):
            return plan.model_dump(mode="json")

    with pytest.raises(ValueError, match=message):
        step(run, Invalid(run))
    assert latest(run) is None
    assert read(run / "calls/000001/receipt.json")["validation"] == "rejected"


@pytest.mark.parametrize("same_chain", [False, True])
def test_cross_gap_context_rejected_even_when_chain_label_is_equal(tmp_path, same_chain):
    _, provider, evidence = setup(tmp_path, "gap")
    if same_chain:
        evidence.context[CATALOG_KEY]["candidates"][10]["chain"] = 0
    plan = proposed(provider, evidence)
    plan.selection.compositions[0].context_candidate_ids.append("e10")
    with pytest.raises(ValueError, match="GPS gap|GPS chains"):
        check_selection(plan, evidence)


def test_resume_replay_and_review_keep_composition_and_source_events(tmp_path):
    run, provider, evidence = setup(tmp_path)
    selected = step(run, provider)

    class Failure(FixtureProvider):
        def answer(self, stage, payload):
            raise ValueError("interrupted grouped writing")

    with pytest.raises(ValueError, match="interrupted grouped"):
        step(run, Failure(run))
    assert latest(run) == selected
    state = build(run, provider)
    assert read(run / "calls/000002/request.json") == read(run / "calls/000003/request.json")
    replay = tmp_path / "replay"
    initialize(replay, evidence.model_dump(mode="json"), provider.model)
    assert build(replay, Provider(replay, provider.model, replay_from=run)) == state
    assert verify(run, replay)["replay_matches_current_state_and_decisions"]
    edited = review(
        run,
        state.revision,
        "simulated",
        "test",
        [
            Edit(scene_id=state.scenes[0].scene_id, text="편집한 본문"),
            Edit(scene_id=state.scenes[-1].scene_id, included=False),
        ],
    )
    snapshot = reviewed_snapshot(edited, evidence)
    assert snapshot["scenes"][0]["text"] == "편집한 본문"
    assert "observed_facts" not in snapshot["scenes"][0]
    assert snapshot["scenes"][0]["scene_context"] == scene_context(
        edited, edited.scenes[0].scene_id, evidence
    )
    assert len(snapshot["scenes"]) == len(state.scenes) - 1
    assert decide(run, edited.revision, "skip")["diary_calls"] == 0
    assert load(run)[2].selection == selected.selection


def test_writer_cannot_drop_an_included_action_or_use_outside_evidence(tmp_path):
    run, provider, _evidence = setup(tmp_path)
    selected = step(run, provider)

    class Drops(FixtureProvider):
        def answer(self, stage, payload):
            answer = super().answer(stage, payload)
            answer["scene"]["observed_facts"] = []
            return answer

    with pytest.raises(ValueError, match="retain every included"):
        step(run, Drops(run))
    assert latest(run) == selected

    class Foreign(FixtureProvider):
        def answer(self, stage, payload):
            answer = super().answer(stage, payload)
            answer["scene"]["observed_facts"][0]["evidence_ids"].append("e13:what0")
            return answer

    with pytest.raises(ValueError, match="outside composition"):
        step(run, Foreign(run))
    assert latest(run) == selected
