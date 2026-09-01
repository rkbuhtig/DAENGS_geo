"""공간 일기 객체의 불변 경계와 상태 전이. Decision: #74."""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.features.spatial_diary.contract import (
    AttestedClaim,
    ClaimAllowance,
    ClaimSupport,
    ContextFacetFilter,
    ContextStatus,
    DriftAssessment,
    ElicitationMode,
    EntrySelector,
    EpisodeCandidate,
    EpisodeOfferSnapshot,
    EpisodePin,
    EventFootprint,
    EvidenceValue,
    GeoPoint,
    MeasurementReceipt,
    MemoryAction,
    ObservationCapability,
    OfferInteraction,
    OfferInteractionKind,
    PinOrigin,
    QualityPolicy,
    ReviewDisposition,
    SpatialDiaryViewReceipt,
    SpatialDiaryViewSpec,
    SubjectRole,
    TemporalPrecision,
    TrailContextSnapshot,
    WalkAttestation,
    WalkCapsuleManifest,
    WalkSelector,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
POINT = GeoPoint(lat=37.5, lng=127.0)
FOOTPRINT = EventFootprint(centre=POINT, radius_m=12)


def _receipt(**overrides) -> MeasurementReceipt:
    values = {
        "session_id": "walk-1",
        "evidence_origin": "device",
        "received_fix_count": 100,
        "accepted_fix_count": 90,
        "rejected_low_accuracy_count": 5,
        "rejected_out_of_order_count": 0,
        "rejected_before_start_count": 0,
        "rejected_after_end_count": 0,
        "unknown_accuracy_count": 0,
        "jump_break_count": 1,
        "gap_break_count": 1,
        "explicit_break_count": 0,
        "dropped_at_capacity_count": 0,
        "mock_fix_count": 0,
        "session_wall_time_s": 600,
        "canonical_segment_time_s": 520,
        "gap_elapsed_s": 65,
        "reported_accuracy_count": 100,
        "reported_accuracy_p50_m": 5,
        "reported_accuracy_p90_m": 42,
        "accepted_accuracy_count": 90,
        "accepted_accuracy_p50_m": 4,
        "accepted_accuracy_p90_m": 18,
    }
    values.update(overrides)
    return MeasurementReceipt(**values)


def _offer(**overrides) -> EpisodeOfferSnapshot:
    values = {
        "offer_id": "offer-1",
        "session_id": "walk-1",
        "source_observation_ids": ("walk-1:micro-v1:7",),
        "event_at": NOW,
        "representative_point": POINT,
        "event_footprint": FOOTPRINT,
        "evidence": (EvidenceValue(name="duration_s", value=42.0, unit="s"),),
        "candidate_policy_version": 1,
        "claim_policy_version": 1,
        "prompt_snapshot": "이 근처에서 42초 동안 천천히 움직였어요.",
        "offered_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return EpisodeOfferSnapshot(**values)


def _attestation(**overrides) -> WalkAttestation:
    values = {
        "attestation_id": "attestation-1",
        "session_id": "walk-1",
        "elicitation_mode": ElicitationMode.SYSTEM_OFFER,
        "offer_id": "offer-1",
        "review_disposition": ReviewDisposition.CONFIRMED,
        "claims": (
            AttestedClaim(
                subject_role=SubjectRole.DOG,
                meaning_code="exploration",
                vocabulary_version=1,
            ),
        ),
        "memory_action": MemoryAction.SAVE,
        "attested_at": NOW + timedelta(minutes=6),
    }
    values.update(overrides)
    return WalkAttestation(**values)


def test_capsule_manifest_is_a_frozen_unique_capability_receipt():
    manifest = WalkCapsuleManifest(
        session_id="walk-1",
        dog_id="dog-1",
        walk_record_version=4,
        walk_calculation_version=4,
        capabilities=(
            ObservationCapability(name="low_motion", generation=1),
            ObservationCapability(name="gap", generation=1),
        ),
        sealed_at=NOW,
    )
    with pytest.raises(ValidationError, match="frozen"):
        manifest.session_id = "walk-2"
    with pytest.raises(ValidationError, match="unique"):
        WalkCapsuleManifest(
            session_id="walk-1",
            dog_id="dog-1",
            walk_record_version=4,
            walk_calculation_version=4,
            capabilities=(
                ObservationCapability(name="low_motion", generation=1),
                ObservationCapability(name="low_motion", generation=1),
            ),
            sealed_at=NOW,
        )
    legacy_manifest = WalkCapsuleManifest(
        session_id="walk-legacy",
        dog_id="dog-1",
        walk_record_version=1,
        walk_calculation_version=1,
        capabilities=(),
        sealed_at=NOW,
    )
    assert legacy_manifest.capabilities == ()


def test_measurement_receipt_freezes_named_numerators_not_confidence_scores():
    receipt = _receipt()
    assert "accepted_time_ratio" not in type(receipt).model_fields
    assert "confidence_score" not in type(receipt).model_fields
    assert receipt.drift_assessment is DriftAssessment.NOT_ASSESSED
    with pytest.raises(ValidationError, match="accepted fixes"):
        _receipt(accepted_fix_count=101)
    with pytest.raises(ValidationError, match="p50 cannot exceed p90"):
        _receipt(reported_accuracy_p50_m=50, reported_accuracy_p90_m=10)
    with pytest.raises(ValidationError, match="assessment method"):
        _receipt(drift_assessment=DriftAssessment.SUSPECTED)


def test_raw_context_and_derived_claim_policy_are_separate_contracts():
    context = TrailContextSnapshot(
        session_id="walk-1",
        status=ContextStatus.CAPTURED,
        walked_at=NOW,
        source_observed_at=NOW,
        captured_at=NOW + timedelta(minutes=1),
        provider="fixture-weather",
        precipitation_mm=1.8,
        temperature_c=13.2,
    )
    allowance = ClaimAllowance(
        policy_version=2,
        evidence_ref="walk-1:micro-v1:7",
        temporal=ClaimSupport.SUPPORTED,
        spatial=ClaimSupport.APPROXIMATE,
        interpretation=ClaimSupport.ATTESTATION_REQUIRED,
    )
    assert context.precipitation_mm == 1.8
    assert allowance.spatial is ClaimSupport.APPROXIMATE
    with pytest.raises(ValidationError, match="unknown or failed context"):
        TrailContextSnapshot(
            session_id="walk-1",
            status=ContextStatus.UNKNOWN,
            walked_at=NOW,
            captured_at=NOW,
            precipitation_mm=0,
        )


def test_offer_snapshot_preserves_exactly_what_was_shown():
    candidate = EpisodeCandidate(
        session_id="walk-1",
        source_observation_ids=("walk-1:micro-v1:7",),
        event_at=NOW,
        representative_point=POINT,
        event_footprint=FOOTPRINT,
        evidence=(EvidenceValue(name="duration_s", value=42.0, unit="s"),),
        candidate_policy_version=1,
    )
    offer = _offer()
    assert candidate.model_dump().keys() < offer.model_dump().keys()
    assert offer.prompt_snapshot.startswith("이 근처")
    assert offer.source_observation_ids == ("walk-1:micro-v1:7",)
    with pytest.raises(ValidationError, match="evidence names"):
        _offer(
            evidence=(
                EvidenceValue(name="duration_s", value=42),
                EvidenceValue(name="duration_s", value=41),
            )
        )


def test_no_response_is_an_interaction_state_not_an_attestation():
    assert "skipped" not in {item.value for item in ReviewDisposition}
    viewed = OfferInteraction(
        interaction_id="interaction-1",
        offer_id="offer-1",
        kind=OfferInteractionKind.VIEWED,
        actor="user",
        occurred_at=NOW,
    )
    expired = OfferInteraction(
        interaction_id="interaction-2",
        offer_id="offer-1",
        kind=OfferInteractionKind.EXPIRED,
        actor="system",
        occurred_at=NOW,
    )
    assert viewed.kind is OfferInteractionKind.VIEWED
    assert expired.kind is OfferInteractionKind.EXPIRED
    with pytest.raises(ValidationError, match="only the system"):
        OfferInteraction(
            interaction_id="interaction-3",
            offer_id="offer-1",
            kind=OfferInteractionKind.EXPIRED,
            actor="user",
            occurred_at=NOW,
        )


def test_attestation_separates_review_from_memory_action():
    saved = _attestation()
    dismissed = _attestation(memory_action=MemoryAction.DISMISS)
    assert saved.review_disposition is dismissed.review_disposition
    assert saved.memory_action is MemoryAction.SAVE
    with pytest.raises(ValidationError, match="cannot be saved"):
        _attestation(
            review_disposition=ReviewDisposition.REJECTED,
            claims=(),
            memory_action=MemoryAction.SAVE,
        )
    uncertain_memory = _attestation(
        review_disposition=ReviewDisposition.UNCERTAIN,
        claims=(),
        memory_action=MemoryAction.SAVE,
    )
    assert uncertain_memory.memory_action is MemoryAction.SAVE
    duplicate_claim = AttestedClaim(
        subject_role=SubjectRole.DOG,
        meaning_code="exploration",
        vocabulary_version=1,
    )
    with pytest.raises(ValidationError, match="claims must be unique"):
        _attestation(claims=(duplicate_claim, duplicate_claim))


def test_manual_attestation_and_pin_do_not_require_a_system_offer():
    attestation = _attestation(
        elicitation_mode=ElicitationMode.POST_WALK_MANUAL,
        offer_id=None,
    )
    pin = EpisodePin(
        pin_id="pin-1",
        session_id="walk-1",
        origin=PinOrigin.POST_WALK_MANUAL,
        created_by_attestation_id=attestation.attestation_id,
        event_at=None,
        temporal_precision=TemporalPrecision.UNKNOWN,
        representative_point=POINT,
        event_footprint=FOOTPRINT,
        promoted_at=NOW + timedelta(minutes=10),
    )
    assert pin.source_offer_id is None
    with pytest.raises(ValidationError, match="system-offer pins"):
        EpisodePin(
            pin_id="pin-bad",
            session_id="walk-1",
            origin=PinOrigin.SYSTEM_OFFER,
            created_by_attestation_id=attestation.attestation_id,
            event_at=NOW,
            temporal_precision=TemporalPrecision.EXACT,
            representative_point=POINT,
            event_footprint=FOOTPRINT,
            promoted_at=NOW,
        )


def test_walk_and_entry_selectors_are_orthogonal_in_the_view_contract():
    spec = SpatialDiaryViewSpec(
        walk_selector=WalkSelector(
            dog_id="dog-1",
            since=date(2026, 9, 1),
            until=date(2026, 11, 30),
            context_facets=(
                ContextFacetFilter(axis="precipitation", values=("rain",), policy_version=1),
            ),
        ),
        entry_selector=EntrySelector(
            subject_roles=(SubjectRole.DOG,),
            meaning_codes=("exploration",),
        ),
        field_metric="walk_utilization",
        quality_policy=QualityPolicy(policy_version=1, name="diary_v1"),
    )
    assert spec.walk_selector.context_facets[0].values == ("rain",)
    assert spec.entry_selector.meaning_codes == ("exploration",)
    with pytest.raises(ValidationError, match="meaning codes must be unique"):
        EntrySelector(meaning_codes=("exploration", "exploration"))


def test_view_receipt_keeps_selected_and_contributing_denominators_visible():
    receipt = SpatialDiaryViewReceipt(
        selector_fingerprint="selector-1234",
        view_as_of=NOW,
        total_capsules=15,
        selected_capsules=9,
        contributing_capsules=8,
        context_known_count=8,
        context_unknown_count=1,
        pin_count=4,
        paint_fp="paint-v2-fixture",
        field_metric="walk_utilization",
        normalization="per_walk",
        context_policy_version=1,
        quality_policy_version=1,
        claim_policy_version=1,
    )
    assert (receipt.selected_capsules, receipt.contributing_capsules) == (9, 8)
    assert receipt.pin_count == 4
    invalid = receipt.model_dump()
    invalid["context_unknown_count"] = 0
    with pytest.raises(ValidationError, match="cover selected"):
        SpatialDiaryViewReceipt(**invalid)
