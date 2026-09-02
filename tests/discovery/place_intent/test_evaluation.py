from pathlib import Path

from app.discovery.place_intent.contract import LLMIntentOutput
from app.discovery.place_intent.evaluation import (
    IntentEvaluationCase,
    evaluate_intent_outputs,
    evaluate_intent_runs,
)
from scripts.evaluate_place_intent import load_cases

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "place_intent"
    / "recorded_outputs.json"
)


def _prediction(payload: dict) -> LLMIntentOutput:
    return LLMIntentOutput.model_validate(payload)


def test_recorded_fixture_exercises_risk_metrics_with_perfect_baseline() -> None:
    cases = load_cases(_FIXTURE)
    predictions = {case.case_id: case.recorded_output for case in cases}

    report = evaluate_intent_outputs(cases, predictions)

    assert report.case_count == 13
    assert report.model_dump(exclude={"case_count"}) == {
        "disposition_accuracy": 1.0,
        "search_mode_accuracy": 1.0,
        "open_discovery_precision": None,
        "open_discovery_recall": None,
        "open_discovery_f1": None,
        "explicit_target_open_discovery_false_positive_rate": 0.0,
        "grounded_output_rate": 1.0,
        "open_discovery_grounding_rate": None,
        "product_outcome_accuracy": None,
        "information_delivery_precision": None,
        "information_delivery_recall": None,
        "inappropriate_search_rate": None,
        "intent_precision": 1.0,
        "intent_recall": 1.0,
        "evidence_span_accuracy": 1.0,
        "unsafe_positive_target_rate": 0.0,
        "exact_command_recall": 1.0,
        "unsupported_visibility": 1.0,
        "paraphrase_plan_equivalence": 1.0,
    }


def test_evaluator_separates_unsafe_target_evidence_and_visibility_failures() -> None:
    cases = load_cases(_FIXTURE)
    predictions = {case.case_id: case.recorded_output for case in cases}
    predictions["negated-hospital"] = _prediction(
        {
            "disposition": "proposed",
            "interpretations": [
                {
                    "proposals": [
                        {
                            "role": "required_target",
                            "intent": {"intent_type": "kind", "kind": "hospital"},
                            "evidence": {
                                "quote": "병원 갈 정도는 아니야",
                                "start": None,
                                "end": None,
                            },
                        }
                    ]
                }
            ],
            "reason": None,
        }
    )
    predictions["parking-required"] = _prediction(
        {
            "disposition": "abstained",
            "interpretations": [],
            "reason": "unsafe_to_guess",
        }
    )
    predictions["explicit-cafe-a"] = _prediction(
        {
            "disposition": "proposed",
            "interpretations": [
                {
                    "proposals": [
                        {
                            "role": "required_target",
                            "intent": {"intent_type": "kind", "kind": "cafe"},
                            "evidence": {
                                "quote": "사용자가 말하지 않은 근거",
                                "start": None,
                                "end": None,
                            },
                        }
                    ]
                }
            ],
            "reason": None,
        }
    )

    report = evaluate_intent_outputs(cases, predictions)

    assert report.unsafe_positive_target_rate > 0
    assert report.evidence_span_accuracy < 1
    assert report.unsupported_visibility < 1
    assert report.disposition_accuracy < 1


def _case(case_id: str, utterance: str, expected: dict) -> IntentEvaluationCase:
    return IntentEvaluationCase.model_validate(
        {
            "case_id": case_id,
            "utterance": utterance,
            "expected": expected,
        }
    )


def test_evaluator_separates_open_discovery_confusion_and_grounding() -> None:
    open_expected = {
        "disposition": "proposed",
        "interpretations": [
            {
                "search_directive": {
                    "mode": "open_discovery",
                    "evidence": {"quote": "네가 골라줘", "start": None, "end": None},
                },
                "proposals": [],
            }
        ],
        "reason": None,
    }
    direct_expected = {
        "disposition": "proposed",
        "interpretations": [
            {
                "proposals": [
                    {
                        "role": "required_target",
                        "intent": {"intent_type": "kind", "kind": "cafe"},
                        "evidence": {"quote": "카페", "start": None, "end": None},
                    }
                ]
            }
        ],
        "reason": None,
    }
    cases = (
        _case("delegated", "오늘은 네가 골라줘", open_expected),
        _case("protected", "카페는 네가 골라줘", direct_expected),
    )
    predictions = {
        "delegated": _prediction(
            {
                **open_expected,
                "interpretations": [
                    {
                        "search_directive": {
                            "mode": "open_discovery",
                            "evidence": {
                                "quote": "원문에 없는 위임",
                                "start": None,
                                "end": None,
                            },
                        },
                        "proposals": [],
                    }
                ],
            }
        ),
        "protected": _prediction(open_expected),
    }

    report = evaluate_intent_outputs(cases, predictions)

    assert report.search_mode_accuracy == 0.5
    assert report.open_discovery_precision == 0.5
    assert report.open_discovery_recall == 1.0
    assert report.explicit_target_open_discovery_false_positive_rate == 1.0
    assert report.open_discovery_grounding_rate == 0.5


def test_repeated_evaluation_reports_mode_and_semantic_stability() -> None:
    cases = load_cases(_FIXTURE)[:2]
    stable = {case.case_id: case.recorded_output for case in cases}
    changed = dict(stable)
    changed[cases[0].case_id] = _prediction(
        {
            "disposition": "proposed",
            "interpretations": [
                {
                    "search_directive": {
                        "mode": "open_discovery",
                        "evidence": {"quote": "찾아줘", "start": None, "end": None},
                    },
                    "proposals": [],
                }
            ],
            "reason": None,
        }
    )

    report = evaluate_intent_runs(cases, (stable, changed))

    assert report.repeat_count == 2
    assert report.search_mode_stability == 0.5
    assert report.semantic_output_stability == 0.5
    assert report.mean.search_mode_accuracy == 0.75
