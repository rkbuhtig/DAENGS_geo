from pathlib import Path

from app.discovery.place_intent.contract import LLMIntentOutput
from app.discovery.place_intent.evaluation import evaluate_intent_outputs
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
