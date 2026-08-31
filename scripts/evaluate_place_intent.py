"""녹화 fixture 또는 명시적 실API 호출로 Place intent proposer를 평가한다."""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import TypeAdapter

from app.discovery.place_intent.contract import LLMIntentOutput
from app.discovery.place_intent.evaluation import (
    IntentEvaluationCase,
    evaluate_intent_outputs,
)
from app.discovery.place_intent.openai import configured_intent_proposer
from app.usage.gate import usage_request_scope

_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "place_intent"
    / "recorded_outputs.json"
)


def load_cases(path: Path) -> tuple[IntentEvaluationCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(TypeAdapter(list[IntentEvaluationCase]).validate_python(payload))


async def _live_predictions(
    cases: tuple[IntentEvaluationCase, ...],
) -> dict[str, LLMIntentOutput]:
    proposer = configured_intent_proposer()
    predictions = {}
    for case in cases:
        async with usage_request_scope():
            predictions[case.case_id] = await proposer.propose(case.utterance)
    return predictions


async def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.fixture)
    if args.live:
        predictions = await _live_predictions(cases)
    else:
        predictions = {case.case_id: case.recorded_output for case in cases}
    report = evaluate_intent_outputs(cases, predictions)
    print(report.model_dump_json(indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    parser.add_argument(
        "--live",
        action="store_true",
        help="configured OpenAI model을 실제 호출한다 (기본은 녹화 출력만 평가)",
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
