"""Place intent proposer의 의미 오류 비용을 분리해 재는 순수 평가기."""

from collections import Counter, defaultdict
from enum import StrEnum

from pydantic import Field

from app.discovery.place_intent.contract import (
    IntentEvidenceError,
    LLMIntentOutput,
    LLMIntentProposal,
    SearchModeId,
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


class EvaluationSplit(StrEnum):
    CALIBRATION = "calibration"
    HOLDOUT = "holdout"


class EvaluationCategory(StrEnum):
    LEGACY = "legacy"
    DELEGATED_OPEN = "delegated_open"
    EXPLICIT_DIRECTED = "explicit_directed"
    MIXED_DELEGATION = "mixed_delegation"
    AFFECTIVE_AMBIGUOUS = "affective_ambiguous"
    ROLE_SAFETY = "role_safety"


class IntentEvaluationCase(PlanningModel):
    case_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    utterance: str = Field(min_length=1, max_length=2000)
    expected: LLMIntentOutput
    recorded_output: LLMIntentOutput | None = None
    split: EvaluationSplit = EvaluationSplit.CALIBRATION
    category: EvaluationCategory = EvaluationCategory.LEGACY
    stability_probe: bool = False
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
    search_mode_accuracy: float
    open_discovery_precision: float
    open_discovery_recall: float
    open_discovery_f1: float
    explicit_target_open_discovery_false_positive_rate: float
    grounded_output_rate: float
    open_discovery_grounding_rate: float
    intent_precision: float
    intent_recall: float
    evidence_span_accuracy: float
    unsafe_positive_target_rate: float
    exact_command_recall: float
    unsupported_visibility: float
    paraphrase_plan_equivalence: float


class RepeatedIntentEvaluationReport(PlanningModel):
    case_count: int
    repeat_count: int
    mean: IntentEvaluationReport
    category_means: dict[EvaluationCategory, IntentEvaluationReport]
    runs: tuple[IntentEvaluationReport, ...]
    search_mode_stability: float
    semantic_output_stability: float


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


def _is_open_discovery(output: LLMIntentOutput) -> bool:
    return any(
        interpretation.search_directive.mode is SearchModeId.OPEN_DISCOVERY
        for interpretation in output.interpretations
    )


def _output_shape(output: LLMIntentOutput) -> tuple:
    return (
        output.disposition.value,
        output.reason.value if output.reason is not None else None,
        tuple(
            sorted(
                (
                    interpretation.search_directive.mode.value,
                    tuple(
                        sorted(
                            (_concept_key(proposal), proposal.role.value)
                            for proposal in interpretation.proposals
                        )
                    ),
                )
                for interpretation in output.interpretations
            )
        ),
    )


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
    search_mode_matches = 0
    open_true_positive = 0
    open_predicted = 0
    open_expected = 0
    protected_direct_open = 0
    protected_direct_total = 0
    grounded_outputs = 0
    predicted_open_grounded = 0
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
        expected_open = _is_open_discovery(expected)
        predicted_open = _is_open_discovery(predicted)
        search_mode_matches += predicted_open == expected_open
        open_true_positive += expected_open and predicted_open
        open_predicted += predicted_open
        open_expected += expected_open

        expected_proposals = _proposals(expected)
        predicted_proposals = _proposals(predicted)
        expected_counts = Counter(_intent_key(item) for item in expected_proposals)
        predicted_counts = Counter(_intent_key(item) for item in predicted_proposals)
        true_positive += sum((expected_counts & predicted_counts).values())
        predicted_total += sum(predicted_counts.values())
        expected_total += sum(expected_counts.values())

        predicted_evidence += len(predicted_proposals)
        grounded_output = False
        try:
            materialize_llm_output(case.utterance, predicted)
        except IntentEvidenceError:
            pass
        else:
            grounded_output = True
            grounded_outputs += 1
            grounded += len(predicted_proposals)
        if predicted_open and grounded_output:
            predicted_open_grounded += 1

        expected_required_target = any(
            proposal.role is IntentRole.REQUIRED_TARGET for proposal in expected_proposals
        )
        if expected_required_target and not expected_open:
            protected_direct_total += 1
            protected_direct_open += predicted_open

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
    open_precision = _rate(open_true_positive, open_predicted)
    open_recall = _rate(open_true_positive, open_expected)
    open_f1 = (
        2 * open_precision * open_recall / (open_precision + open_recall)
        if open_precision + open_recall
        else 0.0
    )
    return IntentEvaluationReport(
        case_count=len(cases),
        disposition_accuracy=_rate(disposition_matches, len(cases)),
        search_mode_accuracy=_rate(search_mode_matches, len(cases)),
        open_discovery_precision=open_precision,
        open_discovery_recall=open_recall,
        open_discovery_f1=open_f1,
        explicit_target_open_discovery_false_positive_rate=_rate(
            protected_direct_open,
            protected_direct_total,
        )
        if protected_direct_total
        else 0.0,
        grounded_output_rate=_rate(grounded_outputs, len(cases)),
        open_discovery_grounding_rate=_rate(predicted_open_grounded, open_predicted),
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


def evaluate_intent_runs(
    cases: tuple[IntentEvaluationCase, ...],
    prediction_runs: tuple[dict[str, LLMIntentOutput], ...],
) -> RepeatedIntentEvaluationReport:
    if not prediction_runs:
        raise ValueError("at least one prediction run is required")
    reports = tuple(evaluate_intent_outputs(cases, run) for run in prediction_runs)

    def mean_report(items: tuple[IntentEvaluationReport, ...]) -> IntentEvaluationReport:
        return IntentEvaluationReport(
            case_count=items[0].case_count,
            **{
                name: sum(getattr(report, name) for report in items) / len(items)
                for name in IntentEvaluationReport.model_fields
                if name != "case_count"
            },
        )

    mean = mean_report(reports)
    categories = tuple(dict.fromkeys(case.category for case in cases))
    category_means = {}
    for category in categories:
        category_cases = tuple(case for case in cases if case.category is category)
        category_ids = {case.case_id for case in category_cases}
        category_reports = tuple(
            evaluate_intent_outputs(
                category_cases,
                {
                    case_id: output
                    for case_id, output in run.items()
                    if case_id in category_ids
                },
            )
            for run in prediction_runs
        )
        category_means[category] = mean_report(category_reports)
    stable_modes = 0
    stable_outputs = 0
    for case in cases:
        outputs = tuple(run[case.case_id] for run in prediction_runs)
        stable_modes += len({_is_open_discovery(output) for output in outputs}) == 1
        stable_outputs += len({_output_shape(output) for output in outputs}) == 1
    return RepeatedIntentEvaluationReport(
        case_count=len(cases),
        repeat_count=len(prediction_runs),
        mean=mean,
        category_means=category_means,
        runs=reports,
        search_mode_stability=_rate(stable_modes, len(cases)),
        semantic_output_stability=_rate(stable_outputs, len(cases)),
    )
