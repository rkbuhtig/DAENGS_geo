"""서로 다른 산책의 Pin이 안정 장소 biography와 첫 조건 비교로 이어진다."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.features.spatial_diary.contract import (
    AttestedClaim,
    ContextStatus,
    DriftAssessment,
    EntrySelector,
    MemoryAction,
    MemoryPlaceBiographySpec,
    MemoryPlaceMembershipOrigin,
    PlaceObservation,
    QualityPolicy,
    ReviewDisposition,
    SubjectRole,
    TrailContextSnapshot,
    UnjudgeableReason,
    WalkSelector,
)
from app.features.spatial_diary.episode import (
    attest_episode_offer,
    correct_pin_attestation,
    list_episode_candidates,
    put_episode_offer,
)
from app.features.territory.memory_place import (
    MemoryPlaceConflictError,
    compare_memory_place_precipitation,
    get_memory_place,
    list_memory_place_memberships,
    list_memory_places,
    put_memory_place,
    put_memory_place_membership,
    query_memory_place_biography,
)
from app.features.walk import store
from app.features.walk.capsule import build_capsule_artifacts, trail_context_request
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkSession
from app.features.walk.observation import MicroObservation
from tests.conftest import TEST_ORIGIN, WALK_T0, db_session, walk_fix

DOG_ID = "dog-memory-place"
PREFIX = "test:memory-place:"


async def _cleanup(db):
    await db.rollback()
    await db.execute(
        text("DELETE FROM walk_session WHERE id LIKE :prefix"), {"prefix": f"{PREFIX}%"}
    )
    await db.execute(
        text("DELETE FROM spatial_diary_memory_place WHERE dog_id = :dog_id"),
        {"dog_id": DOG_ID},
    )
    await db.commit()


async def _seal_walk(
    db,
    name: str,
    day: int,
    *,
    precipitation_mm: float | None,
    observed: bool,
    drift_assessment: DriftAssessment = DriftAssessment.NOT_SUSPECTED,
) -> str:
    session_id = f"{PREFIX}{name}"
    started_at = WALK_T0 + timedelta(days=day)
    ended_at = started_at + timedelta(seconds=40)
    await store.upsert_session(
        db,
        WalkSession(id=session_id, dog_id=DOG_ID, started_at=started_at),
    )
    base = [walk_fix(second, second * 0.6) for second in range(0, 41, 5)]
    fixes = [
        fix.model_copy(update={"at": started_at + timedelta(seconds=index * 5)})
        for index, fix in enumerate(base)
    ]
    await store.append_fixes(db, session_id, fixes)
    loaded = await store.load_fixes_ordered(db, session_id)
    computed = compute_facts(session_id, DOG_ID, started_at, ended_at, loaded)
    observations = []
    if observed:
        observations.append(
            MicroObservation(
                session_id=session_id,
                index=0,
                kind="slow",
                started_at=started_at + timedelta(seconds=10),
                ended_at=started_at + timedelta(seconds=30),
                duration_s=20,
                lat=TEST_ORIGIN[0],
                lng=TEST_ORIGIN[1],
                path_m=4,
                net_m=2,
                span_m=4,
                fix_count=21,
                accuracy_p50_m=8,
                route_offset_m=6,
                chain_index=0,
                abuts_break=False,
            )
        )
    request = trail_context_request(computed.facts, computed.trail)
    captured_at = ended_at + timedelta(seconds=1)
    if precipitation_mm is None:
        context = TrailContextSnapshot(
            session_id=session_id,
            status=ContextStatus.UNKNOWN,
            walked_at=request.walked_at,
            captured_at=captured_at,
        )
    else:
        context = TrailContextSnapshot(
            session_id=session_id,
            status=ContextStatus.CAPTURED,
            walked_at=request.walked_at,
            captured_at=captured_at,
            provider="fixture-weather",
            precipitation_mm=precipitation_mm,
            sun_elevation_deg=10,
        )
    capsule = build_capsule_artifacts(
        computed.facts,
        computed.trail,
        computed.receipt_input,
        context,
        sealed_at=captured_at + timedelta(seconds=1),
    )
    capsule = replace(
        capsule,
        measurement_receipt=capsule.measurement_receipt.model_copy(
            update={
                "drift_assessment": drift_assessment,
                "drift_assessment_method": (
                    None
                    if drift_assessment is DriftAssessment.NOT_ASSESSED
                    else "fixture_drift_screen_v1"
                ),
            }
        ),
    )
    await store.finalize(
        db,
        computed.facts,
        computed.trail.quality,
        computed.events,
        observations=observations,
        capsule=capsule,
    )
    return session_id


async def _pin(db, session_id: str, suffix: str) -> str:
    candidate = (await list_episode_candidates(db, session_id))[0].candidate
    offer = await put_episode_offer(
        db,
        offer_id=f"offer-memory-place-{suffix}",
        session_id=session_id,
        source_observation_id=candidate.source_observation_ids[0],
        candidate_policy_version=1,
        offered_at=candidate.event_at + timedelta(minutes=1),
    )
    pin_id = f"pin-memory-place-{suffix}"
    await attest_episode_offer(
        db,
        offer_id=offer.offer_id,
        attestation_id=f"attestation-memory-place-{suffix}",
        review_disposition=ReviewDisposition.CONFIRMED,
        claims=(
            AttestedClaim(
                subject_role=SubjectRole.DOG,
                meaning_code="exploration",
                vocabulary_version=1,
            ),
        ),
        memory_action=MemoryAction.SAVE,
        pin_id=pin_id,
        attested_at=candidate.event_at + timedelta(minutes=2),
    )
    return pin_id


def _spec() -> MemoryPlaceBiographySpec:
    return MemoryPlaceBiographySpec(
        walk_selector=WalkSelector(dog_id=DOG_ID),
        entry_selector=EntrySelector(),
        quality_policy=QualityPolicy(policy_version=1, name="diary_v1"),
    )


async def test_memory_place_biography_and_rain_dry_comparison_keep_denominators():
    async with db_session() as db:
        await _cleanup(db)
        try:
            rain = await _seal_walk(db, "rain-observed", 0, precipitation_mm=2.0, observed=True)
            dry_observed = await _seal_walk(
                db, "dry-observed", 1, precipitation_mm=0, observed=True
            )
            dry_not_observed = await _seal_walk(
                db, "dry-not-observed", 2, precipitation_mm=0, observed=False
            )
            unknown = await _seal_walk(
                db, "unknown", 3, precipitation_mm=None, observed=False
            )
            await db.commit()

            rain_pin = await _pin(db, rain, "rain")
            dry_pin = await _pin(db, dry_observed, "dry")
            await db.commit()

            place_result = await put_memory_place(
                db,
                place_id="memory-place-stream-grass",
                dog_id=DOG_ID,
                seed_pin_ids=(rain_pin, dry_pin),
                label="하천 풀밭",
                created_at=WALK_T0 + timedelta(days=5),
            )
            same_place = await put_memory_place(
                db,
                place_id="memory-place-stream-grass",
                dog_id=DOG_ID,
                seed_pin_ids=(rain_pin, dry_pin),
                label="하천 풀밭",
            )
            assert same_place == place_result
            assert len({item.session_id for item in place_result.memberships}) == 2
            assert await list_memory_places(db, DOG_ID) == (place_result.place,)
            await db.commit()

            biography = await query_memory_place_biography(db, place_result.place.place_id, _spec())
            assert biography.place.label == "하천 풀밭"
            assert biography.summary.selected_walks == 4
            assert biography.summary.exposed_walks == 4
            assert biography.summary.judgeable_walks == 4
            assert biography.summary.observed_walks == 2
            assert biography.summary.not_observed_walks == 2
            assert biography.summary.member_pin_count == 2
            assert biography.summary.distinct_member_walks == 2
            assert biography.claim_counts[0].meaning_code == "exploration"
            assert biography.claim_counts[0].pin_count == 2
            assert all(
                reading.observation is not PlaceObservation.UNJUDGEABLE
                for reading in biography.readings
            )
            assert all(
                reading.negative_spatial_claim.eligible for reading in biography.readings
            )
            await db.rollback()

            await correct_pin_attestation(
                db,
                pin_id=rain_pin,
                attestation_id="attestation-memory-place-rain-correction",
                supersedes_attestation_id="attestation-memory-place-rain",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(
                    AttestedClaim(
                        subject_role=SubjectRole.OWNER,
                        meaning_code="owner_pause",
                        vocabulary_version=1,
                    ),
                ),
            )
            await db.commit()
            corrected_biography = await query_memory_place_biography(
                db, place_result.place.place_id, _spec()
            )
            current_claims = {
                (item.subject_role, item.meaning_code): item.pin_count
                for item in corrected_biography.claim_counts
            }
            assert current_claims == {
                (SubjectRole.DOG, "exploration"): 1,
                (SubjectRole.OWNER, "owner_pause"): 1,
            }
            corrected_entry = next(
                item for item in corrected_biography.timeline if item.pin.pin_id == rain_pin
            )
            assert corrected_entry.attestation.attestation_id == (
                "attestation-memory-place-rain-correction"
            )
            await db.rollback()

            comparison = await compare_memory_place_precipitation(
                db,
                place_result.place.place_id,
                _spec(),
            )
            assert comparison.comparison_kind == "observational"
            assert comparison.rain.summary.selected_walks == 1
            assert comparison.rain.summary.observed_walks == 1
            assert comparison.dry.summary.selected_walks == 2
            assert comparison.dry.summary.observed_walks == 1
            assert comparison.dry.summary.not_observed_walks == 1
            assert comparison.excluded_unknown_context_walks == 1
            await db.rollback()

            # 노출 재료가 없어진 산책은 low_motion=0의 분모가 아니라 unjudgeable로 남는다.
            await db.execute(
                text("DELETE FROM walk_cellophane_cell WHERE session_id = :session_id"),
                {"session_id": unknown},
            )
            await db.commit()
            conservative = await query_memory_place_biography(
                db, place_result.place.place_id, _spec()
            )
            assert conservative.summary.selected_walks == 4
            assert conservative.summary.judgeable_walks == 3
            assert conservative.summary.unjudgeable_walks == 1
            assert conservative.summary.not_observed_walks == 1
            unknown_reading = next(
                item for item in conservative.readings if item.session_id == unknown
            )
            assert unknown_reading.observation is PlaceObservation.UNJUDGEABLE
            assert unknown_reading.unjudgeable_reasons == (
                UnjudgeableReason.NOT_EXPOSED,
            )
            await db.rollback()

            await db.execute(
                text("""
                    UPDATE walk_capsule_manifest
                    SET capabilities = CAST(:capabilities AS jsonb)
                    WHERE session_id = :session_id
                """),
                {
                    "session_id": dry_not_observed,
                    "capabilities": json.dumps([{"name": "gap", "generation": 1}]),
                },
            )
            await db.commit()
            capability_aware = await query_memory_place_biography(
                db, place_result.place.place_id, _spec()
            )
            unsupported = next(
                item
                for item in capability_aware.readings
                if item.session_id == dry_not_observed
            )
            assert unsupported.observation is PlaceObservation.UNJUDGEABLE
            assert unsupported.unjudgeable_reasons == (
                UnjudgeableReason.CAPABILITY_UNSUPPORTED,
            )
            assert capability_aware.summary.not_observed_walks == 0
            await db.rollback()

            await db.execute(
                text("""
                    UPDATE walk_capsule_manifest
                    SET capabilities = CAST(:capabilities AS jsonb)
                    WHERE session_id = :session_id
                """),
                {
                    "session_id": dry_not_observed,
                    "capabilities": json.dumps(
                        [
                            {"name": "low_motion", "generation": 1},
                            {"name": "gap", "generation": 1},
                        ]
                    ),
                },
            )
            await db.execute(
                text("""
                    UPDATE walk_measurement_receipt
                    SET drift_assessment = 'suspected',
                        drift_assessment_method = 'fixture_drift_v1'
                    WHERE session_id = :session_id
                """),
                {"session_id": dry_not_observed},
            )
            await db.commit()
            drift_aware = await query_memory_place_biography(
                db, place_result.place.place_id, _spec()
            )
            suspected = next(
                item for item in drift_aware.readings if item.session_id == dry_not_observed
            )
            assert suspected.observation is PlaceObservation.UNJUDGEABLE
            assert suspected.unjudgeable_reasons == (
                UnjudgeableReason.SPATIAL_DRIFT_SUSPECTED,
            )
        finally:
            await _cleanup(db)


async def test_negative_spatial_claim_requires_an_active_not_suspected_assessment():
    async with db_session() as db:
        await _cleanup(db)
        try:
            observed = await _seal_walk(
                db,
                "negative-policy-observed",
                0,
                precipitation_mm=0,
                observed=True,
                drift_assessment=DriftAssessment.NOT_ASSESSED,
            )
            absent = await _seal_walk(
                db,
                "negative-policy-absent",
                1,
                precipitation_mm=0,
                observed=False,
                drift_assessment=DriftAssessment.NOT_ASSESSED,
            )
            await db.commit()

            observed_pin = await _pin(db, observed, "negative-policy-observed")
            # Memory Place v0 requires two distinct Pin walks. The second seed supplies identity;
            # the policy probe still uses the no-observation walk above as its negative case.
            seed_walk = await _seal_walk(
                db,
                "negative-policy-seed",
                2,
                precipitation_mm=0,
                observed=True,
            )
            await db.commit()
            seed_pin = await _pin(db, seed_walk, "negative-policy-seed")
            await db.commit()
            place = await put_memory_place(
                db,
                place_id="memory-place-negative-policy",
                dog_id=DOG_ID,
                seed_pin_ids=(observed_pin, seed_pin),
            )
            await db.commit()

            cases = (
                (
                    DriftAssessment.NOT_ASSESSED,
                    PlaceObservation.UNJUDGEABLE,
                    (UnjudgeableReason.SPATIAL_DRIFT_NOT_ASSESSED,),
                    False,
                    0,
                ),
                (
                    DriftAssessment.INSUFFICIENT_EVIDENCE,
                    PlaceObservation.UNJUDGEABLE,
                    (UnjudgeableReason.SPATIAL_DRIFT_INSUFFICIENT_EVIDENCE,),
                    False,
                    0,
                ),
                (
                    DriftAssessment.NOT_SUSPECTED,
                    PlaceObservation.NOT_OBSERVED,
                    (),
                    True,
                    1,
                ),
            )
            for index, (assessment, observation, reasons, eligible, absent_count) in enumerate(
                cases
            ):
                if index:
                    await db.execute(
                        text("""
                            UPDATE walk_measurement_receipt
                            SET drift_assessment = :assessment,
                                drift_assessment_method = 'fixture_drift_screen_v1'
                            WHERE session_id = :session_id
                        """),
                        {"session_id": absent, "assessment": assessment},
                    )
                    await db.commit()
                biography = await query_memory_place_biography(
                    db, place.place.place_id, _spec()
                )
                absent_reading = next(
                    item for item in biography.readings if item.session_id == absent
                )
                assert absent_reading.observation is observation
                assert absent_reading.negative_spatial_claim.eligible is eligible
                assert absent_reading.unjudgeable_reasons == reasons
                assert biography.summary.not_observed_walks == absent_count
                if index == 0:
                    observed_reading = next(
                        item for item in biography.readings if item.session_id == observed
                    )
                    assert observed_reading.observation is PlaceObservation.OBSERVED
                    assert not observed_reading.negative_spatial_claim.eligible
                    assert observed_reading.unjudgeable_reasons == ()
                await db.rollback()
        finally:
            await _cleanup(db)


async def test_place_identity_survives_source_walk_deletion_but_membership_recomputes():
    async with db_session() as db:
        await _cleanup(db)
        try:
            first = await _seal_walk(db, "first", 0, precipitation_mm=1, observed=True)
            second = await _seal_walk(db, "second", 1, precipitation_mm=0, observed=True)
            third = await _seal_walk(db, "third", 2, precipitation_mm=0, observed=True)
            await db.commit()
            first_pin = await _pin(db, first, "delete-first")
            second_pin = await _pin(db, second, "delete-second")
            third_pin = await _pin(db, third, "delete-third")
            await db.commit()
            created = await put_memory_place(
                db,
                place_id="memory-place-stable-after-delete",
                dog_id=DOG_ID,
                seed_pin_ids=(first_pin, second_pin),
            )
            linked = await put_memory_place_membership(
                db,
                place_id=created.place.place_id,
                pin_id=third_pin,
            )
            assert linked.origin is MemoryPlaceMembershipOrigin.USER_LINKED
            await db.commit()

            await db.execute(
                text("DELETE FROM walk_session WHERE id = :session_id"), {"session_id": first}
            )
            await db.commit()

            place = await get_memory_place(db, created.place.place_id)
            memberships = await list_memory_place_memberships(db, created.place.place_id)
            assert place == created.place
            assert [item.pin_id for item in memberships] == [second_pin, third_pin]
        finally:
            await _cleanup(db)


async def test_memory_place_requires_two_distinct_walks():
    async with db_session() as db:
        await _cleanup(db)
        try:
            session_id = await _seal_walk(db, "one", 0, precipitation_mm=0, observed=True)
            await db.commit()
            pin_id = await _pin(db, session_id, "one")
            await db.commit()

            with pytest.raises(MemoryPlaceConflictError, match="2..100"):
                await put_memory_place(
                    db,
                    place_id="memory-place-not-enough-support",
                    dog_id=DOG_ID,
                    seed_pin_ids=(pin_id,),
                )
        finally:
            await _cleanup(db)
