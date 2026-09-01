from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.context_plane.contract import (
    ContextAtom,
    ContextAtomStatus,
    ContextBundle,
    ContextCapabilityId,
    ContextFacet,
    ContextLensId,
    ContextRequest,
    ContextSourceAuthority,
    ContextTargetKind,
    ContextTargetRef,
    ContextTemporalSupport,
    ContextUse,
    ContextUseAllowance,
    SubjectAgeFacetValueV1,
    SubjectProfileSnapshotV1,
    SubjectProfileTimeBasis,
    TrailWeatherObservationV1,
)
from app.context_plane.facets import trail_weather_facets
from app.context_plane.registry import (
    build_context_bundle,
    evidence_receipt,
    validate_request,
    verify_context_bundle,
)

T0 = datetime(2026, 8, 31, 11, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
TARGET = ContextTargetRef(kind=ContextTargetKind.WALK, target_id="walk-1")


def weather_atom(*, atom_id: str = "weather-1", status=ContextAtomStatus.KNOWN) -> ContextAtom:
    payload = (
        TrailWeatherObservationV1(precipitation_mm=1.2, sun_elevation_deg=-8)
        if status in {ContextAtomStatus.KNOWN, ContextAtomStatus.PARTIAL}
        else None
    )
    return ContextAtom(
        atom_id=atom_id,
        capability_id=ContextCapabilityId.WORLD_TRAIL_WEATHER,
        schema_version=1,
        target=TARGET,
        status=status,
        payload=payload,
        provider="weather-fixture" if payload is not None else None,
        source_authority=ContextSourceAuthority.PROVIDER_OBSERVATION,
        source_as_of=T0,
        captured_at=T1,
        temporal_support=ContextTemporalSupport(started_at=T0, ended_at=T0),
    )


def journal_request(*, request_id: str = "request-1") -> ContextRequest:
    return ContextRequest(
        request_id=request_id,
        lens_id=ContextLensId.WALK_JOURNAL,
        target=TARGET,
        requested_capabilities=(ContextCapabilityId.WORLD_TRAIL_WEATHER,),
        occurred_at=T0,
        requested_at=T1,
    )


def test_registry_is_closed_to_private_thought_capabilities_and_free_text_payloads():
    with pytest.raises(ValidationError):
        ContextRequest(
            request_id="private-request",
            lens_id=ContextLensId.WALK_JOURNAL,
            target=TARGET,
            requested_capabilities=("subject.inner_thought",),
            occurred_at=T0,
            requested_at=T1,
        )

    with pytest.raises(ValidationError):
        TrailWeatherObservationV1(
            precipitation_mm=0,
            private_note="사실은 산책하기 싫었다",
        )


def test_atom_keeps_unknown_distinct_and_rejects_capability_payload_mismatch():
    unknown = weather_atom(status=ContextAtomStatus.NOT_FETCHED)
    assert unknown.payload is None
    assert unknown.status is ContextAtomStatus.NOT_FETCHED

    profile_payload = SubjectProfileSnapshotV1(
        dog_id="dog-1",
        profile_version=3,
        time_basis=SubjectProfileTimeBasis.WALK_TIME,
        effective_at=T0,
        birth_date=T0.date().replace(year=2020),
        weight_kg=8,
        size_class="small",
    )
    with pytest.raises(ValidationError, match="does not match typed payload"):
        ContextAtom(
            atom_id="bad",
            capability_id=ContextCapabilityId.WORLD_TRAIL_WEATHER,
            schema_version=1,
            target=TARGET,
            status=ContextAtomStatus.KNOWN,
            payload=profile_payload,
            provider="profile",
            source_authority=ContextSourceAuthority.USER_ATTESTED_PROFILE,
            captured_at=T1,
        )


def test_lens_requires_its_minimum_capability_and_rejects_unlisted_capability():
    request = ContextRequest(
        request_id="missing-weather",
        lens_id=ContextLensId.WALK_JOURNAL,
        target=TARGET,
        requested_capabilities=(ContextCapabilityId.MEASUREMENT_WALK_QUALITY,),
        occurred_at=T0,
        requested_at=T1,
    )
    with pytest.raises(ValueError, match="missing a lens-required"):
        validate_request(request)


def test_bundle_fingerprint_is_content_based_and_evidence_use_is_checked():
    atom = weather_atom()
    facets = trail_weather_facets(atom)
    first = build_context_bundle(
        bundle_id="bundle-a",
        request=journal_request(request_id="retry-request"),
        atoms=(atom,),
        facets=facets,
        created_at=T1,
    )
    retry = build_context_bundle(
        bundle_id="bundle-b",
        request=journal_request(),
        atoms=(atom,),
        facets=tuple(reversed(facets)),
        created_at=T1,
    )

    assert first.bundle_fingerprint == retry.bundle_fingerprint
    tampered = first.model_dump(mode="json")
    tampered["bundle_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        ContextBundle.model_validate(tampered)
    receipt = evidence_receipt(
        first,
        use=ContextUse.DESCRIBE,
        evidence_atom_ids=(atom.atom_id,),
    )
    assert receipt.bundle_fingerprint == first.bundle_fingerprint
    assert receipt.request_fingerprint == first.request.request_fingerprint

    with pytest.raises(ValueError, match="prohibited"):
        evidence_receipt(
            first,
            use=ContextUse.CAUSAL_CLAIM,
            evidence_atom_ids=(atom.atom_id,),
        )


def test_unknown_weather_facets_do_not_become_dry_or_day():
    precipitation, daylight = trail_weather_facets(
        weather_atom(status=ContextAtomStatus.UNKNOWN)
    )
    assert precipitation.value.state == "unknown"
    assert daylight.value.state == "unknown"


def test_bundle_contract_itself_cannot_be_forged_to_grant_causal_authority():
    atom = weather_atom()
    with pytest.raises(ValidationError, match="cannot grant causal or safety-gate"):
        ContextBundle(
            bundle_id="forged",
            request=journal_request(),
            lens_version=1,
            atoms=(atom,),
            use_allowance=ContextUseAllowance(
                allowed=(ContextUse.CAUSAL_CLAIM,),
                prohibited=tuple(use for use in ContextUse if use is not ContextUse.CAUSAL_CLAIM),
            ),
            created_at=T1,
        )


def test_facet_evidence_capability_must_match_its_typed_value():
    atom = weather_atom()
    wrong_facet = ContextFacet(
        facet_id="wrong-age",
        value=SubjectAgeFacetValueV1(age_years=6, at=T0),
        policy_version=1,
        evidence_atom_ids=(atom.atom_id,),
    )
    with pytest.raises(ValidationError, match="facet evidence capability"):
        ContextBundle(
            bundle_id="wrong-evidence",
            request=journal_request(),
            lens_version=1,
            atoms=(atom,),
            facets=(wrong_facet,),
            use_allowance=ContextUseAllowance(
                allowed=(ContextUse.DESCRIBE,),
                prohibited=tuple(use for use in ContextUse if use is not ContextUse.DESCRIBE),
            ),
            created_at=T1,
        )


def test_deserialized_bundle_must_be_reverified_against_the_lens_registry():
    atom = weather_atom()
    forged = ContextBundle(
        bundle_id="forged-recommend",
        request=journal_request(),
        lens_version=1,
        atoms=(atom,),
        use_allowance=ContextUseAllowance(
            allowed=(ContextUse.RECOMMEND,),
            prohibited=tuple(use for use in ContextUse if use is not ContextUse.RECOMMEND),
        ),
        created_at=T1,
    )
    round_tripped = ContextBundle.model_validate_json(forged.model_dump_json())
    with pytest.raises(ValueError, match="use allowance"):
        verify_context_bundle(round_tripped)
    with pytest.raises(ValueError, match="use allowance"):
        evidence_receipt(
            round_tripped,
            use=ContextUse.RECOMMEND,
            evidence_atom_ids=(atom.atom_id,),
        )

    wrong_version = forged.model_copy(update={"lens_version": 99})
    with pytest.raises(ValueError, match="lens version"):
        verify_context_bundle(wrong_version)
