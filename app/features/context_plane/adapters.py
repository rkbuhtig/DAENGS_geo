"""TrailContext·MeasurementReceipt·외부 DogProfile을 타입 있는 Context Atom으로 바꾼다."""

from datetime import datetime

from app.context_plane.contract import (
    AccuracySummaryV1,
    ContextAtom,
    ContextAtomStatus,
    ContextCapabilityId,
    ContextSourceAuthority,
    ContextSpatialSupport,
    ContextTargetRef,
    ContextTemporalSupport,
    SubjectHealthFlag,
    SubjectProfileSnapshotV1,
    SubjectProfileTimeBasis,
    TrailWeatherObservationV1,
    WalkBreakCountsV1,
    WalkMeasurementObservationV1,
    WalkRejectionCountsV1,
)
from app.features.spatial_diary.contract import (
    ContextStatus,
    MeasurementReceipt,
    TrailContextSnapshot,
)
from app.profile.contract import DogProfile

_TRAIL_STATUS = {
    ContextStatus.CAPTURED: ContextAtomStatus.KNOWN,
    ContextStatus.PARTIAL: ContextAtomStatus.PARTIAL,
    ContextStatus.UNKNOWN: ContextAtomStatus.UNKNOWN,
    ContextStatus.FAILED: ContextAtomStatus.FETCH_FAILED,
}


def trail_context_atom(
    snapshot: TrailContextSnapshot,
    *,
    atom_id: str,
    target: ContextTargetRef,
    spatial_support: ContextSpatialSupport | None = None,
) -> ContextAtom:
    payload = None
    if snapshot.status in {ContextStatus.CAPTURED, ContextStatus.PARTIAL}:
        payload = TrailWeatherObservationV1(
            precipitation_mm=snapshot.precipitation_mm,
            temperature_c=snapshot.temperature_c,
            humidity_pct=snapshot.humidity_pct,
            sun_elevation_deg=snapshot.sun_elevation_deg,
        )
    return ContextAtom(
        atom_id=atom_id,
        capability_id=ContextCapabilityId.WORLD_TRAIL_WEATHER,
        schema_version=snapshot.context_version,
        target=target,
        status=_TRAIL_STATUS[snapshot.status],
        payload=payload,
        provider=snapshot.provider,
        source_authority=(
            ContextSourceAuthority.PROVIDER_OBSERVATION
            if snapshot.provider is not None
            else ContextSourceAuthority.SYSTEM_BOUNDARY
        ),
        source_observed_at=snapshot.source_observed_at,
        source_as_of=snapshot.walked_at,
        captured_at=snapshot.captured_at,
        spatial_support=spatial_support,
        temporal_support=ContextTemporalSupport(
            started_at=snapshot.walked_at,
            ended_at=snapshot.walked_at,
        ),
        failure_code="legacy_provider_failed" if snapshot.status is ContextStatus.FAILED else None,
    )


def measurement_receipt_atom(
    receipt: MeasurementReceipt,
    *,
    atom_id: str,
    target: ContextTargetRef,
    occurred_at: datetime,
    captured_at: datetime,
) -> ContextAtom:
    payload = WalkMeasurementObservationV1(
        receipt_version=receipt.receipt_version,
        evidence_origin=receipt.evidence_origin,
        received_fix_count=receipt.received_fix_count,
        accepted_fix_count=receipt.accepted_fix_count,
        rejection_counts=WalkRejectionCountsV1(
            low_accuracy=receipt.rejected_low_accuracy_count,
            out_of_order=receipt.rejected_out_of_order_count,
            before_start=receipt.rejected_before_start_count,
            after_end=receipt.rejected_after_end_count,
            capacity=receipt.dropped_at_capacity_count,
        ),
        break_counts=WalkBreakCountsV1(
            jump=receipt.jump_break_count,
            gap=receipt.gap_break_count,
            explicit=receipt.explicit_break_count,
        ),
        unknown_accuracy_count=receipt.unknown_accuracy_count,
        mock_fix_count=receipt.mock_fix_count,
        session_wall_time_s=receipt.session_wall_time_s,
        canonical_segment_time_s=receipt.canonical_segment_time_s,
        gap_elapsed_s=receipt.gap_elapsed_s,
        reported_accuracy=AccuracySummaryV1(
            count=receipt.reported_accuracy_count,
            p50_m=receipt.reported_accuracy_p50_m,
            p90_m=receipt.reported_accuracy_p90_m,
        ),
        accepted_accuracy=AccuracySummaryV1(
            count=receipt.accepted_accuracy_count,
            p50_m=receipt.accepted_accuracy_p50_m,
            p90_m=receipt.accepted_accuracy_p90_m,
        ),
        drift_assessment=receipt.drift_assessment,
        drift_assessment_method=receipt.drift_assessment_method,
    )
    return ContextAtom(
        atom_id=atom_id,
        capability_id=ContextCapabilityId.MEASUREMENT_WALK_QUALITY,
        schema_version=receipt.receipt_version,
        target=target,
        status=ContextAtomStatus.KNOWN,
        payload=payload,
        provider="walk_capsule",
        source_authority=ContextSourceAuthority.DEVICE_MEASUREMENT,
        source_ref=f"walk:{receipt.session_id}:measurement:v{receipt.receipt_version}",
        source_as_of=occurred_at,
        captured_at=captured_at,
        temporal_support=ContextTemporalSupport(started_at=occurred_at, ended_at=occurred_at),
    )


def dog_profile_snapshot_atom(
    profile: DogProfile,
    *,
    atom_id: str,
    target: ContextTargetRef,
    time_basis: SubjectProfileTimeBasis,
    effective_at: datetime,
    event_at: datetime,
    captured_at: datetime,
) -> ContextAtom:
    if effective_at > captured_at:
        raise ValueError("profile revision cannot become effective after capture")
    if time_basis is SubjectProfileTimeBasis.WALK_TIME and effective_at > event_at:
        raise ValueError("walk-time profile revision cannot become effective after the walk")
    try:
        health_flags = tuple(sorted({SubjectHealthFlag(flag) for flag in profile.health_flags}))
    except ValueError as exc:
        raise ValueError("dog profile contains an unregistered health flag") from exc
    payload = SubjectProfileSnapshotV1(
        dog_id=profile.dog_id,
        profile_version=profile.profile_version,
        time_basis=time_basis,
        effective_at=effective_at,
        birth_date=profile.birth_date,
        weight_kg=profile.weight_kg,
        size_class=profile.size_class,
        brachycephalic=profile.brachycephalic,
        health_flags=health_flags,
        activity_level=profile.activity_level,
    )
    return ContextAtom(
        atom_id=atom_id,
        capability_id=ContextCapabilityId.SUBJECT_DOG_PROFILE,
        schema_version=1,
        target=target,
        status=ContextAtomStatus.KNOWN,
        payload=payload,
        provider="external_dog_profile_contract",
        source_authority=ContextSourceAuthority.USER_ATTESTED_PROFILE,
        source_ref=f"dog:{profile.dog_id}:profile:v{profile.profile_version}",
        source_as_of=effective_at,
        captured_at=captured_at,
        temporal_support=ContextTemporalSupport(started_at=event_at, ended_at=event_at),
    )
