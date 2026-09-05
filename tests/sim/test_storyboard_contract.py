import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.spikes.walk_record_lab.core import prepare
from scripts.spikes.walk_record_lab.export_app_fixtures import fixture_experiments
from scripts.spikes.walk_record_lab.selection import select
from scripts.spikes.walk_record_lab.storyboard_contract import StoryboardBundle, export_storyboard

FIXTURES = Path(__file__).parents[1] / "fixtures/storyboard"


@pytest.mark.parametrize("name", ["pinless", "clustered", "gap", "movement", "updated"])
def test_portable_fixtures_match_recomputed_scene_identity(name):
    expected = StoryboardBundle.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    exp = dict(fixture_experiments())[name]
    artifacts, entries = prepare(exp)
    selection = select(artifacts, entries, exp.selection, [])
    actual = export_storyboard(artifacts, entries, selection, {})
    assert [s.id for s in actual.scenes] == [s.id for s in expected.scenes]
    assert [s.reasons for s in actual.scenes] == [s.reasons for s in expected.scenes]
    assert actual.synthetic
    if name == "pinless":
        assert not any(f.kind == "action" for s in expected.scenes for f in s.facts)
        assert any(f.kind == "environment" for s in expected.scenes for f in s.facts)
    if name == "gap":
        gap = next(s for s in expected.scenes if "observation_gap" in s.reasons)
        assert gap.route is None and gap.ended_at > gap.started_at
    if name == "movement":
        assert any("session_speed" in s.reasons for s in expected.scenes)


def test_correction_keeps_identity_but_changes_revision_and_removes_deleted_pin():
    before, after = [StoryboardBundle.model_validate_json((FIXTURES / f"{n}.json").read_text(encoding="utf-8"))
                     for n in ("clustered", "updated")]
    old = next(s for s in before.scenes if "note" in s.reasons)
    new = next(s for s in after.scenes if "note" in s.reasons)
    assert before.session_id == after.session_id
    assert old.id == new.id and old.revision != new.revision
    bark = next(s for s in before.scenes if s.title == "짖기")
    assert bark.id not in {s.id for s in after.scenes}


@pytest.mark.parametrize("fault", ["duplicate", "reference", "order", "range", "version"])
def test_rejects_invalid_contract(fault):
    data = json.loads((FIXTURES / "pinless.json").read_text(encoding="utf-8"))
    if fault == "duplicate":
        data["scenes"][1]["id"] = data["scenes"][0]["id"]
    elif fault == "reference":
        data["scenes"][0]["facts"][0]["source_ids"] = ["missing"]
    elif fault == "order":
        data["scenes"].reverse()
    elif fault == "range":
        data["scenes"][1]["route"]["end_m"] = -1
    else:
        data["format"] = "v2"
    with pytest.raises(ValidationError):
        StoryboardBundle.model_validate(data)


def test_checked_in_schema_matches_model():
    path = Path(__file__).parents[2] / "docs/contracts/walk-storyboard-candidates-v1.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == StoryboardBundle.model_json_schema()


def test_unlocated_note_does_not_acquire_a_route_position():
    exp = dict(fixture_experiments())["gap"]
    from scripts.spikes.walk_record_lab.core import Experiment
    exp = Experiment(scenario=exp.scenario, taps=[{"id": "memo", "code": "note", "at_s": 500,
                                                  "note": "위치 없는 메모"}])
    artifacts, entries = prepare(exp)
    result = export_storyboard(artifacts, entries, select(artifacts, entries, exp.selection, []), {})
    assert next(s for s in result.scenes if "note" in s.reasons).route is None


def test_live_builder_accepts_observations_without_a_scenario_or_truth():
    from datetime import UTC, datetime, timedelta

    from app.features.storyboard.scenes import build_storyboard

    start = datetime(2026, 9, 5, tzinfo=UTC)
    result = build_storyboard("real-session", start, start+timedelta(minutes=1), 0,
        [{"id": "memo", "revision": 1, "accepted": True, "kind": "note", "label": "특별한 순간",
          "note": "위치 없는 기록", "elapsed_s": 20, "accepted_distance_m": 0,
          "location": None}], {"anchors": []}, {})
    assert result.synthetic is False
    assert [s.id for s in result.scenes] == ["start", "entry:memo", "end"]
    assert result.scenes[1].route is None


def test_v2_fixtures_and_schema_match_generator():
    from app.features.storyboard.scenes import StoryboardBundleV2
    from scripts.spikes.walk_record_lab.export_evidence_fixtures import bundles
    for name, bundle in bundles().items():
        stored = StoryboardBundleV2.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        assert bundle == stored
    path = Path(__file__).parents[2] / "docs/contracts/walk-storyboard-candidates-v2.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == StoryboardBundleV2.model_json_schema()


def test_v2_attribution_shortfall_and_budget_survive_legacy_conversion():
    from app.features.storyboard.scenes import legacy_bundle
    from scripts.spikes.walk_record_lab.export_evidence_fixtures import bundles
    values = bundles()
    a, b = [next(s for s in values[n].scenes if s.entry) for n in ("v2-before", "v2-after")]
    assert a.id == b.id and a.revision != b.revision
    assert (a.entry.pet_id, b.entry.pet_id, b.entry.revision) == ("pet-a", "pet-b", 2)
    short = values["v2-short"]
    assert not short.selection.minimum_met and short.selection.shortfall_reason
    budget = values["v2-budget"]
    assert budget.selection.selected_count == 8 and budget.selection.deferred_action_count == 1
    assert not budget.selection.coverage_met
    assert len([s for s in budget.scenes if s.entry]) == 9
    for value in values.values():
        old = legacy_bundle(value)
        assert old.format.endswith("v1")
        assert old.scenes[-1].facts == value.scenes[-1].facts


@pytest.mark.parametrize("fault", ["revision", "minimum", "missing_reason", "negative_distance"])
def test_v2_rejects_inconsistent_evidence(fault):
    from app.features.storyboard.scenes import StoryboardBundleV2
    from scripts.spikes.walk_record_lab.export_evidence_fixtures import bundles
    data = bundles()["v2-before"].model_dump(mode="json")
    if fault == "revision":
        next(s for s in data["scenes"] if s["entry"])["entry"]["revision"] = 0
    elif fault == "minimum":
        data["selection"]["minimum_met"] = False
    elif fault == "missing_reason":
        data["selection"].update(selected_count=0, minimum_met=False, shortfall_reason=None)
    else:
        data["selection"]["longest_unread_m"] = -1
    with pytest.raises(ValidationError):
        StoryboardBundleV2.model_validate(data)
