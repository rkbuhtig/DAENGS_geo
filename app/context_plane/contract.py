"""Context Plane v0의 불변 계약. Decision: #83.

임의 JSON이나 자연어를 담는 범용 봉투가 아니다. 등록된 객관·구조화 payload만 허용하며,
원천 Atom과 재계산 가능한 Facet, 목적별 Lens, 실제 소비 근거를 서로 다른 객체로 둔다.
"""

import hashlib
import json
import math
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTEXT_ATOM_VERSION = 1
CONTEXT_BUNDLE_VERSION = 1
CONTEXT_REGISTRY_VERSION = 1
CONTEXT_FACET_POLICY_VERSION = 1


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _timezone_required(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("context timestamps must include a timezone")
    return value


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class ContextNamespace(StrEnum):
    WORLD_DYNAMIC = "world.dynamic"
    WORLD_SPATIAL = "world.spatial"
    SUBJECT = "subject"
    ACTOR_SESSION = "actor_session"
    MEASUREMENT = "measurement"
    HISTORICAL = "historical"


class ContextCapabilityId(StrEnum):
    WORLD_TRAIL_WEATHER = "world.dynamic.trail_weather"
    SUBJECT_DOG_PROFILE = "subject.dog_profile"
    MEASUREMENT_WALK_QUALITY = "measurement.walk_quality"


class ContextAtomStatus(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NOT_FETCHED = "not_fetched"
    NOT_APPLICABLE = "not_applicable"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    CONFLICTED = "conflicted"


class ContextSourceAuthority(StrEnum):
    PROVIDER_OBSERVATION = "provider_observation"
    DEVICE_MEASUREMENT = "device_measurement"
    USER_ATTESTED_PROFILE = "user_attested_profile"
    EXTERNAL_PROFILE_REVISION = "external_profile_revision"
    SYSTEM_BOUNDARY = "system_boundary"


class ContextTargetKind(StrEnum):
    WALK = "walk"
    EPISODE = "episode"
    MEMORY_PLACE = "memory_place"
    SUBJECT = "subject"
    ROUTE_REQUEST = "route_request"


class ContextUse(StrEnum):
    FILTER = "filter"
    DESCRIBE = "describe"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    SAFETY_GATE = "safety_gate"
    CAUSAL_CLAIM = "causal_claim"


class ContextLensId(StrEnum):
    EPISODE_REVIEW = "episode_review"
    WALK_JOURNAL = "walk_journal"
    MEMORY_PLACE_BIOGRAPHY = "memory_place_biography"
    ROUTE_RECOMMENDATION = "route_recommendation"


class SubjectProfileTimeBasis(StrEnum):
    WALK_TIME = "walk_time"
    CURRENT = "current"


class SubjectHealthFlag(StrEnum):
    JOINT = "joint"
    HEART = "heart"
    OBESITY = "obesity"
    SENIOR = "senior"
    UNVACCINATED = "unvaccinated"


class ContextTargetRef(FrozenContract):
    kind: ContextTargetKind
    target_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )


class ContextSpatialSupport(FrozenContract):
    kind: Literal["point", "circle"] = "point"
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float | None = Field(default=None, gt=0, le=50_000)

    @model_validator(mode="after")
    def radius_matches_kind(self) -> "ContextSpatialSupport":
        if (self.kind == "circle") != (self.radius_m is not None):
            raise ValueError("circle support requires radius_m and point support forbids it")
        return self


class ContextTemporalSupport(FrozenContract):
    started_at: datetime
    ended_at: datetime

    _tz = field_validator("started_at", "ended_at")(_timezone_required)

    @model_validator(mode="after")
    def ordered(self) -> "ContextTemporalSupport":
        if self.ended_at < self.started_at:
            raise ValueError("context temporal support must be ordered")
        return self


class TrailWeatherObservationV1(FrozenContract):
    payload_type: Literal["trail_weather_v1"] = "trail_weather_v1"
    precipitation_mm: float | None = Field(default=None, ge=0)
    temperature_c: float | None = Field(default=None, ge=-100, le=100)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    sun_elevation_deg: float | None = Field(default=None, ge=-90, le=90)

    @model_validator(mode="after")
    def has_observation(self) -> "TrailWeatherObservationV1":
        if all(
            value is None
            for value in (
                self.precipitation_mm,
                self.temperature_c,
                self.humidity_pct,
                self.sun_elevation_deg,
            )
        ):
            raise ValueError("trail weather payload requires at least one observation")
        return self


class SubjectProfileSnapshotV1(FrozenContract):
    """판단에 실제 사용한 최소 profile 값. 이름·자유 서술·temperament는 복사하지 않는다."""

    payload_type: Literal["subject_profile_snapshot_v1"] = "subject_profile_snapshot_v1"
    dog_id: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    time_basis: SubjectProfileTimeBasis
    effective_at: datetime
    birth_date: date
    weight_kg: float = Field(gt=0, le=200)
    size_class: Literal["small", "medium", "large"]
    brachycephalic: bool | None = None
    health_flags: tuple[SubjectHealthFlag, ...] = ()
    activity_level: Literal["low", "mid", "high"] | None = None

    _tz = field_validator("effective_at")(_timezone_required)

    @field_validator("health_flags")
    @classmethod
    def unique_health_flags(
        cls, values: tuple[SubjectHealthFlag, ...]
    ) -> tuple[SubjectHealthFlag, ...]:
        if len(values) != len(set(values)):
            raise ValueError("subject health flags must be unique")
        return values


class SubjectProfileRevisionRefV1(FrozenContract):
    """외부 profile 원천이 불변 revision 조회를 보장할 때 쓰는 최소 참조."""

    payload_type: Literal["subject_profile_revision_ref_v1"] = "subject_profile_revision_ref_v1"
    dog_id: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    time_basis: SubjectProfileTimeBasis
    effective_at: datetime

    _tz = field_validator("effective_at")(_timezone_required)


class AccuracySummaryV1(FrozenContract):
    count: int = Field(ge=0)
    p50_m: float | None = Field(default=None, ge=0)
    p90_m: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def percentiles_match_count(self) -> "AccuracySummaryV1":
        if self.count == 0 and (self.p50_m is not None or self.p90_m is not None):
            raise ValueError("zero accuracy count cannot carry percentiles")
        if self.count > 0 and (self.p50_m is None or self.p90_m is None):
            raise ValueError("positive accuracy count requires percentiles")
        if self.p50_m is not None and self.p90_m is not None and self.p50_m > self.p90_m:
            raise ValueError("accuracy p50 cannot exceed p90")
        return self


class WalkRejectionCountsV1(FrozenContract):
    low_accuracy: int = Field(ge=0)
    out_of_order: int = Field(ge=0)
    before_start: int = Field(ge=0)
    after_end: int = Field(ge=0)
    capacity: int = Field(ge=0)


class WalkBreakCountsV1(FrozenContract):
    jump: int = Field(ge=0)
    gap: int = Field(ge=0)
    explicit: int = Field(ge=0)


class WalkMeasurementObservationV1(FrozenContract):
    payload_type: Literal["walk_measurement_v1"] = "walk_measurement_v1"
    receipt_version: int = Field(ge=1)
    evidence_origin: Literal["device", "mock", "mixed", "unknown"]
    received_fix_count: int = Field(ge=0)
    accepted_fix_count: int = Field(ge=0)
    rejection_counts: WalkRejectionCountsV1
    break_counts: WalkBreakCountsV1
    unknown_accuracy_count: int = Field(ge=0)
    mock_fix_count: int = Field(ge=0)
    session_wall_time_s: float = Field(ge=0)
    canonical_segment_time_s: float = Field(ge=0)
    gap_elapsed_s: float = Field(ge=0)
    reported_accuracy: AccuracySummaryV1
    accepted_accuracy: AccuracySummaryV1
    drift_assessment: Literal[
        "not_assessed", "insufficient_evidence", "not_suspected", "suspected"
    ]
    drift_assessment_method: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def measurement_is_consistent(self) -> "WalkMeasurementObservationV1":
        if self.accepted_fix_count > self.received_fix_count:
            raise ValueError("accepted fixes cannot exceed received fixes")
        if self.unknown_accuracy_count > self.accepted_fix_count:
            raise ValueError("unknown accuracy count cannot exceed accepted fixes")
        if self.mock_fix_count > self.received_fix_count:
            raise ValueError("mock fixes cannot exceed received fixes")
        if self.reported_accuracy.count > self.received_fix_count:
            raise ValueError("reported accuracy count cannot exceed received fixes")
        if self.accepted_accuracy.count > self.accepted_fix_count:
            raise ValueError("accepted accuracy count cannot exceed accepted fixes")
        if self.canonical_segment_time_s > self.session_wall_time_s + 1e-6:
            raise ValueError("canonical segment time cannot exceed session wall time")
        if self.gap_elapsed_s > self.session_wall_time_s + 1e-6:
            raise ValueError("gap elapsed time cannot exceed session wall time")
        if self.drift_assessment == "not_assessed":
            if self.drift_assessment_method is not None:
                raise ValueError("not_assessed drift cannot name a method")
        elif self.drift_assessment_method is None:
            raise ValueError("assessed drift requires a method")
        return self

ContextPayload = Annotated[
    TrailWeatherObservationV1
    | SubjectProfileSnapshotV1
    | SubjectProfileRevisionRefV1
    | WalkMeasurementObservationV1,
    Field(discriminator="payload_type"),
]


_PAYLOAD_CAPABILITY = {
    "trail_weather_v1": ContextCapabilityId.WORLD_TRAIL_WEATHER,
    "subject_profile_snapshot_v1": ContextCapabilityId.SUBJECT_DOG_PROFILE,
    "subject_profile_revision_ref_v1": ContextCapabilityId.SUBJECT_DOG_PROFILE,
    "walk_measurement_v1": ContextCapabilityId.MEASUREMENT_WALK_QUALITY,
}
_PAYLOAD_SCHEMA_VERSION = {payload_type: 1 for payload_type in _PAYLOAD_CAPABILITY}
_PAYLOAD_STATUSES = {ContextAtomStatus.KNOWN, ContextAtomStatus.PARTIAL}
_FAILED_STATUSES = {ContextAtomStatus.FETCH_FAILED, ContextAtomStatus.PARSE_FAILED}


class ContextAtom(FrozenContract):
    atom_version: Literal[CONTEXT_ATOM_VERSION] = CONTEXT_ATOM_VERSION
    atom_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    capability_id: ContextCapabilityId
    schema_version: int = Field(ge=1)
    target: ContextTargetRef
    status: ContextAtomStatus
    payload: ContextPayload | None = None
    provider: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    source_authority: ContextSourceAuthority
    source_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/#@-]*$",
    )
    source_observed_at: datetime | None = None
    source_as_of: datetime | None = None
    captured_at: datetime
    spatial_support: ContextSpatialSupport | None = None
    temporal_support: ContextTemporalSupport | None = None
    failure_code: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$"
    )

    _tz = field_validator("captured_at")(_timezone_required)
    _optional_tz = field_validator("source_observed_at", "source_as_of")(
        lambda value: value if value is None else _timezone_required(value)
    )

    @model_validator(mode="after")
    def status_and_payload_match(self) -> "ContextAtom":
        if (self.status in _PAYLOAD_STATUSES) != (self.payload is not None):
            raise ValueError("known/partial atoms require payload and other statuses forbid it")
        if self.payload is not None:
            expected = _PAYLOAD_CAPABILITY[self.payload.payload_type]
            if expected is not self.capability_id:
                raise ValueError("context capability does not match typed payload")
            if self.schema_version != _PAYLOAD_SCHEMA_VERSION[self.payload.payload_type]:
                raise ValueError("context schema version does not match typed payload")
            if self.provider is None:
                raise ValueError("known/partial atoms require a provider")
        if (self.status in _FAILED_STATUSES) != (self.failure_code is not None):
            raise ValueError("provider failure statuses require a bounded failure_code only")
        if self.source_observed_at is not None and self.source_observed_at > self.captured_at:
            raise ValueError("source observation cannot occur after context capture")
        return self


class PrecipitationFacetValueV1(FrozenContract):
    value_type: Literal["precipitation_state_v1"] = "precipitation_state_v1"
    state: Literal["rain", "dry", "unknown"]


class DaylightFacetValueV1(FrozenContract):
    value_type: Literal["daylight_state_v1"] = "daylight_state_v1"
    state: Literal["day", "night", "unknown"]


class SubjectAgeFacetValueV1(FrozenContract):
    value_type: Literal["subject_age_at_event_v1"] = "subject_age_at_event_v1"
    age_years: float = Field(ge=0, le=40)
    at: datetime

    _tz = field_validator("at")(_timezone_required)


class MeasurementDriftFacetValueV1(FrozenContract):
    value_type: Literal["measurement_drift_v1"] = "measurement_drift_v1"
    assessment: Literal[
        "not_assessed", "insufficient_evidence", "not_suspected", "suspected"
    ]


ContextFacetValue = Annotated[
    PrecipitationFacetValueV1
    | DaylightFacetValueV1
    | SubjectAgeFacetValueV1
    | MeasurementDriftFacetValueV1,
    Field(discriminator="value_type"),
]

_FACET_EVIDENCE_CAPABILITY = {
    "precipitation_state_v1": ContextCapabilityId.WORLD_TRAIL_WEATHER,
    "daylight_state_v1": ContextCapabilityId.WORLD_TRAIL_WEATHER,
    "subject_age_at_event_v1": ContextCapabilityId.SUBJECT_DOG_PROFILE,
    "measurement_drift_v1": ContextCapabilityId.MEASUREMENT_WALK_QUALITY,
}


class ContextFacet(FrozenContract):
    facet_id: str = Field(
        min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
    )
    value: ContextFacetValue
    policy_version: int = Field(ge=1)
    evidence_atom_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_is_unique(self) -> "ContextFacet":
        if len(self.evidence_atom_ids) != len(set(self.evidence_atom_ids)):
            raise ValueError("facet evidence atom ids must be unique")
        return self


class ContextCapabilitySpec(FrozenContract):
    capability_id: ContextCapabilityId
    namespace: ContextNamespace
    payload_types: tuple[str, ...] = Field(min_length=1)
    allowed_uses: tuple[ContextUse, ...]


class ContextLensSpec(FrozenContract):
    lens_id: ContextLensId
    lens_version: int = Field(ge=1)
    required_capabilities: tuple[ContextCapabilityId, ...]
    optional_capabilities: tuple[ContextCapabilityId, ...]
    allowed_uses: tuple[ContextUse, ...]
    subject_profile_time_basis: SubjectProfileTimeBasis | None = None

    @model_validator(mode="after")
    def capabilities_do_not_overlap(self) -> "ContextLensSpec":
        required = set(self.required_capabilities)
        optional = set(self.optional_capabilities)
        if required & optional:
            raise ValueError("lens required and optional capabilities cannot overlap")
        return self


class ContextRequest(FrozenContract):
    request_id: str = Field(min_length=1, max_length=128)
    lens_id: ContextLensId
    target: ContextTargetRef
    requested_capabilities: tuple[ContextCapabilityId, ...] = Field(min_length=1)
    occurred_at: datetime
    requested_at: datetime
    request_fingerprint: str = Field(default="", pattern=r"^[0-9a-f]{64}$")

    _tz = field_validator("occurred_at", "requested_at")(_timezone_required)

    @model_validator(mode="after")
    def capabilities_are_unique(self) -> "ContextRequest":
        if len(self.requested_capabilities) != len(set(self.requested_capabilities)):
            raise ValueError("requested context capabilities must be unique")
        material = self.model_dump(mode="json", exclude={"request_id", "request_fingerprint"})
        material["requested_capabilities"] = sorted(material["requested_capabilities"])
        expected = _fingerprint(material)
        if self.request_fingerprint and self.request_fingerprint != expected:
            raise ValueError("request fingerprint does not match its normalized content")
        object.__setattr__(self, "request_fingerprint", expected)
        return self


class ContextUseAllowance(FrozenContract):
    allowed: tuple[ContextUse, ...]
    prohibited: tuple[ContextUse, ...]

    @model_validator(mode="after")
    def complete_partition(self) -> "ContextUseAllowance":
        allowed, prohibited = set(self.allowed), set(self.prohibited)
        if len(allowed) != len(self.allowed) or len(prohibited) != len(self.prohibited):
            raise ValueError("context uses must be unique")
        if allowed & prohibited or allowed | prohibited != set(ContextUse):
            raise ValueError("context use allowance must partition every known use")
        return self


class ContextBundle(FrozenContract):
    bundle_version: Literal[CONTEXT_BUNDLE_VERSION] = CONTEXT_BUNDLE_VERSION
    bundle_id: str = Field(min_length=1, max_length=128)
    request: ContextRequest
    registry_version: Literal[CONTEXT_REGISTRY_VERSION] = CONTEXT_REGISTRY_VERSION
    lens_version: int = Field(ge=1)
    atoms: tuple[ContextAtom, ...] = Field(min_length=1)
    facets: tuple[ContextFacet, ...] = ()
    use_allowance: ContextUseAllowance
    created_at: datetime
    bundle_fingerprint: str = Field(default="", pattern=r"^[0-9a-f]{64}$")

    _tz = field_validator("created_at")(_timezone_required)

    @model_validator(mode="after")
    def bundle_is_closed_and_traceable(self) -> "ContextBundle":
        atom_ids = [atom.atom_id for atom in self.atoms]
        if len(atom_ids) != len(set(atom_ids)):
            raise ValueError("context atom ids must be unique inside a bundle")
        facet_ids = [facet.facet_id for facet in self.facets]
        if len(facet_ids) != len(set(facet_ids)):
            raise ValueError("context facet ids must be unique inside a bundle")
        requested = set(self.request.requested_capabilities)
        actual = {atom.capability_id for atom in self.atoms}
        if actual != requested:
            raise ValueError("bundle must resolve every requested capability and no others")
        if any(atom.target != self.request.target for atom in self.atoms):
            raise ValueError("all context atoms must belong to the request target")
        atoms_by_id = {atom.atom_id: atom for atom in self.atoms}
        known_atom_ids = set(atoms_by_id)
        if any(not set(facet.evidence_atom_ids) <= known_atom_ids for facet in self.facets):
            raise ValueError("facet evidence must refer to atoms in the same bundle")
        for facet in self.facets:
            expected_capability = _FACET_EVIDENCE_CAPABILITY[facet.value.value_type]
            evidence_capabilities = {
                atoms_by_id[atom_id].capability_id for atom_id in facet.evidence_atom_ids
            }
            if evidence_capabilities != {expected_capability}:
                raise ValueError("facet evidence capability does not match its typed value")
            if (
                isinstance(facet.value, SubjectAgeFacetValueV1)
                and facet.value.at != self.request.occurred_at
            ):
                raise ValueError("subject age facet must use the request occurrence time")
        if self.created_at < self.request.requested_at:
            raise ValueError("context bundle cannot precede its request")
        if {
            ContextUse.CAUSAL_CLAIM,
            ContextUse.SAFETY_GATE,
        } & set(self.use_allowance.allowed):
            raise ValueError("context bundle v0 cannot grant causal or safety-gate authority")
        material = self.model_dump(
            mode="json", exclude={"bundle_id", "bundle_fingerprint"}
        )
        material["request"]["requested_capabilities"] = sorted(
            material["request"]["requested_capabilities"]
        )
        material["request"].pop("request_id")
        material["atoms"] = sorted(material["atoms"], key=lambda item: item["atom_id"])
        material["facets"] = sorted(material["facets"], key=lambda item: item["facet_id"])
        material["use_allowance"]["allowed"] = sorted(material["use_allowance"]["allowed"])
        material["use_allowance"]["prohibited"] = sorted(material["use_allowance"]["prohibited"])
        expected = _fingerprint(material)
        if self.bundle_fingerprint and self.bundle_fingerprint != expected:
            raise ValueError("bundle fingerprint does not match its normalized content")
        object.__setattr__(self, "bundle_fingerprint", expected)
        return self


class ContextEvidenceReceipt(FrozenContract):
    bundle_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_version: int = Field(ge=1)
    lens_id: ContextLensId
    lens_version: int = Field(ge=1)
    use: ContextUse
    evidence_atom_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_atom_ids")
    @classmethod
    def unique_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("context evidence atom ids must be unique")
        return values


def finite_number(value: float) -> float:
    """Adapter가 외부 숫자를 payload에 넣기 전에 쓸 수 있는 공용 방어."""

    if not math.isfinite(value):
        raise ValueError("context numbers must be finite")
    return value
