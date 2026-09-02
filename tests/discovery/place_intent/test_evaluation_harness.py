from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.discovery.place_intent.contract import (
    LLMIntentOutput,
    SearchModeId,
    materialize_llm_output,
)
from app.discovery.place_intent.evaluation import (
    EvaluationCategory,
    EvaluationSplit,
    evaluate_intent_runs,
)
from scripts.evaluate_place_intent import (
    IntentPredictionRecording,
    IntentPredictionRun,
    _corpus_digest,
    _live_prediction_runs,
    _select_cases,
    _write_json,
    load_cases,
    load_recording,
)

_CORPUS = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "place_intent"
    / "open_discovery_cases.json"
)


def _is_open(output: LLMIntentOutput) -> bool:
    return any(
        interpretation.search_directive.mode is SearchModeId.OPEN_DISCOVERY
        for interpretation in output.interpretations
    )


def test_open_discovery_corpus_freezes_categories_splits_and_grounding() -> None:
    cases = load_cases(_CORPUS)

    assert len(cases) == 50
    assert Counter(case.category for case in cases) == {
        EvaluationCategory.DELEGATED_OPEN: 10,
        EvaluationCategory.EXPLICIT_DIRECTED: 10,
        EvaluationCategory.MIXED_DELEGATION: 10,
        EvaluationCategory.AFFECTIVE_AMBIGUOUS: 10,
        EvaluationCategory.ROLE_SAFETY: 10,
    }
    assert Counter(case.split for case in cases) == {
        EvaluationSplit.CALIBRATION: 30,
        EvaluationSplit.HOLDOUT: 20,
    }
    assert sum(_is_open(case.expected) for case in cases) == 15
    probes = [case for case in cases if case.stability_probe]
    assert len(probes) == 10
    assert Counter(case.category for case in probes) == {
        EvaluationCategory.DELEGATED_OPEN: 2,
        EvaluationCategory.EXPLICIT_DIRECTED: 2,
        EvaluationCategory.MIXED_DELEGATION: 2,
        EvaluationCategory.AFFECTIVE_AMBIGUOUS: 2,
        EvaluationCategory.ROLE_SAFETY: 2,
    }
    assert all(case.split is EvaluationSplit.CALIBRATION for case in probes)
    assert all(case.recorded_output is None for case in cases)
    for case in cases:
        materialize_llm_output(case.utterance, case.expected)

    report = evaluate_intent_runs(
        cases,
        ({case.case_id: case.expected for case in cases},),
    )
    assert {category: result.case_count for category, result in report.category_means.items()} == {
        EvaluationCategory.DELEGATED_OPEN: 10,
        EvaluationCategory.EXPLICIT_DIRECTED: 10,
        EvaluationCategory.MIXED_DELEGATION: 10,
        EvaluationCategory.AFFECTIVE_AMBIGUOUS: 10,
        EvaluationCategory.ROLE_SAFETY: 10,
    }


def test_split_selection_keeps_holdout_separate() -> None:
    cases = load_cases(_CORPUS)

    calibration = _select_cases(cases, EvaluationSplit.CALIBRATION.value)
    holdout = _select_cases(cases, EvaluationSplit.HOLDOUT.value)

    assert len(calibration) == 30
    assert len(holdout) == 20
    assert {case.case_id for case in calibration}.isdisjoint(
        case.case_id for case in holdout
    )
    assert len(
        _select_cases(
            cases,
            EvaluationSplit.CALIBRATION.value,
            stability_probe=True,
        )
    ) == 10


class _RecordedProposer:
    def __init__(self, output: LLMIntentOutput) -> None:
        self.output = output
        self.utterances: list[str] = []

    async def propose(self, utterance: str) -> LLMIntentOutput:
        self.utterances.append(utterance)
        return self.output


@pytest.mark.asyncio
async def test_live_prediction_runs_repeat_every_selected_case() -> None:
    cases = load_cases(_CORPUS)[:2]
    proposer = _RecordedProposer(cases[0].expected)

    runs = await _live_prediction_runs(cases, proposer, repeat=3)

    assert len(runs) == 3
    assert all(set(run) == {case.case_id for case in cases} for run in runs)
    assert proposer.utterances == [case.utterance for _ in range(3) for case in cases]


def test_recording_round_trip_rejects_a_different_corpus(tmp_path: Path) -> None:
    cases = load_cases(_CORPUS)[:2]
    predictions = {case.case_id: case.expected for case in cases}
    recording = IntentPredictionRecording(
        schema_version="place-intent-predictions-v1",
        provider="gemini",
        model="gemini-3.1-flash-lite-preview",
        corpus_sha256=_corpus_digest(cases),
        created_at=datetime.now(UTC),
        runs=(IntentPredictionRun(repeat_index=1, predictions=predictions),),
    )
    path = tmp_path / "recording.json"
    _write_json(path, recording.model_dump_json(indent=2))

    loaded = load_recording(path, cases)

    assert loaded == recording
    relabeled = (cases[0].model_copy(update={"exact_command": True}), cases[1])
    assert _corpus_digest(relabeled) != recording.corpus_sha256
    with pytest.raises(ValueError, match="does not match"):
        load_recording(path, load_cases(_CORPUS)[1:3])
