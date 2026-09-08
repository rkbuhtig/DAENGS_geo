"""ID-only proposals cannot rewrite observations; real transport boundary is mocked."""

import json
from datetime import datetime

import httpx
import pytest

from scripts.spikes.diary_storyboard.candidates import catalog_for
from scripts.spikes.diary_storyboard.composition_experiment import execute, prepare
from scripts.spikes.diary_storyboard.contracts import Evidence
from scripts.spikes.diary_storyboard.editorial_contract import (
    resolve_plan,
    resolved_scopes,
    wire_contract,
)
from scripts.spikes.diary_storyboard.editorial_experiment import EditorialProvider
from scripts.spikes.diary_storyboard.runner import initialize, load, step
from scripts.spikes.diary_storyboard.selection_adapter import from_selection_case
from scripts.spikes.diary_storyboard.selection_demo import ARCHIVE
from scripts.spikes.diary_storyboard.storage import digest, read


def evidence_for(mode="grouped", case="actions"):
    source = next(c for c in read(ARCHIVE)["cases"] if c["id"] == case)
    return from_selection_case(
        source,
        started_at=datetime.fromisoformat("2026-09-07T09:00+09:00"),
        session_id=case,
        composition_mode=mode,
    )


def proposal_for(evidence):
    catalog = catalog_for(evidence)
    chosen = [c.id for c in catalog.candidates if c.required]
    if not chosen:
        chosen = [next(c.id for c in catalog.candidates if c.card_eligible)]
    scenes = [{"candidate_id": i, "focus": "fixture", "reason": "fixture"} for i in chosen]
    if catalog.composition_mode == "grouped":
        scenes = [
            {
                "primary_candidate_id": i,
                "included_candidate_ids": [i],
                "context_candidate_ids": [],
                "focus": "fixture",
                "reason": "fixture",
            }
            for i in chosen
        ]
    return {
        "understanding": {
            "summary": "fixture",
            "observed_flow": [],
            "interpretations": [],
            "open_questions": [],
        },
        "title_draft": None,
        "scenes": scenes,
        "omissions": [
            {"candidate_id": c.id, "code": "low_signal", "reason": "fixture"}
            for c in catalog.candidates
            if c.card_eligible and c.id not in chosen
        ],
    }


def resolve(raw, evidence):
    return resolve_plan(
        wire_contract(catalog_for(evidence).composition_mode).model_validate(raw), evidence
    )


@pytest.mark.parametrize("mode", ["individual", "grouped"])
def test_wire_has_no_source_fields_and_rejects_manual_time_or_other_mode(mode):
    schema = wire_contract(mode).model_json_schema()
    for forbidden in ("start_at", "end_at", "evidence_ids", "scene_id", "latitude", "longitude"):
        assert f'"{forbidden}"' not in json.dumps(schema)
    raw = proposal_for(evidence_for(mode))
    raw["scenes"][0]["start_at"] = "2026-09-07T09:00:00+09:00"
    with pytest.raises(ValueError):
        wire_contract(mode).model_validate(raw)
    other = "individual" if mode == "grouped" else "grouped"
    with pytest.raises(ValueError):
        wire_contract(mode).model_validate(proposal_for(evidence_for(other)))


def test_two_actions_share_scene_but_keep_point_times_and_unresolved_locations():
    evidence = evidence_for()
    before = evidence.model_dump(mode="json")
    raw = proposal_for(evidence)
    raw["scenes"] = [{**raw["scenes"][1], "included_candidate_ids": ["e04", "e07"]}]
    plan = resolve(raw, evidence)
    assert plan.outline[0].start_at == plan.outline[0].end_at
    scopes = resolved_scopes(plan, evidence)
    assert scopes[0]["included_extent"]["start_at"] != scopes[0]["included_extent"]["end_at"]
    assert all(r["start_at"] == r["end_at"] for r in scopes[0]["source_events"])
    assert all(r["location_status"] == "unresolved" for r in scopes[0]["source_events"])
    assert evidence.model_dump(mode="json") == before


def test_shared_context_is_derived_once_and_not_reported_as_omitted():
    evidence = evidence_for()
    raw = proposal_for(evidence)
    for scene in raw["scenes"]:
        scene["context_candidate_ids"] = ["e03"]
    raw["omissions"] = [o for o in raw["omissions"] if o["candidate_id"] != "e03"]
    plan = resolve(raw, evidence)
    context = next(d for d in plan.selection.decisions if d.candidate_id == "e03")
    assert context.code == "context" and len(context.context_scene_ids) == 2
    assert all(
        d.code == "connection"
        for d in plan.selection.decisions
        if d.candidate_id in {c.id for c in catalog_for(evidence).candidates if not c.card_eligible}
    )


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("unknown", "unknown event"),
        ("duplicate_owner", "duplicate event ownership"),
        ("missing_omission", "omissions must cover"),
        ("required_context", "required record"),
        ("budget", "budget omission"),
        ("unknown_claim", "unknown event"),
        ("omitted_title", "title must refer"),
        ("connection_card", "connection cannot"),
    ],
)
def test_rejects_invalid_choices_without_repair(mutation, match):
    evidence = evidence_for()
    raw = proposal_for(evidence)
    if mutation == "unknown":
        raw["scenes"][0]["included_candidate_ids"].append("missing")
    elif mutation == "duplicate_owner":
        raw["scenes"].append(raw["scenes"][0].copy())
    elif mutation == "missing_omission":
        raw["omissions"].pop()
    elif mutation == "required_context":
        raw["scenes"].pop(0)
        raw["scenes"][0]["context_candidate_ids"] = ["e04"]
    elif mutation == "budget":
        raw["omissions"][0]["code"] = "budget"
    elif mutation == "unknown_claim":
        raw["understanding"]["observed_flow"] = [{"text": "test", "candidate_ids": ["missing"]}]
    elif mutation == "omitted_title":
        raw["title_draft"] = {
            "text": "test",
            "candidate_ids": [raw["omissions"][0]["candidate_id"]],
        }
    elif mutation == "connection_card":
        raw["scenes"][0]["included_candidate_ids"].append("e00")
    with pytest.raises(ValueError, match=match):
        resolve(raw, evidence)


def test_rejects_cross_gap_group_and_keeps_chronology_system_owned():
    evidence = evidence_for(case="gap")
    raw = proposal_for(evidence)
    later = next(c.id for c in catalog_for(evidence).candidates if c.chain > 0 and c.card_eligible)
    raw["scenes"][0]["included_candidate_ids"].append(later)
    raw["omissions"] = [o for o in raw["omissions"] if o["candidate_id"] != later]
    with pytest.raises(ValueError, match="GPS"):
        resolve(raw, evidence)
    raw = proposal_for(evidence)
    raw["scenes"].reverse()
    plan = resolve(raw, evidence)
    assert plan.outline[0].start_at < plan.outline[1].start_at


def test_six_http_boundary_calls_preserve_wire_resolve_and_resume_without_calls(
    tmp_path, monkeypatch
):
    manifest = prepare(tmp_path, provider_type=EditorialProvider)
    assert manifest["version"] == "event-scene-planning-ab-v2"
    sent = []

    def respond(request):
        body = json.loads(request.content)
        payload = json.loads(body["contents"][0]["parts"][0]["text"])
        answer = proposal_for(Evidence.model_validate(payload["evidence_snapshot"]))
        sent.append(body)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]}}
                ],
                "usageMetadata": {"totalTokenCount": 10},
                "modelVersion": "fake",
            },
        )

    client = httpx.Client
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )
    result = execute(tmp_path, provider_type=EditorialProvider)
    assert result["accepted"] == 6 and len(sent) == 6
    assert execute(tmp_path, provider_type=EditorialProvider) == result
    assert len(sent) == 6
    for row, request in zip(result["rows"], sent, strict=True):
        run = tmp_path / row["id"]
        assert digest(request) == manifest["requests"][row["id"]]
        assert "scenes" in row["output"] and "outline" not in row["output"]
        assert row["resolved_output"] == read(run / "resolved_plan.json")
        assert read(run / "resolved_scene_scopes.json")
        assert load(run)[2].scenes == []
    source = tmp_path / "actions-grouped"
    replay = tmp_path / "exact-replay"
    config, evidence, state = load(source)
    initialize(replay, evidence.model_dump(mode="json"), config["model"])
    restored = step(replay, EditorialProvider(replay, config["model"], replay_from=source))
    assert restored == state and len(sent) == 6


@pytest.mark.parametrize(
    "run_id,message",
    [
        ("actions-grouped", "omissions must cover exactly unused eligible events"),
        ("actions-individual", "title must refer to selected scene events"),
        ("gap-grouped", "composition cannot join GPS chains"),
    ],
)
def test_recorded_model_failures_are_not_silently_accepted(run_id, message):
    root = ARCHIVE.parent.parent / "2026-09-08-event-scene-gemini-ab-v2" / run_id
    evidence = Evidence.model_validate(read(root / "evidence_snapshot.json"))
    response = read(root / "calls/000001/response.json")
    with pytest.raises(ValueError, match=message):
        resolve(response, evidence)
