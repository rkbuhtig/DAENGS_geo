"""State/provenance/decision regression tests; fake text is not a quality evaluation."""

import copy
from pathlib import Path

import pytest

from scripts.spikes.diary_storyboard.contracts import Edit
from scripts.spikes.diary_storyboard.runner import build, decide, initialize, review, step
from scripts.spikes.diary_storyboard.storage import latest, read, save

FIXTURE = Path(__file__).parents[3] / "scripts/spikes/diary_storyboard/fixtures/scenario.json"


def claim(text, source="p1"):
    return {"text": text, "evidence_ids": [source]}


def understanding(text):
    return {
        "summary": text,
        "observed_flow": [claim("냄새핀 기록")],
        "interpretations": [],
        "open_questions": ["머문 이유"],
    }


def scene(scene_id, text):
    return {
        "scene_id": scene_id,
        "title": scene_id,
        "text": text,
        "observed_facts": [claim("냄새핀 기록")],
        "interpretations": [],
        "open_questions": [],
        "connection_to_previous": "시간순 연결",
    }


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail_target = None
        self.unknown_reference = False

    def call(self, stage, payload, contract):
        self.calls.append((stage, copy.deepcopy(payload)))
        if stage == "understand":
            result = {
                "understanding": understanding("초기 이해"),
                "outline": [
                    {
                        "scene_id": "first",
                        "start_at": "2026-09-06T07:00:00+09:00",
                        "end_at": "2026-09-06T07:08:00+09:00",
                        "focus": "출발",
                        "evidence_ids": ["p1"],
                    },
                    {
                        "scene_id": "last",
                        "start_at": "2026-09-06T07:08:00+09:00",
                        "end_at": "2026-09-06T07:15:00+09:00",
                        "focus": "귀가",
                        "evidence_ids": ["p2"],
                    },
                ],
            }
        elif stage == "scene":
            target = payload["target_scene"]["scene_id"]
            if target == self.fail_target:
                self.fail_target = None
                raise ValueError("simulated transport failure")
            result = {
                "scene": scene(target, f"{target} 원문"),
                "understanding": understanding(f"{target} 이후 이해"),
                "change_reason": "현재 장면에서 연결 확인",
                "evidence_ids": ["p1"],
                "revisit_scene_ids": ["first"] if target == "last" else [],
            }
            if self.unknown_reference:
                result["scene"]["observed_facts"][0]["evidence_ids"] = ["invented-id"]
        elif stage == "reconcile":
            assert payload["board_before"]["revisit_scene_ids"] == ["first"]
            result = {
                "understanding": understanding("재검토한 이해"),
                "replacement_scenes": [scene("first", "돌아올 때와 연결해 수정한 첫 장면")],
                "change_reason": "뒤 장면과 첫 장면의 연결 반영",
                "evidence_ids": ["p2"],
                "findings": [
                    {"scene_ids": ["last"], "text": "머문 이유는 미확인", "evidence_ids": ["m4"]}
                ],
            }
        else:
            result = {
                "title": "일기",
                "text": "검토한 산책",
                "used_scene_ids": [s["scene_id"] for s in payload["reviewed_snapshot"]["scenes"]],
            }
        return contract.model_validate(result)


@pytest.fixture
def run(tmp_path):
    path = tmp_path / "run"
    initialize(path, read(FIXTURE), "fake-model")
    return path


def test_sequence_carries_updates_and_reconciles_without_diary(run):
    provider = FakeModel()
    state = build(run, provider)
    assert [s for s, _ in provider.calls] == ["understand", "scene", "scene", "reconcile"]
    second = provider.calls[2][1]["board_before"]
    assert second["understanding"]["summary"] == "first 이후 이해"
    assert second["scenes"][0]["text"] == "first 원문"
    assert state.status == "awaiting_review"
    assert state.scenes[0].text == "돌아올 때와 연결해 수정한 첫 장면"
    assert state.findings[0].text == "머문 이유는 미확인"
    assert read(run / "states/000001.json")["scenes"][0]["text"] == "first 원문"
    assert len(list((run / "states").glob("*.json"))) == 4
    assert not (run / "decisions").exists()


def test_failed_scene_resumes_without_repeating_completed_calls(run):
    provider = FakeModel()
    provider.fail_target = "last"
    with pytest.raises(ValueError, match="transport failure"):
        build(run, provider)
    assert latest(run).revision == 1
    failed_payload = provider.calls[-1][1]
    resumed = FakeModel()
    build(run, resumed)
    assert [stage for stage, _ in resumed.calls] == ["scene", "reconcile"]
    assert resumed.calls[0][1] == failed_payload


def test_invalid_evidence_reference_does_not_advance_checkpoint(run):
    provider = FakeModel()
    step(run, provider)
    provider.unknown_reference = True
    with pytest.raises(ValueError, match="unknown evidence"):
        step(run, provider)
    assert latest(run).revision == 0


def test_modified_source_snapshot_is_rejected(run):
    source = read(run / "evidence_snapshot.json")
    source["pieces"][0]["value"]["observed_path_m"] = 999
    save(run / "evidence_snapshot.json", source)
    with pytest.raises(ValueError, match="snapshot changed"):
        build(run, FakeModel())


def test_review_gate_skip_and_generation_are_separate_and_idempotent(run):
    model = FakeModel()
    state = build(run, model)
    with pytest.raises(ValueError, match="exact reviewed"):
        decide(run, state.revision, "generate", model)
    reviewed = review(run, state.revision, "simulated", "test", [])
    before = len(model.calls)
    assert decide(run, reviewed.revision, "skip")["diary_calls"] == 0
    assert len(model.calls) == before
    result = decide(run, reviewed.revision, "generate", model)
    assert decide(run, reviewed.revision, "generate", model) == result
    assert len(model.calls) == before + 1
    assert model.calls[-1][1]["reviewed_snapshot"]["review"]["actor"] == "simulated"


def test_user_edits_hidden_scenes_and_stale_revision(run):
    model = FakeModel()
    state = build(run, model)
    with pytest.raises(ValueError, match="stale"):
        review(run, state.revision - 1, "human", "tester", [])
    reviewed = review(
        run,
        state.revision,
        "simulated",
        "test",
        [
            Edit(scene_id="first", text="사용자가 정정한 내용"),
            Edit(scene_id="last", included=False, text="숨겨야 할 사용자 문구"),
        ],
    )
    decide(run, reviewed.revision, "generate", model)
    snapshot = model.calls[-1][1]["reviewed_snapshot"]
    assert len(snapshot["scenes"]) == 1
    assert snapshot["scenes"][0]["text"] == "사용자가 정정한 내용"
    assert "observed_facts" not in snapshot["scenes"][0]
    assert "understanding" not in snapshot
    assert "숨겨야 할 사용자 문구" not in str(snapshot)
    next_review = review(
        run,
        reviewed.revision,
        "simulated",
        "test",
        [
            Edit(scene_id="first", title="수정한 제목"),
        ],
    )
    assert next_review.review.edits[0].text == "사용자가 정정한 내용"
    assert next_review.review.edits[1] == reviewed.review.edits[1]
    with pytest.raises(ValueError, match="exact reviewed"):
        decide(run, reviewed.revision, "generate", model)


def test_scene_times_outside_session_are_rejected(run):
    class BadTime(FakeModel):
        def call(self, stage, payload, contract):
            result = super().call(stage, payload, contract)
            result.outline[0].start_at = result.outline[0].start_at.replace(hour=6)
            return result

    with pytest.raises(ValueError, match="outside session"):
        step(run, BadTime())
    assert latest(run) is None
