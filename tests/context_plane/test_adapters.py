from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.context_plane.contract import (
    ContextAtomStatus,
    ContextCapabilityId,
    ContextLensId,
    ContextRequest,
    ContextSpatialSupport,
    ContextTargetKind,
    ContextTargetRef,
    ContextUse,
    SubjectProfileTimeBasis,
)
from app.context_plane.facets import subject_age_at_event_facet, trail_weather_facets
from app.context_plane.registry import build_context_bundle, evidence_receipt
from app.features.context_plane.adapters import (
    dog_profile_snapshot_atom,
    measurement_receipt_atom,
    trail_context_atom,
)
from app.features.spatial_diary.contract import (
    ContextStatus,
    MeasurementReceipt,
    TrailContextSnapshot,
)
from app.profile.contract import DogProfile

WALKED_AT = datetime(2026, 8, 31, 11, 0, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
TARGET = ContextTargetRef(kind=ContextTargetKind.WALK, target_id="walk-1")


def receipt() -> MeasurementReceipt:
    return MeasurementReceipt(
        session_id="walk-1",
        evidence_origin="device",
        received_fix_count=10,
        accepted_fix_count=8,
        rejected_low_accuracy_count=1,
        rejected_out_of_order_count=1,
        rejected_before_start_count=0,
        rejected_after_end_count=0,
        unknown_accuracy_count=0,
        jump_break_count=1,
        gap_break_count=0,
        explicit_break_count=0,
        dropped_at_capacity_count=0,
        mock_fix_count=0,
        session_wall_time_s=600,
        canonical_segment_time_s=540,
        gap_elapsed_s=0,
        reported_accuracy_count=10,
        reported_accuracy_p50_m=6,
        reported_accuracy_p90_m=9,
        accepted_accuracy_count=8,
        accepted_accuracy_p50_m=5,
        accepted_accuracy_p90_m=8,
    )


def profile() -> DogProfile:
    return DogProfile(
        dog_id="dog-1",
        name="콩이",
        breed=[{"breed": "mixed", "ratio": 1}],
        birth_date=date(2020, 8, 31),
        sex="M",
        neutered=True,
        weight_kg=8,
        size_class="small",
        profile_version=4,
        health_flags=["joint"],
        activity_level="mid",
        temperament=["shy"],
        has_car=True,
    )


def test_trail_adapter_preserves_provider_times_support_and_unknown_state():
    captured = TrailContextSnapshot(
        session_id="walk-1",
        status=ContextStatus.PARTIAL,
        walked_at=WALKED_AT,
        source_observed_at=WALKED_AT,
        captured_at=CAPTURED_AT,
        provider="weather-api",
        precipitation_mm=1.2,
    )
    support = ContextSpatialSupport(kind="circle", lat=37.5, lng=127, radius_m=500)
    atom = trail_context_atom(
        captured,
        atom_id="weather-1",
        target=TARGET,
        spatial_support=support,
    )
    assert atom.status is ContextAtomStatus.PARTIAL
    assert atom.source_observed_at == WALKED_AT
    assert atom.spatial_support == support
    assert atom.payload is not None and atom.payload.precipitation_mm == 1.2

    unknown = trail_context_atom(
        TrailContextSnapshot(
            session_id="walk-1",
            status=ContextStatus.UNKNOWN,
            walked_at=WALKED_AT,
            captured_at=CAPTURED_AT,
        ),
        atom_id="weather-unknown",
        target=TARGET,
    )
    assert unknown.status is ContextAtomStatus.UNKNOWN
    assert unknown.payload is None
    assert all(facet.value.state == "unknown" for facet in trail_weather_facets(unknown))


def test_measurement_adapter_keeps_named_counts_not_a_confidence_score():
    atom = measurement_receipt_atom(
        receipt(),
        atom_id="measurement-1",
        target=TARGET,
        occurred_at=WALKED_AT,
        captured_at=CAPTURED_AT,
    )
    assert atom.capability_id is ContextCapabilityId.MEASUREMENT_WALK_QUALITY
    assert atom.payload is not None
    assert atom.payload.rejection_counts.low_accuracy == 1
    assert atom.payload.accepted_accuracy.p90_m == 8
    assert "confidence" not in atom.payload.model_dump()


def test_profile_adapter_freezes_minimum_values_and_age_at_walk_not_current_age():
    atom = dog_profile_snapshot_atom(
        profile(),
        atom_id="profile-1",
        target=TARGET,
        time_basis=SubjectProfileTimeBasis.WALK_TIME,
        effective_at=WALKED_AT,
        event_at=WALKED_AT,
        captured_at=CAPTURED_AT,
    )
    payload = atom.payload
    assert payload is not None
    assert set(payload.model_dump()) == {
        "payload_type",
        "dog_id",
        "profile_version",
        "time_basis",
        "effective_at",
        "birth_date",
        "weight_kg",
        "size_class",
        "brachycephalic",
        "health_flags",
        "activity_level",
    }
    assert subject_age_at_event_facet(atom, WALKED_AT).value.age_years == 6.0

    with pytest.raises(ValueError, match="cannot become effective after"):
        dog_profile_snapshot_atom(
            profile(),
            atom_id="future-profile",
            target=TARGET,
            time_basis=SubjectProfileTimeBasis.WALK_TIME,
            effective_at=CAPTURED_AT,
            event_at=WALKED_AT,
            captured_at=CAPTURED_AT,
        )

    unregistered = profile().model_copy(update={"health_flags": ["owner_anxious"]})
    with pytest.raises(ValueError, match="unregistered health flag"):
        dog_profile_snapshot_atom(
            unregistered,
            atom_id="private-profile",
            target=TARGET,
            time_basis=SubjectProfileTimeBasis.WALK_TIME,
            effective_at=WALKED_AT,
            event_at=WALKED_AT,
            captured_at=CAPTURED_AT,
        )


def test_walk_lens_rejects_current_profile_and_route_lens_accepts_only_current_profile():
    current_profile = dog_profile_snapshot_atom(
        profile(),
        atom_id="profile-current",
        target=TARGET,
        time_basis=SubjectProfileTimeBasis.CURRENT,
        effective_at=WALKED_AT,
        event_at=CAPTURED_AT,
        captured_at=CAPTURED_AT,
    )
    weather = trail_context_atom(
        TrailContextSnapshot(
            session_id="walk-1",
            status=ContextStatus.CAPTURED,
            walked_at=WALKED_AT,
            captured_at=CAPTURED_AT,
            provider="weather-api",
            temperature_c=20,
        ),
        atom_id="weather-1",
        target=TARGET,
    )
    walk_request = ContextRequest(
        request_id="journal",
        lens_id=ContextLensId.WALK_JOURNAL,
        target=TARGET,
        requested_capabilities=(
            ContextCapabilityId.WORLD_TRAIL_WEATHER,
            ContextCapabilityId.SUBJECT_DOG_PROFILE,
        ),
        occurred_at=WALKED_AT,
        requested_at=CAPTURED_AT,
    )
    with pytest.raises(ValueError, match="time basis"):
        build_context_bundle(
            bundle_id="bad-history",
            request=walk_request,
            atoms=(weather, current_profile),
            created_at=CAPTURED_AT,
        )

    route_target = ContextTargetRef(kind=ContextTargetKind.ROUTE_REQUEST, target_id="route-1")
    route_weather = weather.model_copy(update={"target": route_target})
    route_profile = current_profile.model_copy(update={"target": route_target})
    route_request = ContextRequest(
        request_id="route",
        lens_id=ContextLensId.ROUTE_RECOMMENDATION,
        target=route_target,
        requested_capabilities=(
            ContextCapabilityId.SUBJECT_DOG_PROFILE,
            ContextCapabilityId.WORLD_TRAIL_WEATHER,
        ),
        occurred_at=CAPTURED_AT,
        requested_at=CAPTURED_AT,
    )
    bundle = build_context_bundle(
        bundle_id="route-bundle",
        request=route_request,
        atoms=(route_profile, route_weather),
        created_at=CAPTURED_AT,
    )
    assert ContextUse.RECOMMEND in bundle.use_allowance.allowed
    assert ContextUse.SAFETY_GATE in bundle.use_allowance.prohibited
    assert ContextUse.CAUSAL_CLAIM in bundle.use_allowance.prohibited
    assert evidence_receipt(
        bundle,
        use=ContextUse.RECOMMEND,
        evidence_atom_ids=(route_profile.atom_id, route_weather.atom_id),
    )


def test_subject_age_facet_must_use_the_bundle_request_occurrence_time():
    walk_profile = dog_profile_snapshot_atom(
        profile(),
        atom_id="profile-walk",
        target=TARGET,
        time_basis=SubjectProfileTimeBasis.WALK_TIME,
        effective_at=WALKED_AT,
        event_at=WALKED_AT,
        captured_at=CAPTURED_AT,
    )
    weather = trail_context_atom(
        TrailContextSnapshot(
            session_id="walk-1",
            status=ContextStatus.UNKNOWN,
            walked_at=WALKED_AT,
            captured_at=CAPTURED_AT,
        ),
        atom_id="weather-unknown",
        target=TARGET,
    )
    request = ContextRequest(
        request_id="journal-wrong-age",
        lens_id=ContextLensId.WALK_JOURNAL,
        target=TARGET,
        requested_capabilities=(
            ContextCapabilityId.WORLD_TRAIL_WEATHER,
            ContextCapabilityId.SUBJECT_DOG_PROFILE,
        ),
        occurred_at=WALKED_AT,
        requested_at=CAPTURED_AT,
    )
    wrong_time = subject_age_at_event_facet(walk_profile, CAPTURED_AT)
    with pytest.raises(ValidationError, match="request occurrence time"):
        build_context_bundle(
            bundle_id="wrong-age-time",
            request=request,
            atoms=(weather, walk_profile),
            facets=(wrong_time,),
            created_at=CAPTURED_AT,
        )
