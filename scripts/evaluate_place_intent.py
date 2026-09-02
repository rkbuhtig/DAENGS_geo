"""녹화 fixture 또는 명시적 실API 호출로 Place intent proposer를 평가한다."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from app.core.config import settings
from app.discovery.place_intent.contract import IntentProposer, LLMIntentOutput
from app.discovery.place_intent.evaluation import (
    EvaluationSplit,
    IntentEvaluationCase,
    evaluate_intent_runs,
)
from app.discovery.place_intent.gemini import configured_gemini_intent_proposer
from app.discovery.place_intent.openai import configured_intent_proposer
from app.place.planning.contract import PlanningModel
from app.usage.gate import usage_request_scope
from app.usage.policy import DevUsageLimits

_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "place_intent"
    / "recorded_outputs.json"
)


class IntentPredictionRun(PlanningModel):
    repeat_index: int = Field(ge=1)
    predictions: dict[str, LLMIntentOutput]


class IntentPredictionRecording(PlanningModel):
    schema_version: Literal["place-intent-predictions-v1"]
    provider: Literal["gemini", "openai"]
    model: str = Field(min_length=1, max_length=120)
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    runs: tuple[IntentPredictionRun, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def repeat_indexes_are_unique(self) -> Self:
        indexes = [run.repeat_index for run in self.runs]
        if len(indexes) != len(set(indexes)):
            raise ValueError("recording repeat indexes must be unique")
        return self


def load_cases(path: Path) -> tuple[IntentEvaluationCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = tuple(TypeAdapter(list[IntentEvaluationCase]).validate_python(payload))
    ids = [case.case_id for case in cases]
    if not cases:
        raise ValueError("evaluation corpus cannot be empty")
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case ids must be unique")
    return cases


def _corpus_digest(cases: tuple[IntentEvaluationCase, ...]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "utterance": case.utterance,
            "expected": case.expected.model_dump(mode="json"),
            "split": case.split.value,
            "category": case.category.value,
            "stability_probe": case.stability_probe,
            "exact_command": case.exact_command,
            "paraphrase_group": case.paraphrase_group,
        }
        for case in cases
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _select_cases(
    cases: tuple[IntentEvaluationCase, ...],
    split: str,
    *,
    stability_probe: bool = False,
) -> tuple[IntentEvaluationCase, ...]:
    selected = cases
    if split != "all":
        selected = tuple(case for case in selected if case.split == EvaluationSplit(split))
    if stability_probe:
        selected = tuple(case for case in selected if case.stability_probe)
    if not selected:
        raise ValueError("evaluation selection has no cases")
    return selected


def _configured_provider(name: str) -> tuple[IntentProposer, str]:
    if name == "gemini":
        return configured_gemini_intent_proposer(), settings.gemini_model
    if name == "openai":
        return configured_intent_proposer(), settings.openai_model
    raise ValueError(f"unsupported evaluation provider: {name}")


async def _live_prediction_runs(
    cases: tuple[IntentEvaluationCase, ...],
    proposer: IntentProposer,
    *,
    repeat: int,
) -> tuple[dict[str, LLMIntentOutput], ...]:
    runs = []
    for _ in range(repeat):
        predictions = {}
        for case in cases:
            async with usage_request_scope():
                predictions[case.case_id] = await proposer.propose(case.utterance)
        runs.append(predictions)
    return tuple(runs)


def _validate_prediction_ids(
    cases: tuple[IntentEvaluationCase, ...],
    runs: tuple[dict[str, LLMIntentOutput], ...],
) -> None:
    expected_ids = {case.case_id for case in cases}
    for index, predictions in enumerate(runs, start=1):
        if set(predictions) != expected_ids:
            raise ValueError(f"prediction run {index} must contain every case id exactly once")


def load_recording(
    path: Path,
    cases: tuple[IntentEvaluationCase, ...],
) -> IntentPredictionRecording:
    recording = IntentPredictionRecording.model_validate_json(path.read_text(encoding="utf-8"))
    if recording.corpus_sha256 != _corpus_digest(cases):
        raise ValueError("prediction recording does not match the selected evaluation corpus")
    _validate_prediction_ids(cases, tuple(run.predictions for run in recording.runs))
    return recording


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload + "\n", encoding="utf-8")
    temporary.replace(path)


async def run(args: argparse.Namespace) -> int:
    if args.recording_out is not None and not args.live:
        raise ValueError("--recording-out requires --live")
    cases = _select_cases(
        load_cases(args.fixture),
        args.split,
        stability_probe=args.stability_probe,
    )
    requested_calls = len(cases) * args.repeat
    if args.live and settings.usage_policy == "dev":
        window_limit = DevUsageLimits().language_parse.window_units
        if requested_calls > window_limit:
            raise ValueError(
                f"live evaluation requests {requested_calls} calls but the dev Usage Gate "
                f"allows {window_limit} per window; select fewer cases or repetitions"
            )
    if args.live:
        proposer, model = _configured_provider(args.provider)
        prediction_runs = await _live_prediction_runs(
            cases,
            proposer,
            repeat=args.repeat,
        )
        if args.recording_out is not None:
            recording = IntentPredictionRecording(
                schema_version="place-intent-predictions-v1",
                provider=args.provider,
                model=model,
                corpus_sha256=_corpus_digest(cases),
                created_at=datetime.now(UTC),
                runs=tuple(
                    IntentPredictionRun(repeat_index=index, predictions=predictions)
                    for index, predictions in enumerate(prediction_runs, start=1)
                ),
            )
            _write_json(args.recording_out, recording.model_dump_json(indent=2))
    elif args.recording_in is not None:
        recording = load_recording(args.recording_in, cases)
        prediction_runs = tuple(run.predictions for run in recording.runs)
    else:
        missing = [case.case_id for case in cases if case.recorded_output is None]
        if missing:
            raise ValueError(
                "evaluation cases require --live or --recording-in; missing embedded outputs: "
                + ", ".join(missing)
            )
        prediction_runs = (
            {
                case.case_id: case.recorded_output
                for case in cases
                if case.recorded_output is not None
            },
        )
    _validate_prediction_ids(cases, prediction_runs)
    report_json = evaluate_intent_runs(cases, prediction_runs).model_dump_json(indent=2)
    if args.report_out is not None:
        _write_json(args.report_out, report_json)
    print(report_json)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--live",
        action="store_true",
        help="configured provider를 실제 호출한다 (명시하지 않으면 녹화 출력 평가)",
    )
    source.add_argument("--recording-in", type=Path, help="평가할 prediction recording JSON")
    parser.add_argument("--recording-out", type=Path, help="실호출 prediction recording 저장 경로")
    parser.add_argument("--report-out", type=Path, help="평가 report JSON 저장 경로")
    parser.add_argument("--provider", choices=("gemini", "openai"), default="gemini")
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=1)
    parser.add_argument(
        "--stability-probe",
        action="store_true",
        help="선택된 split에서 고정 stability probe case만 평가한다",
    )
    parser.add_argument(
        "--split",
        choices=("all", EvaluationSplit.CALIBRATION.value, EvaluationSplit.HOLDOUT.value),
        default="all",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
