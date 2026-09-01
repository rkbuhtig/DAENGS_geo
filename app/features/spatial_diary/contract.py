"""공간 일기 v1의 순수 객체 계약. Decision: #74.

저장 모델이나 API 모델이 아니다. 어떤 객체가 불변 사실이고, 어떤 사용자 응답이 증언이며,
어느 순간 지도에 남는 안정적인 Pin이 되는지를 먼저 고정한다. 구현은 이 타입을 그대로
테이블 하나씩 복사할 의무가 없지만, 상태를 합치거나 의미를 바꿀 수는 없다.
"""

import math
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CAPSULE_VERSION = 1
MEASUREMENT_RECEIPT_VERSION = 1
CONTEXT_SNAPSHOT_VERSION = 1
OFFER_VERSION = 1
INTERACTION_VERSION = 1
ATTESTATION_VERSION = 1
PIN_VERSION = 1
MEMORY_PLACE_VERSION = 1
MEMORY_PLACE_MEMBERSHIP_VERSION = 1
VIEW_VERSION = 1
JOURNAL_PROJECTION_VERSION = 1
PUBLISHED_JOURNAL_SNAPSHOT_VERSION = 1
NEGATIVE_SPATIAL_CLAIM_POLICY_VERSION = 1

EvidenceOrigin = Literal["device", "mock", "mixed", "unknown"]
EvidenceScalar = str | int | float | bool | None
SpatialFieldMetric = Literal[
    "total_time",
    "visit_rate",
    "conditional_dwell",
    "time_utilization",
    "walk_utilization",
]


class FrozenContract(BaseModel):
    """모르는 필드를 버리지 않고 생성 뒤 수정도 허용하지 않는 경계 모델."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _timezone_required(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("spatial diary timestamps must include a timezone")
    return value


class ContextStatus(StrEnum):
    CAPTURED = "captured"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    FAILED = "failed"


class DriftAssessment(StrEnum):
    NOT_ASSESSED = "not_assessed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_SUSPECTED = "not_suspected"
    SUSPECTED = "suspected"


class OfferInteractionKind(StrEnum):
    VIEWED = "viewed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class ReviewDisposition(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class MemoryAction(StrEnum):
    SAVE = "save"
    DISMISS = "dismiss"


class SubjectRole(StrEnum):
    DOG = "dog"
    OWNER = "owner"
    JOINT = "joint"
    EXTERNAL = "external"
    NONE = "none"
    UNKNOWN = "unknown"


class ElicitationMode(StrEnum):
    SYSTEM_OFFER = "system_offer"
    IN_WALK_BOOKMARK = "in_walk_bookmark"
    POST_WALK_MANUAL = "post_walk_manual"
    PHOTO_ASSOCIATED = "photo_associated"


class PinOrigin(StrEnum):
    SYSTEM_OFFER = "system_offer"
    IN_WALK_BOOKMARK = "in_walk_bookmark"
    POST_WALK_MANUAL = "post_walk_manual"
    PHOTO_ASSOCIATED = "photo_associated"


class MemoryPlaceMembershipOrigin(StrEnum):
    SEED = "seed"
    USER_LINKED = "user_linked"


class MacroExposure(StrEnum):
    EXPOSED = "exposed"
    NOT_EXPOSED = "not_exposed"
    UNCERTAIN = "uncertain"


class CapabilitySupport(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class PlaceObservation(StrEnum):
    OBSERVED = "observed"
    NOT_OBSERVED = "not_observed"
    UNJUDGEABLE = "unjudgeable"


class UnjudgeableReason(StrEnum):
    NOT_EXPOSED = "not_exposed"
    EXPOSURE_UNCERTAIN = "exposure_uncertain"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    SPATIAL_DRIFT_NOT_ASSESSED = "spatial_drift_not_assessed"
    SPATIAL_DRIFT_INSUFFICIENT_EVIDENCE = "spatial_drift_insufficient_evidence"
    SPATIAL_DRIFT_SUSPECTED = "spatial_drift_suspected"


class TemporalPrecision(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class ClaimSupport(StrEnum):
    SUPPORTED = "supported"
    APPROXIMATE = "approximate"
    UNSUPPORTED = "unsupported"
    ATTESTATION_REQUIRED = "attestation_required"


class GeoPoint(FrozenContract):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class EventFootprint(FrozenContract):
    """v1의 보수적 사건 범위. 대표점과 달리 실제 공간 주장은 이 범위가 담당한다."""

    kind: Literal["circle"] = "circle"
    centre: GeoPoint
    radius_m: float = Field(gt=0, le=5_000)


class ObservationCapability(FrozenContract):
    """해당 Capsule generation이 어떤 현상을 다시 읽을 재료를 보존했는가."""

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    generation: int = Field(ge=1)


class WalkCapsuleManifest(FrozenContract):
    """자식 결과를 복제하지 않고 한 산책이 완전히 봉인됐음을 선언하는 manifest."""

    capsule_version: Literal[CAPSULE_VERSION] = CAPSULE_VERSION
    session_id: str = Field(min_length=1, max_length=128)
    dog_id: str = Field(min_length=1, max_length=128)
    walk_record_version: int = Field(ge=1)
    walk_calculation_version: int = Field(ge=1)
    capabilities: tuple[ObservationCapability, ...]
    sealed_at: datetime

    _tz = field_validator("sealed_at")(_timezone_required)

    @model_validator(mode="after")
    def unique_capabilities(self) -> "WalkCapsuleManifest":
        keys = [(item.name, item.generation) for item in self.capabilities]
        if len(keys) != len(set(keys)):
            raise ValueError("capsule capabilities must be unique by name and generation")
        return self


class MeasurementReceipt(FrozenContract):
    """주장 판정 전의 산책별 측정 영수증.

    비율과 `신뢰도 점수`는 넣지 않는다. 소비자는 이름 붙은 분자·분모와 정책 버전으로
    ClaimAllowance를 다시 계산한다.
    """

    receipt_version: Literal[MEASUREMENT_RECEIPT_VERSION] = MEASUREMENT_RECEIPT_VERSION
    session_id: str = Field(min_length=1, max_length=128)
    evidence_origin: EvidenceOrigin

    received_fix_count: int = Field(ge=0)
    accepted_fix_count: int = Field(ge=0)
    rejected_low_accuracy_count: int = Field(ge=0)
    rejected_out_of_order_count: int = Field(ge=0)
    rejected_before_start_count: int = Field(ge=0)
    rejected_after_end_count: int = Field(ge=0)
    unknown_accuracy_count: int = Field(ge=0)
    jump_break_count: int = Field(ge=0)
    gap_break_count: int = Field(ge=0)
    explicit_break_count: int = Field(ge=0)
    dropped_at_capacity_count: int = Field(ge=0)
    mock_fix_count: int = Field(ge=0)

    session_wall_time_s: float = Field(ge=0)
    canonical_segment_time_s: float = Field(ge=0)
    gap_elapsed_s: float = Field(ge=0)

    reported_accuracy_count: int = Field(ge=0)
    reported_accuracy_p50_m: float | None = Field(default=None, ge=0)
    reported_accuracy_p90_m: float | None = Field(default=None, ge=0)
    accepted_accuracy_count: int = Field(ge=0)
    accepted_accuracy_p50_m: float | None = Field(default=None, ge=0)
    accepted_accuracy_p90_m: float | None = Field(default=None, ge=0)

    drift_assessment: DriftAssessment = DriftAssessment.NOT_ASSESSED
    drift_assessment_method: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def receipt_is_consistent(self) -> "MeasurementReceipt":
        if self.accepted_fix_count > self.received_fix_count:
            raise ValueError("accepted fixes cannot exceed received fixes")
        if self.unknown_accuracy_count > self.accepted_fix_count:
            raise ValueError("unknown accuracy count cannot exceed accepted fixes")
        if self.mock_fix_count > self.received_fix_count:
            raise ValueError("mock fix count cannot exceed received fixes")
        if self.reported_accuracy_count > self.received_fix_count:
            raise ValueError("reported accuracy count cannot exceed received fixes")
        if self.accepted_accuracy_count > self.accepted_fix_count:
            raise ValueError("accepted accuracy count cannot exceed accepted fixes")
        tolerance = 1e-6
        if self.canonical_segment_time_s > self.session_wall_time_s + tolerance:
            raise ValueError("canonical segment time cannot exceed session wall time")
        if self.gap_elapsed_s > self.session_wall_time_s + tolerance:
            raise ValueError("gap elapsed time cannot exceed session wall time")
        self._check_percentiles(
            self.reported_accuracy_count,
            self.reported_accuracy_p50_m,
            self.reported_accuracy_p90_m,
            "reported",
        )
        self._check_percentiles(
            self.accepted_accuracy_count,
            self.accepted_accuracy_p50_m,
            self.accepted_accuracy_p90_m,
            "accepted",
        )
        if self.drift_assessment is DriftAssessment.NOT_ASSESSED:
            if self.drift_assessment_method is not None:
                raise ValueError("not_assessed drift cannot name an assessment method")
        elif self.drift_assessment_method is None:
            raise ValueError("assessed drift requires an assessment method")
        return self

    @staticmethod
    def _check_percentiles(
        count: int,
        p50: float | None,
        p90: float | None,
        label: str,
    ) -> None:
        if count == 0 and (p50 is not None or p90 is not None):
            raise ValueError(f"{label} accuracy percentiles require a positive count")
        if count > 0 and (p50 is None or p90 is None):
            raise ValueError(f"{label} accuracy count requires p50 and p90")
        if p50 is not None and p90 is not None and p50 > p90:
            raise ValueError(f"{label} accuracy p50 cannot exceed p90")


class TrailContextSnapshot(FrozenContract):
    """산책 당시 확보한 동적 문맥 원자. rainy/evening 같은 facet은 저장하지 않는다."""

    context_version: Literal[CONTEXT_SNAPSHOT_VERSION] = CONTEXT_SNAPSHOT_VERSION
    session_id: str = Field(min_length=1, max_length=128)
    status: ContextStatus
    walked_at: datetime
    source_observed_at: datetime | None = None
    captured_at: datetime
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    precipitation_mm: float | None = Field(default=None, ge=0)
    temperature_c: float | None = Field(default=None, ge=-100, le=100)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    sun_elevation_deg: float | None = Field(default=None, ge=-90, le=90)
    failure_reason: str | None = Field(default=None, min_length=1, max_length=256)

    _tz = field_validator("walked_at", "captured_at")(_timezone_required)
    _optional_tz = field_validator("source_observed_at")(
        lambda value: value if value is None else _timezone_required(value)
    )

    @model_validator(mode="after")
    def context_status_matches_payload(self) -> "TrailContextSnapshot":
        values = (
            self.precipitation_mm,
            self.temperature_c,
            self.humidity_pct,
            self.sun_elevation_deg,
        )
        observed = any(value is not None for value in values)
        if self.status in {ContextStatus.CAPTURED, ContextStatus.PARTIAL} and (
            self.provider is None or not observed
        ):
            raise ValueError("captured or partial context requires a provider and a value")
        if self.status in {ContextStatus.UNKNOWN, ContextStatus.FAILED} and observed:
            raise ValueError("unknown or failed context cannot carry observed values")
        if self.status is ContextStatus.FAILED and self.failure_reason is None:
            raise ValueError("failed context requires a failure reason")
        return self


class EvidenceValue(FrozenContract):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    value: EvidenceScalar
    unit: str | None = Field(default=None, min_length=1, max_length=32)

    @field_validator("value")
    @classmethod
    def finite_numbers(cls, value: EvidenceScalar) -> EvidenceScalar:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("evidence numbers must be finite")
        return value


class EpisodeCandidate(FrozenContract):
    """현재 정책으로 재계산 가능한 기계 후보. 사용자에게 보였다는 역사도 의미 주장도 아니다."""

    session_id: str = Field(min_length=1, max_length=128)
    source_observation_ids: tuple[str, ...] = Field(min_length=1)
    event_at: datetime
    representative_point: GeoPoint
    event_footprint: EventFootprint
    evidence: tuple[EvidenceValue, ...] = Field(min_length=1)
    candidate_policy_version: int = Field(ge=1)

    _tz = field_validator("event_at")(_timezone_required)

    @model_validator(mode="after")
    def candidate_is_consistent(self) -> "EpisodeCandidate":
        if len(self.source_observation_ids) != len(set(self.source_observation_ids)):
            raise ValueError("source observation ids must be unique")
        evidence_names = [item.name for item in self.evidence]
        if len(evidence_names) != len(set(evidence_names)):
            raise ValueError("candidate evidence names must be unique")
        return self


class EpisodeOfferSnapshot(FrozenContract):
    """재계산 후보가 실제로 사용자에게 제시된 순간의 불변 역사."""

    offer_version: Literal[OFFER_VERSION] = OFFER_VERSION
    offer_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    source_observation_ids: tuple[str, ...] = Field(min_length=1)
    event_at: datetime
    representative_point: GeoPoint
    event_footprint: EventFootprint
    evidence: tuple[EvidenceValue, ...] = Field(min_length=1)
    candidate_policy_version: int = Field(ge=1)
    claim_policy_version: int = Field(ge=1)
    prompt_snapshot: str = Field(min_length=1, max_length=2_000)
    offered_at: datetime

    _tz = field_validator("event_at", "offered_at")(_timezone_required)

    @model_validator(mode="after")
    def offer_is_consistent(self) -> "EpisodeOfferSnapshot":
        if self.offered_at < self.event_at:
            raise ValueError("an offer cannot precede its event")
        if len(self.source_observation_ids) != len(set(self.source_observation_ids)):
            raise ValueError("source observation ids must be unique")
        evidence_names = [item.name for item in self.evidence]
        if len(evidence_names) != len(set(evidence_names)):
            raise ValueError("offer evidence names must be unique")
        return self


class OfferInteraction(FrozenContract):
    """제안의 노출 생명주기. 사용자가 의미를 말하지 않았으므로 증언이 아니다."""

    interaction_version: Literal[INTERACTION_VERSION] = INTERACTION_VERSION
    interaction_id: str = Field(min_length=1, max_length=128)
    offer_id: str = Field(min_length=1, max_length=128)
    kind: OfferInteractionKind
    actor: Literal["user", "system"]
    occurred_at: datetime

    _tz = field_validator("occurred_at")(_timezone_required)

    @model_validator(mode="after")
    def actor_matches_kind(self) -> "OfferInteraction":
        if self.kind is OfferInteractionKind.EXPIRED and self.actor != "system":
            raise ValueError("only the system expires an offer")
        if self.kind is not OfferInteractionKind.EXPIRED and self.actor != "user":
            raise ValueError("view and dismiss interactions belong to the user")
        return self


class AttestedClaim(FrozenContract):
    subject_role: SubjectRole
    meaning_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    vocabulary_version: int = Field(ge=1)

    @model_validator(mode="after")
    def claim_has_a_subject(self) -> "AttestedClaim":
        if self.subject_role in {SubjectRole.NONE, SubjectRole.UNKNOWN}:
            raise ValueError("none/unknown roles do not make a positive meaning claim")
        return self


class WalkAttestation(FrozenContract):
    """사용자가 실제로 답한 의미. 수정은 update가 아니라 superseding 행이다."""

    attestation_version: Literal[ATTESTATION_VERSION] = ATTESTATION_VERSION
    attestation_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    elicitation_mode: ElicitationMode
    offer_id: str | None = Field(default=None, min_length=1, max_length=128)
    review_disposition: ReviewDisposition
    claims: tuple[AttestedClaim, ...] = ()
    memory_action: MemoryAction
    attested_at: datetime
    supersedes_attestation_id: str | None = Field(default=None, min_length=1, max_length=128)

    _tz = field_validator("attested_at")(_timezone_required)

    @model_validator(mode="after")
    def attestation_is_consistent(self) -> "WalkAttestation":
        from_offer = self.elicitation_mode is ElicitationMode.SYSTEM_OFFER
        if from_offer != (self.offer_id is not None):
            raise ValueError("only system-offer attestations reference an offer")
        if self.review_disposition is ReviewDisposition.CONFIRMED and not self.claims:
            raise ValueError("confirmed attestation requires at least one claim")
        if self.review_disposition is ReviewDisposition.REJECTED:
            if self.claims:
                raise ValueError("rejected attestation cannot carry positive claims")
            if self.memory_action is MemoryAction.SAVE:
                raise ValueError("rejected offer cannot be saved as that same memory")
        claim_keys = [
            (claim.subject_role, claim.meaning_code, claim.vocabulary_version)
            for claim in self.claims
        ]
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("attestation claims must be unique")
        if self.supersedes_attestation_id == self.attestation_id:
            raise ValueError("an attestation cannot supersede itself")
        return self


class EpisodePin(FrozenContract):
    """사용자가 공간 일기에 남기기로 한 안정적인 기억 identity."""

    pin_version: Literal[PIN_VERSION] = PIN_VERSION
    pin_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    origin: PinOrigin
    source_offer_id: str | None = Field(default=None, min_length=1, max_length=128)
    created_by_attestation_id: str = Field(min_length=1, max_length=128)
    event_at: datetime | None = None
    temporal_precision: TemporalPrecision
    representative_point: GeoPoint
    event_footprint: EventFootprint
    promoted_at: datetime

    _tz = field_validator("promoted_at")(_timezone_required)
    _optional_tz = field_validator("event_at")(
        lambda value: value if value is None else _timezone_required(value)
    )

    @model_validator(mode="after")
    def pin_is_consistent(self) -> "EpisodePin":
        from_offer = self.origin is PinOrigin.SYSTEM_OFFER
        if from_offer != (self.source_offer_id is not None):
            raise ValueError("only system-offer pins reference an offer")
        unknown_time = self.temporal_precision is TemporalPrecision.UNKNOWN
        if unknown_time != (self.event_at is None):
            raise ValueError("unknown temporal precision and a missing event_at must agree")
        if self.event_at is not None and self.promoted_at < self.event_at:
            raise ValueError("a pin cannot be promoted before its event")
        return self


class MemoryPlace(FrozenContract):
    """필터와 무관하게 남는 장소 identity. footprint는 생성 당시의 v1 snapshot이다."""

    place_version: Literal[MEMORY_PLACE_VERSION] = MEMORY_PLACE_VERSION
    place_id: str = Field(min_length=1, max_length=128)
    dog_id: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, min_length=1, max_length=80)
    footprint: EventFootprint
    grouping_policy_version: int = Field(ge=1)
    seed_fingerprint: str = Field(min_length=8, max_length=128)
    created_at: datetime

    _tz = field_validator("created_at")(_timezone_required)


class MemoryPlaceMembership(FrozenContract):
    """Episode Pin과 Memory Place의 명시적 연결. 화면 marker cluster와 다르다."""

    membership_version: Literal[MEMORY_PLACE_MEMBERSHIP_VERSION] = MEMORY_PLACE_MEMBERSHIP_VERSION
    place_id: str = Field(min_length=1, max_length=128)
    pin_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    origin: MemoryPlaceMembershipOrigin
    linked_at: datetime

    _tz = field_validator("linked_at")(_timezone_required)


class ClaimAllowance(FrozenContract):
    """영수증에서 현재 정책으로 계산한 문장 상한. Capsule 사실이 아니다."""

    policy_version: int = Field(ge=1)
    evidence_ref: str = Field(min_length=1, max_length=128)
    temporal: ClaimSupport
    spatial: ClaimSupport
    interpretation: ClaimSupport


class ContextFacetFilter(FrozenContract):
    """동결 원천값을 현재 정책으로 분류한 필터. unknown은 명시적인 값이다."""

    axis: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    values: tuple[str, ...] = Field(min_length=1)
    policy_version: int = Field(ge=1)

    @field_validator("values")
    @classmethod
    def unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("facet values must be unique")
        return values


class WalkSelector(FrozenContract):
    """어떤 Capsule이 지도 배경과 노출 분모에 들어가는가."""

    dog_id: str = Field(min_length=1, max_length=128)
    since: date | None = None
    until: date | None = None
    context_facets: tuple[ContextFacetFilter, ...] = ()

    @model_validator(mode="after")
    def range_and_facets_are_consistent(self) -> "WalkSelector":
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("walk selector since cannot follow until")
        axes = [facet.axis for facet in self.context_facets]
        if len(axes) != len(set(axes)):
            raise ValueError("walk selector facet axes must be unique")
        return self


class EntrySelector(FrozenContract):
    """선택된 Capsule 안에서 어떤 Pin을 overlay 하는가. Walk 분모를 바꾸지 않는다."""

    subject_roles: tuple[SubjectRole, ...] = ()
    meaning_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def entry_filters_are_unique(self) -> "EntrySelector":
        if len(self.subject_roles) != len(set(self.subject_roles)):
            raise ValueError("entry selector subject roles must be unique")
        if len(self.meaning_codes) != len(set(self.meaning_codes)):
            raise ValueError("entry selector meaning codes must be unique")
        return self


class QualityPolicy(FrozenContract):
    """Capsule을 cohort에서 지우지 않고 각 주장·분모의 judgeability를 평가하는 정책."""

    policy_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


class SpatialDiaryViewSpec(FrozenContract):
    view_version: Literal[VIEW_VERSION] = VIEW_VERSION
    walk_selector: WalkSelector
    entry_selector: EntrySelector
    field_metric: SpatialFieldMetric
    quality_policy: QualityPolicy


class SpatialDiaryViewReceipt(FrozenContract):
    """필터 결과가 어떤 분모와 정책으로 만들어졌는지 재현하는 영수증."""

    selector_fingerprint: str = Field(min_length=8, max_length=128)
    view_as_of: datetime
    total_capsules: int = Field(ge=0)
    selected_capsules: int = Field(ge=0)
    contributing_capsules: int = Field(ge=0)
    context_known_count: int = Field(ge=0)
    context_unknown_count: int = Field(ge=0)
    pin_count: int = Field(ge=0)
    paint_fp: str = Field(min_length=1, max_length=128)
    field_metric: SpatialFieldMetric
    normalization: str = Field(min_length=1, max_length=64)
    context_policy_version: int = Field(ge=1)
    quality_policy_version: int = Field(ge=1)
    claim_policy_version: int = Field(ge=1)

    _tz = field_validator("view_as_of")(_timezone_required)

    @model_validator(mode="after")
    def denominators_are_consistent(self) -> "SpatialDiaryViewReceipt":
        if self.selected_capsules > self.total_capsules:
            raise ValueError("selected capsules cannot exceed total capsules")
        if self.contributing_capsules > self.selected_capsules:
            raise ValueError("contributing capsules cannot exceed selected capsules")
        if self.context_known_count + self.context_unknown_count != self.selected_capsules:
            raise ValueError("known and unknown context counts must cover selected capsules")
        return self


class MemoryPlaceBiographySpec(FrozenContract):
    """장소 biography의 산책 분모와 timeline Pin 조건."""

    walk_selector: WalkSelector
    entry_selector: EntrySelector = EntrySelector()
    quality_policy: QualityPolicy


class NegativeSpatialClaimAllowance(FrozenContract):
    """한 산책의 사건 부재를 공간적 `not_observed`로 말할 수 있는 적극적 자격."""

    policy_version: Literal[NEGATIVE_SPATIAL_CLAIM_POLICY_VERSION] = (
        NEGATIVE_SPATIAL_CLAIM_POLICY_VERSION
    )
    eligible: bool
    macro_exposure: MacroExposure
    capability: CapabilitySupport
    drift_assessment: DriftAssessment
    blocking_reasons: tuple[UnjudgeableReason, ...]

    @model_validator(mode="after")
    def eligibility_requires_all_negative_evidence(self) -> "NegativeSpatialClaimAllowance":
        expected_reasons: list[UnjudgeableReason] = []
        if self.macro_exposure is MacroExposure.NOT_EXPOSED:
            expected_reasons.append(UnjudgeableReason.NOT_EXPOSED)
        elif self.macro_exposure is MacroExposure.UNCERTAIN:
            expected_reasons.append(UnjudgeableReason.EXPOSURE_UNCERTAIN)
        if self.capability is CapabilitySupport.UNSUPPORTED:
            expected_reasons.append(UnjudgeableReason.CAPABILITY_UNSUPPORTED)
        drift_reason = {
            DriftAssessment.NOT_ASSESSED: UnjudgeableReason.SPATIAL_DRIFT_NOT_ASSESSED,
            DriftAssessment.INSUFFICIENT_EVIDENCE: (
                UnjudgeableReason.SPATIAL_DRIFT_INSUFFICIENT_EVIDENCE
            ),
            DriftAssessment.NOT_SUSPECTED: None,
            DriftAssessment.SUSPECTED: UnjudgeableReason.SPATIAL_DRIFT_SUSPECTED,
        }[self.drift_assessment]
        if drift_reason is not None:
            expected_reasons.append(drift_reason)
        if self.blocking_reasons != tuple(expected_reasons):
            raise ValueError("negative spatial claim blockers must match its evidence")
        if self.eligible != (not expected_reasons):
            raise ValueError("negative spatial claim eligibility requires all evidence gates")
        return self


class MemoryPlaceWalkReading(FrozenContract):
    """한 산책이 한 장소에 대해 말할 수 있는 것과 말할 수 없는 것."""

    session_id: str = Field(min_length=1, max_length=128)
    walked_at: datetime
    precipitation: Literal["rain", "dry", "unknown"]
    daylight: Literal["day", "night", "unknown"]
    macro_exposure: MacroExposure
    capability: CapabilitySupport
    observation: PlaceObservation
    negative_spatial_claim: NegativeSpatialClaimAllowance
    observed_episode_count: int = Field(ge=0)
    member_pin_count: int = Field(ge=0)
    unjudgeable_reasons: tuple[UnjudgeableReason, ...] = ()

    _tz = field_validator("walked_at")(_timezone_required)

    @model_validator(mode="after")
    def reading_is_consistent(self) -> "MemoryPlaceWalkReading":
        if len(self.unjudgeable_reasons) != len(set(self.unjudgeable_reasons)):
            raise ValueError("unjudgeable reasons must be unique")
        if (
            self.negative_spatial_claim.macro_exposure is not self.macro_exposure
            or self.negative_spatial_claim.capability is not self.capability
        ):
            raise ValueError("negative spatial claim evidence must match the walk reading")
        expected_reasons: set[UnjudgeableReason] = set()
        if self.macro_exposure is MacroExposure.NOT_EXPOSED:
            expected_reasons.add(UnjudgeableReason.NOT_EXPOSED)
        elif self.macro_exposure is MacroExposure.UNCERTAIN:
            expected_reasons.add(UnjudgeableReason.EXPOSURE_UNCERTAIN)
        if self.capability is CapabilitySupport.UNSUPPORTED:
            expected_reasons.add(UnjudgeableReason.CAPABILITY_UNSUPPORTED)
        if (
            self.observation is PlaceObservation.NOT_OBSERVED
            and not self.negative_spatial_claim.eligible
        ):
            raise ValueError("not_observed requires negative spatial claim eligibility")
        drift_reason = {
            DriftAssessment.NOT_ASSESSED: UnjudgeableReason.SPATIAL_DRIFT_NOT_ASSESSED,
            DriftAssessment.INSUFFICIENT_EVIDENCE: (
                UnjudgeableReason.SPATIAL_DRIFT_INSUFFICIENT_EVIDENCE
            ),
            DriftAssessment.NOT_SUSPECTED: None,
            DriftAssessment.SUSPECTED: UnjudgeableReason.SPATIAL_DRIFT_SUSPECTED,
        }[self.negative_spatial_claim.drift_assessment]
        drift_reasons = {
            UnjudgeableReason.SPATIAL_DRIFT_NOT_ASSESSED,
            UnjudgeableReason.SPATIAL_DRIFT_INSUFFICIENT_EVIDENCE,
            UnjudgeableReason.SPATIAL_DRIFT_SUSPECTED,
        }
        present_drift_reasons = set(self.unjudgeable_reasons) & drift_reasons
        required_drift_reason = None
        if (
            self.negative_spatial_claim.drift_assessment is DriftAssessment.SUSPECTED
            or self.observed_episode_count == 0
            and not self.negative_spatial_claim.eligible
        ):
            required_drift_reason = drift_reason
        expected_drift_reasons = {required_drift_reason} if required_drift_reason else set()
        if present_drift_reasons != expected_drift_reasons:
            raise ValueError("drift reason must match the negative spatial claim evidence")
        allowed_reasons = expected_reasons | drift_reasons
        if not set(self.unjudgeable_reasons).issubset(allowed_reasons):
            raise ValueError("unjudgeable reasons must match the reading evidence")
        if self.observation is PlaceObservation.UNJUDGEABLE:
            if not self.unjudgeable_reasons:
                raise ValueError("unjudgeable observation requires at least one reason")
        elif self.unjudgeable_reasons:
            raise ValueError("judgeable observation cannot carry unjudgeable reasons")
        if not expected_reasons.issubset(self.unjudgeable_reasons):
            raise ValueError("exposure and capability failures must remain visible as reasons")
        if self.observation is PlaceObservation.OBSERVED and self.observed_episode_count == 0:
            raise ValueError("observed status requires an observed episode")
        if self.observation is PlaceObservation.NOT_OBSERVED and self.observed_episode_count:
            raise ValueError("not_observed status cannot carry an observed episode")
        return self


class MemoryPlaceClaimCount(FrozenContract):
    subject_role: SubjectRole
    meaning_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    vocabulary_version: int = Field(ge=1)
    pin_count: int = Field(ge=1)


class MemoryPlaceCohortSummary(FrozenContract):
    selected_walks: int = Field(ge=0)
    exposed_walks: int = Field(ge=0)
    not_exposed_walks: int = Field(ge=0)
    uncertain_exposure_walks: int = Field(ge=0)
    capability_supported_walks: int = Field(ge=0)
    capability_unsupported_walks: int = Field(ge=0)
    judgeable_walks: int = Field(ge=0)
    observed_walks: int = Field(ge=0)
    not_observed_walks: int = Field(ge=0)
    unjudgeable_walks: int = Field(ge=0)
    member_pin_count: int = Field(ge=0)
    distinct_member_walks: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_partition_the_cohort(self) -> "MemoryPlaceCohortSummary":
        if (
            self.exposed_walks + self.not_exposed_walks + self.uncertain_exposure_walks
            != self.selected_walks
        ):
            raise ValueError("exposure counts must partition selected walks")
        if (
            self.capability_supported_walks + self.capability_unsupported_walks
            != self.selected_walks
        ):
            raise ValueError("capability counts must partition selected walks")
        if self.judgeable_walks + self.unjudgeable_walks != self.selected_walks:
            raise ValueError("judgeability counts must partition selected walks")
        if self.observed_walks + self.not_observed_walks != self.judgeable_walks:
            raise ValueError("observation counts must partition judgeable walks")
        if self.distinct_member_walks > self.selected_walks:
            raise ValueError("member walk support cannot exceed selected walks")
        return self


class MemoryPlaceBiographyReceipt(FrozenContract):
    selector_fingerprint: str = Field(min_length=8, max_length=128)
    view_as_of: datetime
    total_capsules: int = Field(ge=0)
    exposure_policy_version: int = Field(ge=1)
    observation_policy_version: int = Field(ge=1)
    context_policy_version: int = Field(ge=1)
    quality_policy_version: int = Field(ge=1)
    paint_fp: str = Field(min_length=1, max_length=128)

    _tz = field_validator("view_as_of")(_timezone_required)


class MemoryPlaceTimelineEntry(FrozenContract):
    pin: EpisodePin
    attestation: WalkAttestation

    @model_validator(mode="after")
    def pin_and_attestation_match(self) -> "MemoryPlaceTimelineEntry":
        if self.pin.session_id != self.attestation.session_id:
            raise ValueError("timeline pin and attestation must belong to the same walk")
        if self.pin.created_by_attestation_id != self.attestation.attestation_id:
            raise ValueError("timeline pin must reference its attestation")
        return self


class MemoryPlaceBiography(FrozenContract):
    place: MemoryPlace
    spec: MemoryPlaceBiographySpec
    summary: MemoryPlaceCohortSummary
    readings: tuple[MemoryPlaceWalkReading, ...]
    timeline: tuple[MemoryPlaceTimelineEntry, ...]
    claim_counts: tuple[MemoryPlaceClaimCount, ...]
    receipt: MemoryPlaceBiographyReceipt

    @model_validator(mode="after")
    def biography_matches_place_and_cohort(self) -> "MemoryPlaceBiography":
        if self.place.dog_id != self.spec.walk_selector.dog_id:
            raise ValueError("place and walk selector must belong to the same dog")
        if len(self.readings) != self.summary.selected_walks:
            raise ValueError("one walk reading is required for every selected walk")
        return self


class PrecipitationBiographyComparison(FrozenContract):
    """같은 장소의 두 관찰 cohort. 인과 효과를 주장하지 않는다."""

    comparison_kind: Literal["observational"] = "observational"
    axis: Literal["precipitation"] = "precipitation"
    rain: MemoryPlaceBiography
    dry: MemoryPlaceBiography
    excluded_unknown_context_walks: int = Field(ge=0)

    @model_validator(mode="after")
    def cohorts_share_one_place_and_snapshot(self) -> "PrecipitationBiographyComparison":
        if self.rain.place.place_id != self.dry.place.place_id:
            raise ValueError("comparison cohorts must describe the same Memory Place")
        if self.rain.receipt.view_as_of != self.dry.receipt.view_as_of:
            raise ValueError("comparison cohorts must share one snapshot time")
        rain_values = {
            value
            for facet in self.rain.spec.walk_selector.context_facets
            if facet.axis == "precipitation"
            for value in facet.values
        }
        dry_values = {
            value
            for facet in self.dry.spec.walk_selector.context_facets
            if facet.axis == "precipitation"
            for value in facet.values
        }
        if rain_values != {"rain"} or dry_values != {"dry"}:
            raise ValueError("comparison cohorts must be rain and dry respectively")
        return self


class WalkJournalFacts(FrozenContract):
    """한 산책의 시간 투영에 필요한, 기존 WalkFacts의 좁은 읽기 형태."""

    started_at: datetime
    ended_at: datetime
    duration_s: int = Field(ge=0)
    moving_distance_m: int = Field(ge=0)
    moving_s: int = Field(ge=0)
    stop_count: int = Field(ge=0)
    stop_s: int = Field(ge=0)

    _tz = field_validator("started_at", "ended_at")(_timezone_required)

    @model_validator(mode="after")
    def facts_are_consistent(self) -> "WalkJournalFacts":
        if self.ended_at < self.started_at:
            raise ValueError("journal facts cannot end before they start")
        if self.moving_s + self.stop_s > self.duration_s:
            raise ValueError("journal moving and stop time cannot exceed duration")
        return self


class WalkJournalContextFacets(FrozenContract):
    """TrailContext 원자를 현재 context policy로 읽은 일기용 분류."""

    precipitation: Literal["rain", "dry", "unknown"]
    daylight: Literal["day", "night", "unknown"]
    policy_version: int = Field(ge=1)


class WalkJournalEntry(FrozenContract):
    """Pin과 증언을 잃지 않은 채 현재 정책으로 만든 한 문장."""

    pin: EpisodePin
    attestation: WalkAttestation
    narration: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def entry_matches_source(self) -> "WalkJournalEntry":
        if self.pin.session_id != self.attestation.session_id:
            raise ValueError("journal pin and attestation must belong to one walk")
        if self.pin.created_by_attestation_id != self.attestation.attestation_id:
            raise ValueError("journal pin must reference its attestation")
        return self


class WalkJournalReceipt(FrozenContract):
    projection_version: Literal[JOURNAL_PROJECTION_VERSION] = JOURNAL_PROJECTION_VERSION
    narration_policy_version: int = Field(ge=1)
    context_policy_version: int = Field(ge=1)
    capsule_version: int = Field(ge=1)
    generated_at: datetime
    pin_count: int = Field(ge=0)

    _tz = field_validator("generated_at")(_timezone_required)


class WalkJournalProjection(FrozenContract):
    """영구 Journal 원본 없이 Capsule·Context·Pin을 다시 읽은 한 산책의 일기."""

    session_id: str = Field(min_length=1, max_length=128)
    dog_id: str = Field(min_length=1, max_length=128)
    facts: WalkJournalFacts
    context: TrailContextSnapshot
    context_facets: WalkJournalContextFacets
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1_000)
    entries: tuple[WalkJournalEntry, ...]
    receipt: WalkJournalReceipt

    @model_validator(mode="after")
    def projection_matches_sources(self) -> "WalkJournalProjection":
        if self.context.session_id != self.session_id:
            raise ValueError("journal context must belong to its walk")
        if any(entry.pin.session_id != self.session_id for entry in self.entries):
            raise ValueError("journal entries must belong to its walk")
        if self.receipt.pin_count != len(self.entries):
            raise ValueError("journal receipt pin count must match entries")
        return self


class PublishedJournalSnapshot(FrozenContract):
    """사용자가 한 시점의 파생 일기를 제목·요약·대표 Pin과 함께 고정한 비공개 불변본."""

    snapshot_id: str = Field(min_length=1, max_length=128)
    snapshot_version: Literal[PUBLISHED_JOURNAL_SNAPSHOT_VERSION] = (
        PUBLISHED_JOURNAL_SNAPSHOT_VERSION
    )
    session_id: str = Field(min_length=1, max_length=128)
    visibility: Literal["private"] = "private"
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=5_000)
    selected_pin_ids: tuple[str, ...] = Field(default=(), max_length=100)
    source_projection_version: int = Field(ge=1)
    source_narration_policy_version: int = Field(ge=1)
    source_context_policy_version: int = Field(ge=1)
    source_capsule_version: int = Field(ge=1)
    published_at: datetime

    _tz = field_validator("published_at")(_timezone_required)

    @field_validator("title", "summary")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("published journal text cannot be blank")
        return value

    @field_validator("selected_pin_ids")
    @classmethod
    def selected_pins_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not pin_id or len(pin_id) > 128 for pin_id in value):
            raise ValueError("selected pin ids must be between 1 and 128 characters")
        if len(value) != len(set(value)):
            raise ValueError("selected pin ids must be unique")
        return value
