"""Place intent proposer의 의미 오류 비용을 분리해 재는 순수 평가기."""

from collections import Counter, defaultdict
from enum import StrEnum

from pydantic import Field

from app.discovery.place_intent.contract import (
    IntentEvidenceError,
    LLMIntentOutput,
    LLMIntentProposal,
    ProposalDisposition,
    ProposalReason,
    SearchModeId,
    materialize_llm_output,
)
from app.discovery.place_intent.hypotheses import build_search_hypotheses
from app.discovery.place_intent.lenses import (
    LensAvailability,
    LensType,
    compile_search_lenses,
)
from app.discovery.place_intent.suggestions import compile_intent_suggestions
from app.place.planning.contract import PlaceSpatialConstraint, PlanningModel
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


class ProductOutcomeId(StrEnum):
    """의도 추출과 분리해 사용자가 실제로 받는 검색 진행 상태를 평가한다."""

    RESULTS_NOW = "results_now"
    RESULTS_WITH_REFINEMENT = "results_with_refinement"
    CLARIFICATION_ONLY = "clarification_only"
    SAFE_NO_SEARCH = "safe_no_search"


class EvaluationFailureType(StrEnum):
    INVALID_OUTPUT = "invalid_output"


class IntentEvaluationFailure(PlanningModel):
    """Provider 응답은 받았지만 intent 계약으로 평가할 수 없는 완료된 시도."""

    failure_type: EvaluationFailureType
    detail: str = Field(min_length=1, max_length=500)
    raw_output: str | None = Field(None, max_length=20000)


type IntentEvaluationPrediction = LLMIntentOutput | IntentEvaluationFailure


class IntentEvaluationCase(PlanningModel):
    case_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    utterance: str = Field(min_length=1, max_length=2000)
    expected: LLMIntentOutput
    recorded_output: LLMIntentOutput | None = None
    split: EvaluationSplit = EvaluationSplit.CALIBRATION
    category: EvaluationCategory = EvaluationCategory.LEGACY
    expected_product_outcome: ProductOutcomeId | None = None
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
    contract_valid_output_rate: float
    invalid_output_rate: float
    disposition_accuracy: float
    search_mode_accuracy: float
    open_discovery_precision: float | None
    open_discovery_recall: float | None
    open_discovery_f1: float | None
    explicit_target_open_discovery_false_positive_rate: float | None
    grounded_output_rate: float
    open_discovery_grounding_rate: float | None
    product_outcome_accuracy: float | None
    information_delivery_precision: float | None
    information_delivery_recall: float | None
    inappropriate_search_rate: float | None
    intent_precision: float | None
    intent_recall: float | None
    evidence_span_accuracy: float | None
    unsafe_positive_target_rate: float | None
    exact_command_recall: float | None
    unsupported_visibility: float | None
    paraphrase_plan_equivalence: float | None


class RepeatedIntentEvaluationReport(PlanningModel):
    case_count: int
    repeat_count: int
    mean: IntentEvaluationReport
    category_means: dict[EvaluationCategory, IntentEvaluationReport]
    runs: tuple[IntentEvaluationReport, ...]
    search_mode_stability: float | None
    semantic_output_stability: float | None
    product_outcome_stability: float | None


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


def _prediction_shape(prediction: IntentEvaluationPrediction) -> tuple:
    if isinstance(prediction, IntentEvaluationFailure):
        return ("failure", prediction.failure_type.value)
    return ("output", _output_shape(prediction))


def _prediction_search_mode_shape(prediction: IntentEvaluationPrediction) -> tuple:
    if isinstance(prediction, IntentEvaluationFailure):
        return ("failure", prediction.failure_type.value)
    return ("output", _is_open_discovery(prediction))


def _prediction_product_outcome_shape(
    utterance: str,
    prediction: IntentEvaluationPrediction,
) -> tuple:
    if isinstance(prediction, IntentEvaluationFailure):
        return ("failure", prediction.failure_type.value)
    return ("output", _product_outcome(utterance, prediction).value)


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _optional_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _optional_precision(numerator: int, predicted: int, expected: int) -> float | None:
    if predicted:
        return numerator / predicted
    return 0.0 if expected else None


_EVALUATION_SPATIAL = PlaceSpatialConstraint(
    lat=37.5563,
    lng=126.9236,
    radius_m=3000,
)
_INFORMATION_OUTCOMES = {
    ProductOutcomeId.RESULTS_NOW,
    ProductOutcomeId.RESULTS_WITH_REFINEMENT,
}


def _product_outcome(utterance: str, output: LLMIntentOutput) -> ProductOutcomeId:
    """DB 결과 수와 별개로 현재 pipeline이 검색을 실행하거나 질문만 하는지 분류한다."""

    try:
        grounded = materialize_llm_output(utterance, output)
    except IntentEvidenceError:
        return ProductOutcomeId.CLARIFICATION_ONLY
    if output.disposition is ProposalDisposition.ABSTAINED:
        return (
            ProductOutcomeId.SAFE_NO_SEARCH
            if output.reason in {
                ProposalReason.UNSAFE_TO_GUESS,
                ProposalReason.UNSUPPORTED_LANGUAGE,
            }
            else ProductOutcomeId.CLARIFICATION_ONLY
        )
    normalized = build_search_hypotheses(grounded)
    suggestions = compile_intent_suggestions(
        grounded,
        spatial=_EVALUATION_SPATIAL,
        limit_per_kind=3,
    )
    lenses = compile_search_lenses(
        normalized,
        suggestions,
        spatial=_EVALUATION_SPATIAL,
        limit_per_kind=3,
    )
    if lenses.executable_targets:
        has_refinement = any(
            signal.lens_type is LensType.UNRESOLVED for signal in lenses.signal_lenses
        )
        return (
            ProductOutcomeId.RESULTS_WITH_REFINEMENT
            if has_refinement
            else ProductOutcomeId.RESULTS_NOW
        )
    if any(
        target.availability is LensAvailability.NEEDS_SELECTION
        for target in lenses.target_lenses
    ):
        return ProductOutcomeId.CLARIFICATION_ONLY
    return ProductOutcomeId.SAFE_NO_SEARCH


def evaluate_intent_outputs(
    cases: tuple[IntentEvaluationCase, ...],
    predictions: dict[str, IntentEvaluationPrediction],
) -> IntentEvaluationReport:
    if not cases:
        raise ValueError("at least one evaluation case is required")
    expected_ids = {case.case_id for case in cases}
    if set(predictions) != expected_ids:
        raise ValueError("predictions must contain every case id exactly once")

    valid_outputs = 0
    invalid_outputs = 0
    disposition_matches = 0
    search_mode_matches = 0
    open_true_positive = 0
    open_predicted = 0
    open_expected = 0
    protected_direct_open = 0
    protected_direct_total = 0
    grounded_outputs = 0
    predicted_open_grounded = 0
    product_outcome_matches = 0
    product_outcome_total = 0
    expected_information = 0
    predicted_information = 0
    delivered_information = 0
    inappropriate_search = 0
    expected_no_information = 0
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
    paraphrases: dict[str, list[tuple]] = defaultdict(list)

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
        expected_open = _is_open_discovery(expected)
        open_expected += expected_open

        expected_proposals = _proposals(expected)
        expected_counts = Counter(_intent_key(item) for item in expected_proposals)
        expected_total += sum(expected_counts.values())
        expected_required_target = any(
            proposal.role is IntentRole.REQUIRED_TARGET for proposal in expected_proposals
        )
        if expected_required_target and not expected_open:
            protected_direct_total += 1

        expected_has_information = False
        if case.expected_product_outcome is not None:
            product_outcome_total += 1
            expected_has_information = (
                case.expected_product_outcome in _INFORMATION_OUTCOMES
            )
            expected_information += expected_has_information
            expected_no_information += not expected_has_information

        if case.exact_command:
            exact_command_total += 1

        for proposal in expected_proposals:
            if proposal.role in forbidden_positive_roles:
                unsafe_relevant += bool(_target_kinds(proposal))
            requires_visibility = isinstance(
                proposal.intent,
                (ActivityIntent, ObjectIntent, SemanticIntent),
            ) or proposal.role in {
                IntentRole.REQUIRED_CONDITION,
                IntentRole.EXCLUDED,
            }
            unsupported_total += requires_visibility

        if isinstance(predicted, IntentEvaluationFailure):
            invalid_outputs += predicted.failure_type is EvaluationFailureType.INVALID_OUTPUT
            if case.paraphrase_group:
                paraphrases[case.paraphrase_group].append(
                    ("failure", predicted.failure_type.value, case.case_id)
                )
            continue

        valid_outputs += 1
        disposition_matches += predicted.disposition is expected.disposition
        predicted_open = _is_open_discovery(predicted)
        search_mode_matches += predicted_open == expected_open
        open_true_positive += expected_open and predicted_open
        open_predicted += predicted_open

        predicted_proposals = _proposals(predicted)
        predicted_counts = Counter(_intent_key(item) for item in predicted_proposals)
        true_positive += sum((expected_counts & predicted_counts).values())
        predicted_total += sum(predicted_counts.values())

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

        if case.expected_product_outcome is not None:
            predicted_product_outcome = _product_outcome(case.utterance, predicted)
            product_outcome_matches += (
                predicted_product_outcome is case.expected_product_outcome
            )
            predicted_has_information = predicted_product_outcome in _INFORMATION_OUTCOMES
            predicted_information += predicted_has_information
            delivered_information += expected_has_information and predicted_has_information
            inappropriate_search += not expected_has_information and predicted_has_information

        if expected_required_target and not expected_open:
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
                if forbidden_kinds & predicted_positive_kinds:
                    unsafe_positive += 1

            requires_visibility = isinstance(
                proposal.intent,
                (ActivityIntent, ObjectIntent, SemanticIntent),
            ) or proposal.role in {
                IntentRole.REQUIRED_CONDITION,
                IntentRole.EXCLUDED,
            }
            if requires_visibility and _intent_key(proposal) in predicted_counts:
                unsupported_visible += 1

        if case.exact_command:
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
    open_precision = _optional_precision(
        open_true_positive,
        open_predicted,
        open_expected,
    )
    open_recall = _optional_rate(open_true_positive, open_expected)
    open_f1 = (
        2 * open_precision * open_recall / (open_precision + open_recall)
        if open_precision is not None
        and open_recall is not None
        and open_precision + open_recall
        else (
            0.0
            if open_precision is not None and open_recall is not None
            else None
        )
    )
    return IntentEvaluationReport(
        case_count=len(cases),
        contract_valid_output_rate=_rate(valid_outputs, len(cases)),
        invalid_output_rate=_rate(invalid_outputs, len(cases)),
        disposition_accuracy=_rate(disposition_matches, len(cases)),
        search_mode_accuracy=_rate(search_mode_matches, len(cases)),
        open_discovery_precision=open_precision,
        open_discovery_recall=open_recall,
        open_discovery_f1=open_f1,
        explicit_target_open_discovery_false_positive_rate=_optional_rate(
            protected_direct_open,
            protected_direct_total,
        ),
        grounded_output_rate=_rate(grounded_outputs, len(cases)),
        open_discovery_grounding_rate=_optional_rate(
            predicted_open_grounded,
            open_predicted,
        ),
        product_outcome_accuracy=_optional_rate(
            product_outcome_matches,
            product_outcome_total,
        ),
        information_delivery_precision=_optional_precision(
            delivered_information,
            predicted_information,
            expected_information,
        ),
        information_delivery_recall=_optional_rate(
            delivered_information,
            expected_information,
        ),
        inappropriate_search_rate=_optional_rate(
            inappropriate_search,
            expected_no_information,
        ),
        intent_precision=_optional_precision(
            true_positive,
            predicted_total,
            expected_total,
        ),
        intent_recall=_optional_rate(true_positive, expected_total),
        evidence_span_accuracy=_optional_rate(grounded, predicted_evidence),
        unsafe_positive_target_rate=_optional_rate(unsafe_positive, unsafe_relevant),
        exact_command_recall=_optional_rate(exact_command_hit, exact_command_total),
        unsupported_visibility=_optional_rate(unsupported_visible, unsupported_total),
        paraphrase_plan_equivalence=_optional_rate(
            equivalent_groups,
            len(comparable_groups),
        ),
    )


def evaluate_intent_runs(
    cases: tuple[IntentEvaluationCase, ...],
    prediction_runs: tuple[dict[str, IntentEvaluationPrediction], ...],
) -> RepeatedIntentEvaluationReport:
    if not prediction_runs:
        raise ValueError("at least one prediction run is required")
    reports = tuple(evaluate_intent_outputs(cases, run) for run in prediction_runs)

    def mean_report(items: tuple[IntentEvaluationReport, ...]) -> IntentEvaluationReport:
        def metric_mean(name: str) -> float | None:
            values = [getattr(report, name) for report in items]
            present = [value for value in values if value is not None]
            return sum(present) / len(present) if present else None

        return IntentEvaluationReport(
            case_count=items[0].case_count,
            **{
                name: metric_mean(name)
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
    stable_product_outcomes = 0
    product_stability_total = 0
    for case in cases:
        outputs = tuple(run[case.case_id] for run in prediction_runs)
        stable_modes += len({_prediction_search_mode_shape(output) for output in outputs}) == 1
        stable_outputs += len({_prediction_shape(output) for output in outputs}) == 1
        if case.expected_product_outcome is not None:
            product_stability_total += 1
            stable_product_outcomes += len(
                {
                    _prediction_product_outcome_shape(case.utterance, output)
                    for output in outputs
                }
            ) == 1
    return RepeatedIntentEvaluationReport(
        case_count=len(cases),
        repeat_count=len(prediction_runs),
        mean=mean,
        category_means=category_means,
        runs=reports,
        search_mode_stability=(
            _rate(stable_modes, len(cases)) if len(prediction_runs) > 1 else None
        ),
        semantic_output_stability=(
            _rate(stable_outputs, len(cases)) if len(prediction_runs) > 1 else None
        ),
        product_outcome_stability=_optional_rate(
            stable_product_outcomes,
            product_stability_total,
        )
        if len(prediction_runs) > 1
        else None,
    )
