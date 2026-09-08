"""Six bounded planning requests with identical evidence, no writing and no implicit retries."""

import pytest

from scripts.spikes.diary_storyboard import composition_experiment as experiment
from scripts.spikes.diary_storyboard.selection_demo import FixtureProvider
from scripts.spikes.diary_storyboard.storage import read


class FakePlanning(experiment.PlanningProvider):
    answer = FixtureProvider.answer
    call = FixtureProvider.call


def test_prepare_freezes_paired_evidence_settings_and_sends_nothing(tmp_path, monkeypatch):
    manifest = experiment.prepare(tmp_path)
    assert not list(tmp_path.glob("*/calls/*"))
    assert manifest["max_attempts"] == 6
    assert manifest["automatic_retries"] == 0
    for name in ("movement", "actions", "gap"):
        a = read(tmp_path / f"{name}-individual/evidence_snapshot.json")
        b = read(tmp_path / f"{name}-grouped/evidence_snapshot.json")
        a["context"]["candidate_catalog"].pop("composition_mode")
        b["context"]["candidate_catalog"].pop("composition_mode")
        assert a == b
    for path in tmp_path.glob("*/planned_request.json"):
        config = read(path)["generationConfig"]
        assert config["temperature"] == 0.2 and config["maxOutputTokens"] == 8192
    monkeypatch.setitem(experiment.SETTINGS, "temperature", 0.5)
    with pytest.raises(ValueError, match="changed"):
        experiment.prepare(tmp_path)


def test_execute_only_plans_and_resume_never_writes_or_repeats(tmp_path):
    first = experiment.execute(tmp_path, provider_type=FakePlanning)
    assert first["attempts"] == first["accepted"] == 6
    assert experiment.execute(tmp_path, provider_type=FakePlanning) == first
    for path in tmp_path.glob("*/states/*.json"):
        state = read(path)
        assert state["revision"] == 0 and state["scenes"] == []
    receipts = [read(p) for p in tmp_path.glob("*/calls/*/receipt.json")]
    assert len(receipts) == 6 and {r["stage"] for r in receipts} == {"select", "compose"}
    with pytest.raises(ValueError, match="planning only"):
        FakePlanning(tmp_path, "fake").request("scene", {}, None)


def test_rejected_outputs_are_preserved_and_not_retried(tmp_path):
    class Reject(FakePlanning):
        def answer(self, stage, payload):
            result = super().answer(stage, payload)
            result["selection"]["decisions"].pop()
            return result

    result = experiment.execute(tmp_path, provider_type=Reject)
    assert result["attempts"] == 6 and result["accepted"] == 0
    assert all(r["output"] is not None and r["error"] for r in result["rows"])
    assert all(r["proposed_scene_count"] > 0 and r["scene_count"] is None for r in result["rows"])
    assert not list(tmp_path.glob("*/states/*.json"))
    assert experiment.execute(tmp_path, provider_type=Reject) == result


def test_malformed_output_does_not_break_remaining_comparisons(tmp_path):
    class Malformed(FakePlanning):
        def answer(self, stage, payload):
            return {"not_a_plan": True}

    result = experiment.execute(tmp_path, provider_type=Malformed)
    assert result["attempts"] == 6 and result["accepted"] == 0
    assert all(r["proposed_scene_count"] is None for r in result["rows"])


def test_interrupted_attempt_is_not_silently_dispatched_again(tmp_path):
    manifest = experiment.prepare(tmp_path)
    abandoned = tmp_path / manifest["order"][0] / "calls/000001"
    abandoned.mkdir(parents=True)
    result = experiment.execute(tmp_path, provider_type=FakePlanning)
    assert result["attempts"] == 6 and result["accepted"] == 5
    assert result["rows"][0]["status"] == "interrupted_unknown"
    assert not (abandoned / "receipt.json").exists()
