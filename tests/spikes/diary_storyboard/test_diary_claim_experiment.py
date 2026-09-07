import copy
from types import SimpleNamespace

import pytest

from scripts.spikes.diary_storyboard.claim_experiment import (
    AuditItem,
    AuditProvider,
    ClaimAudit,
    inventory,
    normalize,
    validate_audit,
)
from scripts.spikes.diary_storyboard.contracts import Evidence, Scene, Understanding
from scripts.spikes.diary_storyboard.prompts import COMMON, STAGES
from scripts.spikes.diary_storyboard.provider import Provider


def test_normalization_preserves_source_and_other_pieces():
    source = {
        "schema_version": "diary-evidence-v1",
        "session_id": "test",
        "started_at": "2026-09-06T07:00:00+09:00",
        "ended_at": "2026-09-06T07:10:00+09:00",
        "context": {},
        "pieces": [
            {
                "id": "pin",
                "kind": "behavior_pin",
                "session_links": {},
                "value": {"type": "sniffing", "memo": "킁킁", "at": "07:03"},
                "meaning": "original",
                "provenance": {},
                "measurement_status": "synthetic",
            },
            {
                "id": "space",
                "kind": "past_spatial_tendency",
                "session_links": {},
                "value": {"appearance_ratio": 0.5},
                "meaning": "spatial",
                "provenance": {},
                "measurement_status": "computed",
            },
        ],
    }
    before = copy.deepcopy(source)
    result = normalize(source)
    assert source == before
    assert result["pieces"][1] == source["pieces"][1]
    assert result["pieces"][0]["value"] == {
        **source["pieces"][0]["value"],
        "normalized_observation": "냄새 맡기",
    }


def test_audit_covers_prose_understanding_questions_and_rejects_missing_or_unknown():
    understanding = Understanding(
        summary="summary", observed_flow=[], interpretations=[], open_questions=["question premise"]
    )
    scene = Scene(
        scene_id="s1",
        title="title",
        text="body",
        observed_facts=[],
        interpretations=[],
        open_questions=["scene question"],
        connection_to_previous="connection",
    )
    entries = inventory(SimpleNamespace(understanding=understanding, scenes=[scene]))
    assert {e["text"] for e in entries} == {
        "summary",
        "question premise",
        "title",
        "body",
        "scene question",
        "connection",
    }
    evidence = Evidence(
        session_id="s",
        started_at="2026-09-06T07:00:00+09:00",
        ended_at="2026-09-06T07:01:00+09:00",
        context={},
        pieces=[
            {
                "id": "raw",
                "kind": "test",
                "session_links": {},
                "value": {},
                "meaning": "test",
                "provenance": {},
                "measurement_status": "test",
            }
        ],
    )
    items = [
        AuditItem(
            target_id=e["target_id"],
            judgment="unsupported",
            supported_content="",
            additional_assumptions="assumption",
            evidence_ids=["raw"],
            action="rephrase",
            reason="reason",
            affected_target_ids=[],
        )
        for e in entries
    ]
    validate_audit(ClaimAudit(items=items), entries, evidence)
    with pytest.raises(ValueError, match="exactly once"):
        validate_audit(ClaimAudit(items=items[:-1]), entries, evidence)
    with pytest.raises(ValueError, match="unknown affected"):
        validate_audit(
            ClaimAudit(
                items=[items[0].model_copy(update={"affected_target_ids": ["unknown"]})] + items[1:]
            ),
            entries,
            evidence,
        )


def test_experimental_instructions_leave_existing_requests_unchanged(tmp_path):
    before = copy.deepcopy(STAGES)
    baseline = Provider(tmp_path, "model")
    audited = AuditProvider(tmp_path, "model")
    assert baseline.instruction("reconcile") == COMMON + "\n" + STAGES["reconcile"]
    assert audited.instruction("reconcile") != baseline.instruction("reconcile")
    assert STAGES == before
