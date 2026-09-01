"""low-motion Candidate가 실제 제시·증언·Pin·지도 overlay로 이어지는 PR4 수직 테스트."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.features.spatial_diary.access import SpatialDiaryPrincipal
from app.features.spatial_diary.api import read_candidates
from app.features.spatial_diary.contract import (
    AttestedClaim,
    ClaimSupport,
    EntrySelector,
    MemoryAction,
    OfferInteractionKind,
    QualityPolicy,
    ReviewDisposition,
    SpatialDiaryViewSpec,
    SubjectRole,
    WalkSelector,
)
from app.features.spatial_diary.episode import (
    SpatialDiaryEpisodeConflictError,
    attest_episode_offer,
    list_episode_candidates,
    list_offer_review_states,
    put_episode_offer,
    put_offer_interaction,
)
from app.features.territory.spatial_diary import query_spatial_diary_view
from app.features.walk import store
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkSession
from app.features.walk.observation import MicroObservation
from tests.conftest import TEST_ORIGIN, WALK_T0, db_session, walk_fix
from tests.walk.capsule_helpers import capsule_for

DOG_ID = "dog-episode-memory"
SESSION_ID = "test:episode-memory:walk"
PRINCIPAL = SpatialDiaryPrincipal(owner_id="owner-episode", dog_ids=frozenset({DOG_ID}))


def _observation(index: int, start_s: int, duration_s: int, *, kind: str = "slow"):
    return MicroObservation(
        session_id=SESSION_ID,
        index=index,
        kind=kind,
        started_at=WALK_T0 + timedelta(seconds=start_s),
        ended_at=WALK_T0 + timedelta(seconds=start_s + duration_s),
        duration_s=duration_s,
        lat=TEST_ORIGIN[0],
        lng=TEST_ORIGIN[1] + index * 0.00001,
        path_m=0 if kind == "gap" else duration_s * 0.2,
        net_m=0 if kind == "gap" else 1.5,
        span_m=0 if kind == "gap" else 4.0,
        fix_count=2 if kind == "gap" else duration_s + 1,
        accuracy_p50_m=8.0,
        route_offset_m=start_s * 1.2,
        chain_index=0,
        abuts_break=kind == "gap",
    )


async def _cleanup(db):
    await db.rollback()
    await db.execute(
        text("DELETE FROM walk_session WHERE id LIKE 'test:episode-memory:%'")
    )
    await db.commit()


async def _seal_walk(db):
    await store.upsert_session(
        db,
        WalkSession(id=SESSION_ID, dog_id=DOG_ID, started_at=WALK_T0),
    )
    fixes = [walk_fix(second, second * 1.2) for second in range(0, 201, 5)]
    await store.append_fixes(db, SESSION_ID, fixes)
    loaded = await store.load_fixes_ordered(db, SESSION_ID)
    computed = compute_facts(
        SESSION_ID,
        DOG_ID,
        WALK_T0,
        WALK_T0 + timedelta(seconds=200),
        loaded,
    )
    observations = [
        _observation(0, 20, 12),
        _observation(1, 50, 30),
        _observation(2, 90, 20),
        _observation(3, 120, 40),
        _observation(4, 160, 30, kind="gap"),
    ]
    await store.finalize(
        db,
        computed.facts,
        computed.quality,
        computed.events,
        observations=observations,
        capsule=capsule_for(computed, loaded),
    )
    await db.commit()


def _view_spec(*, meanings=(), roles=()) -> SpatialDiaryViewSpec:
    return SpatialDiaryViewSpec(
        walk_selector=WalkSelector(dog_id=DOG_ID),
        entry_selector=EntrySelector(subject_roles=roles, meaning_codes=meanings),
        field_metric="visit_rate",
        quality_policy=QualityPolicy(policy_version=1, name="diary_v1"),
    )


async def test_candidate_policy_returns_only_three_ranked_slow_windows_with_allowances():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)

            candidates = await list_episode_candidates(db, SESSION_ID)

            assert len(candidates) == 3
            assert [
                item.candidate.source_observation_ids[0].rsplit(":", 1)[-1]
                for item in candidates
            ] == ["3", "1", "2"]
            assert all(
                item.candidate.source_observation_ids[0] != f"{SESSION_ID}:micro-v1:4"
                for item in candidates
            )
            first = candidates[0]
            assert first.candidate.event_at == WALK_T0 + timedelta(seconds=140)
            assert first.candidate.event_footprint.radius_m == pytest.approx(12.0)
            assert first.claim_allowance.temporal is ClaimSupport.APPROXIMATE
            assert first.claim_allowance.spatial is ClaimSupport.APPROXIMATE
            assert first.claim_allowance.interpretation is ClaimSupport.ATTESTATION_REQUIRED
        finally:
            await _cleanup(db)


async def test_offer_attestation_pin_and_entry_selector_complete_one_product_loop():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            candidate = (await list_episode_candidates(db, SESSION_ID))[0].candidate
            source_id = candidate.source_observation_ids[0]

            offer = await put_episode_offer(
                db,
                offer_id="offer-episode-1",
                session_id=SESSION_ID,
                source_observation_id=source_id,
                candidate_policy_version=1,
                offered_at=WALK_T0 + timedelta(minutes=4),
            )
            same_offer = await put_episode_offer(
                db,
                offer_id="offer-episode-1",
                session_id=SESSION_ID,
                source_observation_id=source_id,
                candidate_policy_version=1,
            )
            assert same_offer == offer
            assert "천천히 움직였어요" in offer.prompt_snapshot
            with pytest.raises(SpatialDiaryEpisodeConflictError, match="already has"):
                await put_episode_offer(
                    db,
                    offer_id="offer-episode-duplicate",
                    session_id=SESSION_ID,
                    source_observation_id=source_id,
                    candidate_policy_version=1,
                )
            await db.commit()

            viewed = await put_offer_interaction(
                db,
                offer_id=offer.offer_id,
                interaction_id="interaction-episode-1",
                kind=OfferInteractionKind.VIEWED,
                occurred_at=WALK_T0 + timedelta(minutes=5),
            )
            same_viewed = await put_offer_interaction(
                db,
                offer_id=offer.offer_id,
                interaction_id="interaction-episode-1",
                kind=OfferInteractionKind.VIEWED,
            )
            assert same_viewed == viewed
            await db.commit()

            claim = AttestedClaim(
                subject_role=SubjectRole.DOG,
                meaning_code="exploration",
                vocabulary_version=1,
            )
            saved = await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-episode-1",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(claim,),
                memory_action=MemoryAction.SAVE,
                pin_id="pin-episode-1",
                attested_at=WALK_T0 + timedelta(minutes=6),
            )
            same_saved = await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-episode-1",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(claim,),
                memory_action=MemoryAction.SAVE,
                pin_id="pin-episode-1",
            )
            assert same_saved == saved
            assert saved.pin is not None
            assert saved.pin.event_footprint == offer.event_footprint
            await db.commit()

            review_states = await list_offer_review_states(db, SESSION_ID)
            assert len(review_states) == 1
            assert review_states[0].offer == offer
            assert review_states[0].interactions == (viewed,)
            assert review_states[0].attestation == saved.attestation
            assert review_states[0].pin == saved.pin
            await db.rollback()

            with pytest.raises(SpatialDiaryEpisodeConflictError, match="has an attestation"):
                await put_offer_interaction(
                    db,
                    offer_id=offer.offer_id,
                    interaction_id="interaction-after-attestation",
                    kind=OfferInteractionKind.VIEWED,
                )
            await db.rollback()

            exploration = await query_spatial_diary_view(
                db,
                _view_spec(meanings=("exploration",), roles=(SubjectRole.DOG,)),
            )
            assert exploration.receipt.pin_count == 1
            assert exploration.pins[0].pin.pin_id == "pin-episode-1"
            await db.rollback()

            other = await query_spatial_diary_view(
                db,
                _view_spec(meanings=("social_interaction",)),
            )
            assert other.receipt.pin_count == 0
            assert other.pins == ()
        finally:
            await _cleanup(db)


async def test_dismissed_offer_has_no_attestation_and_session_delete_cascades_memory():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            source_id = (
                await list_episode_candidates(db, SESSION_ID)
            )[0].candidate.source_observation_ids[0]
            offer = await put_episode_offer(
                db,
                offer_id="offer-dismissed",
                session_id=SESSION_ID,
                source_observation_id=source_id,
                candidate_policy_version=1,
            )
            await db.commit()
            await put_offer_interaction(
                db,
                offer_id=offer.offer_id,
                interaction_id="interaction-dismissed",
                kind=OfferInteractionKind.DISMISSED,
            )
            await db.commit()

            with pytest.raises(SpatialDiaryEpisodeConflictError, match="already dismissed"):
                await attest_episode_offer(
                    db,
                    offer_id=offer.offer_id,
                    attestation_id="attestation-forbidden",
                    review_disposition=ReviewDisposition.UNCERTAIN,
                    claims=(),
                    memory_action=MemoryAction.DISMISS,
                    pin_id=None,
                )
            await db.rollback()
            counts = (await db.execute(text("""
                SELECT
                  (SELECT count(*) FROM spatial_diary_walk_attestation
                   WHERE session_id = :session_id),
                  (SELECT count(*) FROM spatial_diary_episode_pin
                   WHERE session_id = :session_id)
            """), {"session_id": SESSION_ID})).one()
            assert tuple(counts) == (0, 0)

            await db.execute(
                text("DELETE FROM walk_session WHERE id = :session_id"),
                {"session_id": SESSION_ID},
            )
            await db.commit()
            offer_count = (await db.execute(text(
                "SELECT count(*) FROM spatial_diary_episode_offer "
                "WHERE session_id = :session_id"
            ), {"session_id": SESSION_ID})).scalar_one()
            interaction_count = (await db.execute(text(
                "SELECT count(*) FROM spatial_diary_offer_interaction interaction "
                "JOIN spatial_diary_episode_offer offer USING (offer_id) "
                "WHERE offer.session_id = :session_id"
            ), {"session_id": SESSION_ID})).scalar_one()
            assert (offer_count, interaction_count) == (0, 0)
        finally:
            await _cleanup(db)


async def test_candidate_api_hides_an_unowned_capsule():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            outsider = SpatialDiaryPrincipal(
                owner_id="owner-outsider",
                dog_ids=frozenset({"another-dog"}),
            )

            with pytest.raises(HTTPException) as hidden:
                await read_candidates(SESSION_ID, db, outsider)
            assert hidden.value.status_code == 404
            await db.rollback()

            visible = await read_candidates(SESSION_ID, db, PRINCIPAL)
            assert len(visible.candidates) == 3
        finally:
            await _cleanup(db)


async def test_suspected_drift_keeps_reviewable_candidate_but_forbids_spatial_pin():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            await db.execute(text("""
                UPDATE walk_measurement_receipt
                SET drift_assessment = 'suspected',
                    drift_assessment_method = 'fixture-drift-v1'
                WHERE session_id = :session_id
            """), {"session_id": SESSION_ID})
            await db.commit()

            candidate = (await list_episode_candidates(db, SESSION_ID))[0]
            assert candidate.claim_allowance.spatial is ClaimSupport.UNSUPPORTED
            offer = await put_episode_offer(
                db,
                offer_id="offer-drift",
                session_id=SESSION_ID,
                source_observation_id=candidate.candidate.source_observation_ids[0],
                candidate_policy_version=1,
            )
            await db.commit()

            with pytest.raises(SpatialDiaryEpisodeConflictError, match="forbids a spatial pin"):
                await attest_episode_offer(
                    db,
                    offer_id=offer.offer_id,
                    attestation_id="attestation-drift",
                    review_disposition=ReviewDisposition.UNCERTAIN,
                    claims=(),
                    memory_action=MemoryAction.SAVE,
                    pin_id="pin-drift",
                )
        finally:
            await _cleanup(db)
