"""Place intent proposer의 의미 오류 비용을 분리해 재는 순수 평가기."""

from collections import Counter, defaultdict

from pydantic import Field

from app.discovery.place_intent.contract import (
    IntentEvidenceError,
    LLMIntentOutput,
    LLMIntentProposal,
    materialize_llm_output,
)
from app.place.planning.contract import PlanningModel
from app.place.planning.intents import (
    ActivityIntent,
    IntentRole,
    KindIntent,
    ObjectIntent,
    PurposeIntent,
    SemanticIntent,
)
from app.place.planning.purpose import resolve_purposes


class IntentEvaluationCase(PlanningModel):
    case_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    utterance: str = Field(min_length=1, max_length=2000)
    expected: LLMIntentOutput
    recorded_output: LLMIntentOutput
    exact_command: bool = False
    paraphrase_group: str | None = Field(
        None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_.-]+$",
    )


class IntentEvaluationReport(PlanningModel):
    case_count: int
    disposition_accuracy: float
    intent_precision: float
    intent_recall: float
    evidence_span_accuracy: float
    unsafe_positive_target_rate: float
    exact_command_recall: float
    unsupported_visibility: float
    paraphrase_plan_equivalence: float


def _concept_key(proposal: LLMIntentProposal) -> str:
    return proposal.intent.model_dump_json()


def _intent_key(proposal: LLMIntentProposal) -> tuple[str, IntentRole]:
    return (_concept_key(proposal), proposal.role)


def _target_kinds(proposal: LLMIntentProposal) -> frozenset[str]:
    if isinstance(proposal.intent, KindIntent):
        return frozenset({proposal.intent.kind.value})
    if isinstance(proposal.intent, PurposeIntent):
        return frozenset(
            kind.value for kind in resolve_purposes([proposal.intent.purpose_id]).kinds
        )
    return frozenset()


def _proposals(output: LLMIntentOutput) -> tuple[LLMIntentProposal, ...]:
    return tuple(
        proposal
        for interpretation in output.interpretations
        for proposal in interpretation.proposals
    )


def _semantic_shape(output: LLMIntentOutput) -> tuple[tuple[tuple[str, str], ...], ...]:
    """evidence와 대안 순서를 제외한 plan 입력 의미. 대안끼리는 합치지 않는다."""

    interpretations = []
    for interpretation in output.interpretations:
        interpretations.append(
            tuple(
                sorted(
                    (_concept_key(proposal), proposal.role.value)
                    for proposal in interpretation.proposals
                )
            )
        )
    return tuple(sorted(interpretations))


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def evaluate_intent_outputs(
    cases: tuple[IntentEvaluationCase, ...],
    predictions: dict[str, LLMIntentOutput],
) -> IntentEvaluationReport:
    if not cases:
        raise ValueError("at least one evaluation case is required")
    expected_ids = {case.case_id for case in cases}
    if set(predictions) != expected_ids:
        raise ValueError("predictions must contain every case id exactly once")

    disposition_matches = 0
    true_positive = 0
    predicted_total = 0
    expected_total = 0
    grounded = 0
    predicted_evidence = 0
    unsafe_positive = 0
    unsafe_relevant = 0
    exact_command_hit = 0
    exact_command_total = 0
    unsupported_visible = 0
    unsupported_total = 0
    paraphrases: dict[str, list[tuple[tuple[tuple[str, str], ...], ...]]] = defaultdict(list)

    forbidden_positive_roles = {
        IntentRole.ANALOGY,
        IntentRole.EXCLUDED,
        IntentRole.NEGATED,
        IntentRole.HYPOTHETICAL,
        IntentRole.RELATIONAL,
    }
    for case in cases:
        expected = case.expected
        predicted = predictions[case.case_id]
        disposition_matches += predicted.disposition is expected.disposition

        expected_proposals = _proposals(expected)
        predicted_proposals = _proposals(predicted)
        expected_counts = Counter(_intent_key(item) for item in expected_proposals)
        predicted_counts = Counter(_intent_key(item) for item in predicted_proposals)
        true_positive += sum((expected_counts & predicted_counts).values())
        predicted_total += sum(predicted_counts.values())
        expected_total += sum(expected_counts.values())

        predicted_evidence += len(predicted_proposals)
        try:
            materialize_llm_output(case.utterance, predicted)
        except IntentEvidenceError:
            pass
        else:
            grounded += len(predicted_proposals)

        predicted_positive_kinds = frozenset(
            kind
            for proposal in predicted_proposals
            if proposal.role is IntentRole.REQUIRED_TARGET
            for kind in _target_kinds(proposal)
        )
        for proposal in expected_proposals:
            if proposal.role in forbidden_positive_roles:
                forbidden_kinds = _target_kinds(proposal)
                unsafe_relevant += bool(forbidden_kinds)
                if forbidden_kinds & predicted_positive_kinds:
                    unsafe_positive += 1

            requires_visibility = isinstance(
                proposal.intent,
                (ActivityIntent, ObjectIntent, SemanticIntent),
            ) or proposal.role in {
                IntentRole.REQUIRED_CONDITION,
                IntentRole.EXCLUDED,
            }
            if requires_visibility:
                unsupported_total += 1
                if _intent_key(proposal) in predicted_counts:
                    unsupported_visible += 1

        if case.exact_command:
            exact_command_total += 1
            expected_targets = {
                _concept_key(item)
                for item in expected_proposals
                if item.role is IntentRole.REQUIRED_TARGET
            }
            predicted_targets = {
                _concept_key(item)
                for item in predicted_proposals
                if item.role is IntentRole.REQUIRED_TARGET
            }
            exact_command_hit += bool(expected_targets & predicted_targets)

        if case.paraphrase_group:
            paraphrases[case.paraphrase_group].append(_semantic_shape(predicted))

    comparable_groups = [values for values in paraphrases.values() if len(values) > 1]
    equivalent_groups = sum(len(set(values)) == 1 for values in comparable_groups)
    return IntentEvaluationReport(
        case_count=len(cases),
        disposition_accuracy=_rate(disposition_matches, len(cases)),
        intent_precision=_rate(true_positive, predicted_total),
        intent_recall=_rate(true_positive, expected_total),
        evidence_span_accuracy=_rate(grounded, predicted_evidence),
        unsafe_positive_target_rate=_rate(unsafe_positive, unsafe_relevant)
        if unsafe_relevant
        else 0.0,
        exact_command_recall=_rate(exact_command_hit, exact_command_total),
        unsupported_visibility=_rate(unsupported_visible, unsupported_total),
        paraphrase_plan_equivalence=_rate(equivalent_groups, len(comparable_groups)),
    )
