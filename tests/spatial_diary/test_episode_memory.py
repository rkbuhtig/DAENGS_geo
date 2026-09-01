"""low-motion Candidate가 실제 제시·증언·Pin·지도 overlay로 이어지는 PR4 수직 테스트."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.features.spatial_diary.access import SpatialDiaryPrincipal
from app.features.spatial_diary.api import (
    PutPinAttestationCorrectionIn,
    PutPublishedJournalIn,
    put_pin_attestation_correction,
    put_walk_journal_snapshot,
    read_candidates,
    read_journal_snapshot,
    read_pin_attestations,
    read_walk_journal,
    read_walk_journal_snapshots,
)
from app.features.spatial_diary.contract import (
    AttestedClaim,
    ClaimSupport,
    ElicitationMode,
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
    SpatialDiaryEpisodeIntegrityError,
    SpatialDiaryEpisodeNotFoundError,
    attest_episode_offer,
    correct_pin_attestation,
    list_episode_candidates,
    list_offer_review_states,
    list_pin_attestations,
    put_episode_offer,
    put_offer_interaction,
)
from app.features.spatial_diary.journal import query_walk_journal
from app.features.spatial_diary.published_journal import (
    get_published_journal_snapshot,
    list_published_journal_snapshots,
    put_published_journal_snapshot,
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

            with pytest.raises(
                SpatialDiaryEpisodeConflictError,
                match="already has a viewed interaction",
            ):
                await put_offer_interaction(
                    db,
                    offer_id=offer.offer_id,
                    interaction_id="interaction-episode-viewed-again",
                    kind=OfferInteractionKind.VIEWED,
                )
            await db.rollback()

            claim = AttestedClaim(
                subject_role=SubjectRole.DOG,
                meaning_code="exploration",
                vocabulary_version=1,
            )
            owner_claim = AttestedClaim(
                subject_role=SubjectRole.OWNER,
                meaning_code="owner_pause",
                vocabulary_version=1,
            )
            saved = await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-episode-1",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(claim, owner_claim),
                memory_action=MemoryAction.SAVE,
                pin_id="pin-episode-1",
                attested_at=WALK_T0 + timedelta(minutes=6),
            )
            same_saved = await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-episode-1",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(claim, owner_claim),
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
            await db.rollback()

            owner_pause = await query_spatial_diary_view(
                db,
                _view_spec(meanings=("owner_pause",), roles=(SubjectRole.OWNER,)),
            )
            assert owner_pause.receipt.pin_count == 1
            await db.rollback()

            crossed_claims = await query_spatial_diary_view(
                db,
                _view_spec(meanings=("owner_pause",), roles=(SubjectRole.DOG,)),
            )
            assert crossed_claims.receipt.pin_count == 0
            assert crossed_claims.pins == ()
        finally:
            await _cleanup(db)


async def test_pin_attestation_correction_preserves_history_and_updates_read_models():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            candidate = (await list_episode_candidates(db, SESSION_ID))[0].candidate
            offer = await put_episode_offer(
                db,
                offer_id="offer-correction",
                session_id=SESSION_ID,
                source_observation_id=candidate.source_observation_ids[0],
                candidate_policy_version=1,
            )
            initial = await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-correction-origin",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(
                    AttestedClaim(
                        subject_role=SubjectRole.DOG,
                        meaning_code="exploration",
                        vocabulary_version=1,
                    ),
                ),
                memory_action=MemoryAction.SAVE,
                pin_id="pin-correction",
                attested_at=candidate.event_at + timedelta(minutes=2),
            )
            await db.commit()

            owner_claim = AttestedClaim(
                subject_role=SubjectRole.OWNER,
                meaning_code="owner_pause",
                vocabulary_version=1,
            )
            correction = await correct_pin_attestation(
                db,
                pin_id="pin-correction",
                attestation_id="attestation-correction-1",
                supersedes_attestation_id=initial.attestation.attestation_id,
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(owner_claim,),
                attested_at=candidate.event_at + timedelta(minutes=3),
            )
            await db.commit()
            same = await correct_pin_attestation(
                db,
                pin_id="pin-correction",
                attestation_id="attestation-correction-1",
                supersedes_attestation_id=initial.attestation.attestation_id,
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(owner_claim,),
            )
            assert same == correction
            assert correction.elicitation_mode is ElicitationMode.PIN_CORRECTION
            assert correction.offer_id is None
            await db.rollback()

            history = await list_pin_attestations(db, "pin-correction")
            assert tuple(item.attestation_id for item in history) == (
                "attestation-correction-origin",
                "attestation-correction-1",
            )
            await db.rollback()

            with pytest.raises(
                SpatialDiaryEpisodeConflictError,
                match="current head",
            ):
                await correct_pin_attestation(
                    db,
                    pin_id="pin-correction",
                    attestation_id="attestation-correction-fork",
                    supersedes_attestation_id=initial.attestation.attestation_id,
                    review_disposition=ReviewDisposition.CONFIRMED,
                    claims=(owner_claim,),
                )
            await db.rollback()

            review_state = (await list_offer_review_states(db, SESSION_ID))[0]
            assert review_state.attestation == initial.attestation
            await db.rollback()

            journal = await query_walk_journal(db, SESSION_ID)
            assert journal.entries[0].pin.created_by_attestation_id == (
                initial.attestation.attestation_id
            )
            assert journal.entries[0].attestation == correction
            assert journal.entries[0].attestation.claims == (owner_claim,)
            await db.rollback()

            old_meaning = await query_spatial_diary_view(
                db,
                _view_spec(meanings=("exploration",)),
            )
            assert old_meaning.receipt.pin_count == 0
            await db.rollback()
            current_meaning = await query_spatial_diary_view(
                db,
                _view_spec(meanings=("owner_pause",), roles=(SubjectRole.OWNER,)),
            )
            assert current_meaning.receipt.pin_count == 1
            await db.rollback()

            second_body = PutPinAttestationCorrectionIn(
                supersedes_attestation_id=correction.attestation_id,
                review_disposition=ReviewDisposition.UNCERTAIN,
                claims=(),
            )
            second = await put_pin_attestation_correction(
                "pin-correction",
                "attestation-correction-2",
                second_body,
                db,
                PRINCIPAL,
            )
            assert second.supersedes_attestation_id == correction.attestation_id
            same_second = await put_pin_attestation_correction(
                "pin-correction",
                "attestation-correction-2",
                second_body,
                db,
                PRINCIPAL,
            )
            assert same_second == second
            listed = await read_pin_attestations("pin-correction", db, PRINCIPAL)
            assert listed.current_attestation_id == second.attestation_id
            assert len(listed.attestations) == 3
            await db.rollback()

            outsider = SpatialDiaryPrincipal(
                owner_id="owner-outsider",
                dog_ids=frozenset({"another-dog"}),
            )
            with pytest.raises(HTTPException) as hidden:
                await read_pin_attestations("pin-correction", db, outsider)
            assert hidden.value.status_code == 404
            await db.rollback()

            await db.execute(
                text("DELETE FROM spatial_diary_episode_pin WHERE pin_id = :pin_id"),
                {"pin_id": "pin-correction"},
            )
            await db.commit()
            remaining = (await db.execute(text("""
                SELECT attestation_id
                FROM spatial_diary_walk_attestation
                WHERE session_id = :session_id
                ORDER BY attestation_id
            """), {"session_id": SESSION_ID})).scalars().all()
            assert remaining == ["attestation-correction-origin"]
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


async def test_walk_journal_projection_replays_context_facts_and_saved_pins():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            generated_at = WALK_T0 + timedelta(days=1)
            unknown = await query_walk_journal(
                db,
                SESSION_ID,
                generated_at=generated_at,
            )
            assert unknown.context_facets.precipitation == "unknown"
            assert unknown.context_facets.daylight == "unknown"
            assert "비가 " not in unknown.summary
            assert "낮 산책" not in unknown.summary
            assert "밤 산책" not in unknown.summary
            await db.rollback()

            await db.execute(text("""
                UPDATE walk_trail_context
                SET status = 'captured', provider = 'fixture-weather',
                    source_observed_at = walked_at,
                    precipitation_mm = 1.2, sun_elevation_deg = 12
                WHERE session_id = :session_id
            """), {"session_id": SESSION_ID})
            await db.commit()

            empty = await query_walk_journal(
                db,
                SESSION_ID,
                generated_at=generated_at,
            )
            assert empty.title == "2026년 8월 24일 산책 일기"
            assert empty.context_facets.precipitation == "rain"
            assert empty.context_facets.daylight == "day"
            assert empty.entries == ()
            assert empty.receipt.pin_count == 0
            assert "기억으로 남긴 장면은 아직 없어요" in empty.summary
            await db.rollback()

            candidate = (await list_episode_candidates(db, SESSION_ID))[0].candidate
            offer = await put_episode_offer(
                db,
                offer_id="offer-journal-1",
                session_id=SESSION_ID,
                source_observation_id=candidate.source_observation_ids[0],
                candidate_policy_version=1,
                offered_at=candidate.event_at + timedelta(minutes=1),
            )
            await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-journal-1",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(
                    AttestedClaim(
                        subject_role=SubjectRole.DOG,
                        meaning_code="exploration",
                        vocabulary_version=1,
                    ),
                ),
                memory_action=MemoryAction.SAVE,
                pin_id="pin-journal-1",
                attested_at=candidate.event_at + timedelta(minutes=2),
            )
            await db.commit()

            journal = await query_walk_journal(
                db,
                SESSION_ID,
                generated_at=generated_at,
            )
            assert journal.receipt.generated_at == generated_at
            assert journal.receipt.narration_policy_version == 1
            assert journal.receipt.pin_count == 1
            assert journal.entries[0].attestation.claims[0].meaning_code == "exploration"
            assert journal.entries[0].narration == (
                "16시 02분쯤, 사용자가 강아지에 관한 장면으로 확인해 기억에 남겼어요."
            )
            assert "비 오는 날로 분류된 낮 산책" in journal.summary
            assert "기억으로 남긴 장면은 1개예요" in journal.summary
            await db.rollback()

            visible = await read_walk_journal(SESSION_ID, db, PRINCIPAL)
            assert visible.session_id == SESSION_ID
            await db.rollback()

            outsider = SpatialDiaryPrincipal(
                owner_id="owner-outsider",
                dog_ids=frozenset({"another-dog"}),
            )
            with pytest.raises(HTTPException) as hidden:
                await read_walk_journal(SESSION_ID, db, outsider)
            assert hidden.value.status_code == 404
            await db.rollback()

            await db.execute(
                text("DELETE FROM walk_trail_context WHERE session_id = :session_id"),
                {"session_id": SESSION_ID},
            )
            await db.commit()
            with pytest.raises(
                SpatialDiaryEpisodeIntegrityError,
                match="missing journal material",
            ):
                await query_walk_journal(db, SESSION_ID)
        finally:
            await _cleanup(db)


async def test_published_journal_snapshot_is_private_immutable_and_cascades_with_walk():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            candidate = (await list_episode_candidates(db, SESSION_ID))[0].candidate
            offer = await put_episode_offer(
                db,
                offer_id="offer-published-journal",
                session_id=SESSION_ID,
                source_observation_id=candidate.source_observation_ids[0],
                candidate_policy_version=1,
            )
            await attest_episode_offer(
                db,
                offer_id=offer.offer_id,
                attestation_id="attestation-published-journal",
                review_disposition=ReviewDisposition.CONFIRMED,
                claims=(
                    AttestedClaim(
                        subject_role=SubjectRole.DOG,
                        meaning_code="exploration",
                        vocabulary_version=1,
                    ),
                ),
                memory_action=MemoryAction.SAVE,
                pin_id="pin-published-journal",
            )
            await db.commit()

            published_at = WALK_T0 + timedelta(days=2)
            snapshot = await put_published_journal_snapshot(
                db,
                snapshot_id="journal-snapshot-1",
                session_id=SESSION_ID,
                title="비 온 뒤 냄새 맡던 날",
                summary="천천히 오래 머문 장면을 대표 기억으로 고정했다.",
                selected_pin_ids=("pin-published-journal",),
                published_at=published_at,
            )
            await db.commit()
            assert snapshot.visibility == "private"
            assert snapshot.published_at == published_at
            assert snapshot.selected_pin_ids == ("pin-published-journal",)
            assert snapshot.source_projection_version == 1

            same = await put_published_journal_snapshot(
                db,
                snapshot_id="journal-snapshot-1",
                session_id=SESSION_ID,
                title="비 온 뒤 냄새 맡던 날",
                summary="천천히 오래 머문 장면을 대표 기억으로 고정했다.",
                selected_pin_ids=("pin-published-journal",),
            )
            assert same == snapshot
            assert await get_published_journal_snapshot(db, snapshot.snapshot_id) == snapshot
            assert await list_published_journal_snapshots(db, SESSION_ID) == (snapshot,)
            await db.rollback()

            with pytest.raises(
                SpatialDiaryEpisodeConflictError,
                match="already has different content",
            ):
                await put_published_journal_snapshot(
                    db,
                    snapshot_id="journal-snapshot-1",
                    session_id=SESSION_ID,
                    title="바꿀 수 없는 제목",
                    summary=snapshot.summary,
                    selected_pin_ids=snapshot.selected_pin_ids,
                )
            await db.rollback()

            with pytest.raises(
                SpatialDiaryEpisodeConflictError,
                match="must belong",
            ):
                await put_published_journal_snapshot(
                    db,
                    snapshot_id="journal-snapshot-unknown-pin",
                    session_id=SESSION_ID,
                    title="없는 장면",
                    summary="다른 산책이나 존재하지 않는 Pin은 고정할 수 없다.",
                    selected_pin_ids=("pin-not-in-this-walk",),
                )
            await db.rollback()

            await db.execute(
                text("DELETE FROM walk_session WHERE id = :session_id"),
                {"session_id": SESSION_ID},
            )
            await db.commit()
            with pytest.raises(SpatialDiaryEpisodeNotFoundError):
                await get_published_journal_snapshot(db, snapshot.snapshot_id)
        finally:
            await _cleanup(db)


async def test_published_journal_api_hides_snapshot_and_allows_summary_only_version():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db)
            body = PutPublishedJournalIn(
                title="대표 장면이 없는 산책",
                summary="산책 전체를 한 편으로 고정한 비공개 일기다.",
            )
            snapshot = await put_walk_journal_snapshot(
                SESSION_ID,
                "journal-snapshot-api",
                body,
                db,
                PRINCIPAL,
            )
            assert snapshot.selected_pin_ids == ()

            listed = await read_walk_journal_snapshots(SESSION_ID, db, PRINCIPAL)
            assert listed.snapshots == (snapshot,)
            await db.rollback()

            outsider = SpatialDiaryPrincipal(
                owner_id="owner-outsider",
                dog_ids=frozenset({"another-dog"}),
            )
            with pytest.raises(HTTPException) as hidden:
                await read_journal_snapshot(snapshot.snapshot_id, db, outsider)
            assert hidden.value.status_code == 404
            await db.rollback()

            visible = await read_journal_snapshot(snapshot.snapshot_id, db, PRINCIPAL)
            assert visible == snapshot
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
