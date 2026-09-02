"""녹화 fixture 또는 명시적 실API 호출로 Place intent proposer를 평가한다."""

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from app.core.config import settings
from app.discovery.place_intent.contract import IntentProposer, LLMIntentOutput
from app.discovery.place_intent.evaluation import (
    EvaluationSplit,
    IntentEvaluationCase,
    ProductOutcomeId,
    evaluate_intent_runs,
)
from app.discovery.place_intent.gemini import (
    GEMINI_GENERATION_CONFIG,
    configured_gemini_intent_proposer,
)
from app.discovery.place_intent.openai import (
    OPENAI_GENERATION_CONFIG,
    configured_intent_proposer,
)
from app.discovery.place_intent.prompt import (
    gemini_output_schema,
    proposer_instructions,
    strict_output_schema,
)
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
    schema_version: Literal["place-intent-predictions-v2"]
    provider: Literal["gemini", "openai"]
    model: str = Field(min_length=1, max_length=120)
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_config: dict[str, int | float | str | bool | None]
    requested_repeat: int = Field(ge=1, le=10)
    created_at: datetime
    updated_at: datetime
    complete: bool
    runs: tuple[IntentPredictionRun, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def runs_match_requested_repetitions(self) -> Self:
        indexes = [run.repeat_index for run in self.runs]
        if indexes != list(range(1, self.requested_repeat + 1)):
            raise ValueError("recording runs must cover requested repetitions in order")
        if self.updated_at < self.created_at:
            raise ValueError("recording update time cannot precede creation time")
        return self


class _ProviderProvenance(PlanningModel):
    prompt_sha256: str
    output_schema_sha256: str
    generation_config: dict[str, int | float | str | bool | None]


def load_cases(path: Path) -> tuple[IntentEvaluationCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    product_outcomes: dict[str, ProductOutcomeId] | None = None
    if isinstance(payload, dict):
        product_outcomes = TypeAdapter(dict[str, ProductOutcomeId]).validate_python(
            payload.get("product_outcomes")
        )
        payload = payload.get("cases")
    cases = tuple(TypeAdapter(list[IntentEvaluationCase]).validate_python(payload))
    ids = [case.case_id for case in cases]
    if not cases:
        raise ValueError("evaluation corpus cannot be empty")
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case ids must be unique")
    if product_outcomes is not None:
        if set(product_outcomes) != set(ids):
            raise ValueError("product outcomes must contain every case id exactly once")
        cases = tuple(
            case.model_copy(
                update={
                    "expected_product_outcome": product_outcomes[case.case_id],
                }
            )
            for case in cases
        )
    return cases


def _corpus_digest(cases: tuple[IntentEvaluationCase, ...]) -> str:
    payload = [
        {
            "case_id": case.case_id,
            "utterance": case.utterance,
            "expected": case.expected.model_dump(mode="json"),
            "split": case.split.value,
            "category": case.category.value,
            "expected_product_outcome": (
                case.expected_product_outcome.value
                if case.expected_product_outcome is not None
                else None
            ),
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


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _provider_provenance(name: str) -> _ProviderProvenance:
    if name == "gemini":
        schema = gemini_output_schema()
        generation_config = GEMINI_GENERATION_CONFIG
    elif name == "openai":
        schema = strict_output_schema()
        generation_config = OPENAI_GENERATION_CONFIG
    else:
        raise ValueError(f"unsupported evaluation provider: {name}")
    return _ProviderProvenance(
        prompt_sha256=_text_digest(proposer_instructions()),
        output_schema_sha256=_json_digest(schema),
        generation_config=generation_config,
    )


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
    initial_runs: tuple[dict[str, LLMIntentOutput], ...] | None = None,
    on_progress: Callable[[tuple[dict[str, LLMIntentOutput], ...]], None] | None = None,
) -> tuple[dict[str, LLMIntentOutput], ...]:
    if initial_runs is not None and len(initial_runs) != repeat:
        raise ValueError("initial prediction runs must match requested repeat count")
    runs = (
        [dict(predictions) for predictions in initial_runs]
        if initial_runs is not None
        else [{} for _ in range(repeat)]
    )
    _validate_prediction_ids(cases, tuple(runs), require_complete=False)
    for predictions in runs:
        for case in cases:
            if case.case_id in predictions:
                continue
            async with usage_request_scope():
                predictions[case.case_id] = await proposer.propose(case.utterance)
            if on_progress is not None:
                on_progress(tuple(dict(run) for run in runs))
    return tuple(runs)


def _validate_prediction_ids(
    cases: tuple[IntentEvaluationCase, ...],
    runs: tuple[dict[str, LLMIntentOutput], ...],
    *,
    require_complete: bool = True,
) -> None:
    expected_ids = {case.case_id for case in cases}
    for index, predictions in enumerate(runs, start=1):
        prediction_ids = set(predictions)
        valid = (
            prediction_ids == expected_ids
            if require_complete
            else prediction_ids <= expected_ids
        )
        if not valid:
            expectation = (
                "contain every case id exactly once"
                if require_complete
                else "contain only case ids from the selected evaluation corpus"
            )
            raise ValueError(f"prediction run {index} must {expectation}")


def load_recording(
    path: Path,
    cases: tuple[IntentEvaluationCase, ...],
    *,
    require_complete: bool = True,
) -> IntentPredictionRecording:
    recording = IntentPredictionRecording.model_validate_json(path.read_text(encoding="utf-8"))
    if recording.corpus_sha256 != _corpus_digest(cases):
        raise ValueError("prediction recording does not match the selected evaluation corpus")
    if require_complete and not recording.complete:
        raise ValueError("prediction recording is incomplete; resume it before evaluation")
    _validate_prediction_ids(
        cases,
        tuple(run.predictions for run in recording.runs),
        require_complete=require_complete,
    )
    return recording


def _recording(
    *,
    provider: str,
    model: str,
    provenance: _ProviderProvenance,
    cases: tuple[IntentEvaluationCase, ...],
    created_at: datetime,
    prediction_runs: tuple[dict[str, LLMIntentOutput], ...],
) -> IntentPredictionRecording:
    expected_ids = {case.case_id for case in cases}
    complete = all(set(predictions) == expected_ids for predictions in prediction_runs)
    return IntentPredictionRecording(
        schema_version="place-intent-predictions-v2",
        provider=provider,
        model=model,
        corpus_sha256=_corpus_digest(cases),
        prompt_sha256=provenance.prompt_sha256,
        output_schema_sha256=provenance.output_schema_sha256,
        generation_config=provenance.generation_config,
        requested_repeat=len(prediction_runs),
        created_at=created_at,
        updated_at=datetime.now(UTC),
        complete=complete,
        runs=tuple(
            IntentPredictionRun(repeat_index=index, predictions=predictions)
            for index, predictions in enumerate(prediction_runs, start=1)
        ),
    )


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload + "\n", encoding="utf-8")
    temporary.replace(path)


async def run(args: argparse.Namespace) -> int:
    resuming = args.resume is not None
    live = args.live or resuming
    if args.recording_out is not None and not args.live:
        raise ValueError("--recording-out requires --live")
    cases = _select_cases(
        load_cases(args.fixture),
        args.split,
        stability_probe=args.stability_probe,
    )
    prediction_runs: tuple[dict[str, LLMIntentOutput], ...]
    if live:
        proposer, model = _configured_provider(args.provider)
        provenance = _provider_provenance(args.provider)
        recording_path = args.resume if resuming else args.recording_out
        if resuming:
            existing = load_recording(args.resume, cases, require_complete=False)
            if existing.provider != args.provider or existing.model != model:
                raise ValueError("resume recording provider or model does not match configuration")
            if existing.requested_repeat != args.repeat:
                raise ValueError("--repeat must match the resume recording")
            if (
                existing.prompt_sha256 != provenance.prompt_sha256
                or existing.output_schema_sha256 != provenance.output_schema_sha256
                or existing.generation_config != provenance.generation_config
            ):
                raise ValueError("resume recording proposer contract has changed")
            created_at = existing.created_at
            initial_runs = tuple(run.predictions for run in existing.runs)
        else:
            created_at = datetime.now(UTC)
            initial_runs = tuple({} for _ in range(args.repeat))

        requested_calls = sum(len(cases) - len(predictions) for predictions in initial_runs)
    else:
        requested_calls = 0
    if live and settings.usage_policy == "dev":
        window_limit = DevUsageLimits().language_parse.window_units
        if requested_calls > window_limit:
            raise ValueError(
                f"live evaluation requests {requested_calls} calls but the dev Usage Gate "
                f"allows {window_limit} per window; select fewer cases or repetitions"
            )
    if live:
        def checkpoint(runs: tuple[dict[str, LLMIntentOutput], ...]) -> None:
            if recording_path is None:
                return
            snapshot = _recording(
                provider=args.provider,
                model=model,
                provenance=provenance,
                cases=cases,
                created_at=created_at,
                prediction_runs=runs,
            )
            _write_json(recording_path, snapshot.model_dump_json(indent=2))

        checkpoint(initial_runs)
        prediction_runs = await _live_prediction_runs(
            cases,
            proposer,
            repeat=args.repeat,
            initial_runs=initial_runs,
            on_progress=checkpoint,
        )
        checkpoint(prediction_runs)
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
    source.add_argument(
        "--resume",
        type=Path,
        help="중단된 live prediction recording을 이어서 호출한다",
    )
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
