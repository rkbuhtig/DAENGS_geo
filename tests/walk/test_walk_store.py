"""세션 저장 흐름 — 멱등 시작 · 배치 순서 보존 · **파생 뒤 fix 잔존 0**.

마지막 하나가 이 계층의 존재 이유다: 궤적은 정책 전까지 세션 수명만 산다.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.features.walk import store
from app.features.walk.encounter import FacilityCandidate, compute_encounters
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkSession
from tests.conftest import WALK_T0, db_session, walk_fix

SID = "test:walk:store"


async def _cleanup(session):
    await session.execute(text("DELETE FROM walk_session WHERE id LIKE 'test:walk:%'"))
    await session.commit()


async def test_full_session_lifecycle():
    async with db_session() as db:
        await _cleanup(db)
        try:
            s = WalkSession(id=SID, dog_id="halmae", started_at=WALK_T0)
            first = await store.upsert_session(db, s)
            again = await store.upsert_session(db, s)      # 멱등 재전송
            assert first.id == again.id and again.fix_count == 0

            # 두 배치 — seq 가 이어지고 수신 수가 누적된다
            batch1 = [walk_fix(t, t / 5 * 7) for t in range(0, 30, 5)]
            batch2 = [walk_fix(t, 35) for t in range(30, 60, 5)]
            assert (await store.append_fixes(db, SID, batch1)).fix_count == 6
            assert (await store.append_fixes(db, SID, batch2)).fix_count == 12

            loaded = await store.load_fixes_ordered(db, SID)
            assert [f.at for f in loaded] == sorted(f.at for f in batch1 + batch2)

            ended = WALK_T0 + timedelta(seconds=60)
            computed = compute_facts(SID, "halmae", WALK_T0, ended, loaded)
            nearby = walk_fix(30, 35)
            encounters = compute_encounters(
                SID, computed.segments, computed.events,
                [FacilityCandidate(
                    facility_source="test", facility_ref="nearby", kind="cafe",
                    lat=nearby.lat, lng=nearby.lng, place_active=None, as_of=None,
                )],
            )
            await store.finalize(
                db, computed.facts, computed.quality, computed.events, encounters,
            )
            await db.commit()

            # 사실은 남고, fix 는 없다
            stored = await store.get_facts(db, SID)
            assert stored is not None
            facts, quality = stored
            assert facts.model_dump() == computed.facts.model_dump()
            assert quality["received"] == 12
            remaining = (await db.execute(text(
                "SELECT count(*) FROM walk_fix WHERE session_id = :id"), {"id": SID}
            )).scalar_one()
            assert remaining == 0, "finish 뒤에 궤적이 남아 있다 — 저장 정책 위반"

            ended_session = await store.get_session(db, SID)
            assert ended_session is not None and ended_session.ended_at is not None
            assert ended_session.state == "purged"
            assert computed.events
            assert await store.get_events(db, SID) == computed.events
            assert await store.get_encounters(db, SID) == encounters
        finally:
            await _cleanup(db)


async def test_mock_fixes_are_counted_separately():
    async with db_session() as db:
        await _cleanup(db)
        try:
            sid = "test:walk:mock"
            await store.upsert_session(db, WalkSession(id=sid, dog_id="halmae", started_at=WALK_T0))
            mocked = [walk_fix(0, 0, is_mock=True), walk_fix(5, 7, is_mock=True)]
            await store.append_fixes(db, sid, mocked)
            mocks = (await db.execute(text(
                "SELECT mock_fix_count FROM walk_session WHERE id = :id"), {"id": sid}
            )).scalar_one()
            assert mocks == 2
            stored = await store.get_session(db, sid)
            assert stored is not None and stored.evidence_origin == "mock"
        finally:
            await _cleanup(db)


async def test_fix_batch_retry_is_idempotent_and_conflict_is_visible():
    async with db_session() as db:
        await _cleanup(db)
        try:
            sid = "test:walk:retry"
            await store.upsert_session(db, WalkSession(id=sid, dog_id="halmae", started_at=WALK_T0))
            batch = [walk_fix(0, 0), walk_fix(5, 7)]
            first = await store.append_fixes(db, sid, batch)
            retry = await store.append_fixes(db, sid, batch)
            assert (first.stored, first.duplicates, first.fix_count) == (2, 0, 2)
            assert (retry.stored, retry.duplicates, retry.fix_count) == (0, 2, 2)

            changed = [walk_fix(0, 99, client_seq=batch[0].client_seq)]
            with pytest.raises(store.FixSequenceConflictError):
                await store.append_fixes(db, sid, changed)

            changed_chain = [walk_fix(0, 0, client_seq=batch[0].client_seq, chain_index=1)]
            with pytest.raises(store.FixSequenceConflictError):
                await store.append_fixes(db, sid, changed_chain)
        finally:
            await _cleanup(db)


async def test_device_and_mock_cannot_mix_in_one_session():
    async with db_session() as db:
        await _cleanup(db)
        try:
            sid = "test:walk:origin"
            await store.upsert_session(db, WalkSession(id=sid, dog_id="halmae", started_at=WALK_T0))
            await store.append_fixes(db, sid, [walk_fix(0, 0)])
            with pytest.raises(store.EvidenceOriginConflictError):
                await store.append_fixes(db, sid, [walk_fix(5, 7, is_mock=True)])
        finally:
            await _cleanup(db)


async def test_finish_lock_prevents_late_upload_from_surviving():
    sid = "test:walk:finish-race"
    async with db_session() as setup:
        await _cleanup(setup)
        await store.upsert_session(setup, WalkSession(id=sid, dog_id="halmae", started_at=WALK_T0))
        await store.append_fixes(setup, sid, [walk_fix(0, 0), walk_fix(5, 7)])
        await setup.commit()

    try:
        async with db_session() as finishing, db_session() as uploading:
            session = await store.lock_session(finishing, sid)
            assert session is not None
            late_upload = asyncio.create_task(
                store.append_fixes(uploading, sid, [walk_fix(10, 14)])
            )
            await asyncio.sleep(0.05)  # late upload은 같은 세션 row lock 뒤에서 기다린다

            loaded = await store.load_fixes_ordered(finishing, sid)
            computed = compute_facts(sid, "halmae", WALK_T0, WALK_T0 + timedelta(seconds=10), loaded)
            await store.finalize(
                finishing, computed.facts, computed.quality, computed.events
            )
            await finishing.commit()

            with pytest.raises(store.WalkSessionNotOpenError):
                await late_upload
            await uploading.rollback()

        async with db_session() as verify:
            remaining = (await verify.execute(text(
                "SELECT count(*) FROM walk_fix WHERE session_id = :id"
            ), {"id": sid})).scalar_one()
            assert remaining == 0
    finally:
        async with db_session() as cleanup:
            await _cleanup(cleanup)
