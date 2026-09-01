"""Capsule seal과 raw purge가 실제 PostGIS 트랜잭션 하나인지 검증한다. Decision: #75."""

import math
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.features.spatial_diary.contract import ContextStatus
from app.features.walk import store
from app.features.walk.api import FinishIn, finish_session
from app.features.walk.capsule import UnknownTrailContextProvider
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkSession
from tests.conftest import WALK_T0, db_session, walk_fix
from tests.walk.capsule_helpers import capsule_for

SID = "test:walk:capsule"


class TimeoutContextProvider:
    name = "timeout-weather"

    async def capture(self, request, captured_at):
        raise TimeoutError("fixture timeout")


class CountingContextProvider:
    name = "counting-context"

    def __init__(self):
        self.calls = 0

    async def capture(self, request, captured_at):
        self.calls += 1
        return await UnknownTrailContextProvider().capture(request, captured_at)


async def _cleanup(db):
    await db.execute(text("DELETE FROM walk_session WHERE id LIKE 'test:walk:%'"))
    await db.commit()


async def _open_walk(db):
    await store.upsert_session(db, WalkSession(id=SID, dog_id="dog-1", started_at=WALK_T0))
    fixes = [walk_fix(t, t * 1.2) for t in range(0, 31, 5)]
    await store.append_fixes(db, SID, fixes)
    loaded = await store.load_fixes_ordered(db, SID)
    computed = compute_facts(
        SID,
        "dog-1",
        WALK_T0,
        WALK_T0 + timedelta(seconds=30),
        loaded,
    )
    return loaded, computed


async def test_finalize_persists_all_capsule_children_before_raw_purge():
    async with db_session() as db:
        await _cleanup(db)
        try:
            fixes, computed = await _open_walk(db)
            await store.finalize(
                db,
                computed.facts,
                computed.quality,
                computed.events,
                capsule=capsule_for(computed, fixes),
            )
            await db.commit()

            manifest = await store.get_capsule_manifest(db, SID)
            receipt = await store.get_measurement_receipt(db, SID)
            context = await store.get_trail_context(db, SID)
            sheet = await store.get_cellophane(db, SID)
            assert manifest is not None and manifest.dog_id == "dog-1"
            assert receipt is not None and receipt.accepted_fix_count == len(fixes)
            assert context is not None and context.status is ContextStatus.UNKNOWN
            assert sheet is not None
            assert math.fsum(sheet.occupancy.values()) == pytest.approx(
                receipt.canonical_segment_time_s
            )
            assert (await db.execute(text(
                "SELECT count(*) FROM walk_fix WHERE session_id = :id"
            ), {"id": SID})).scalar_one() == 0
        finally:
            await _cleanup(db)


async def test_finish_api_purges_normally_when_context_capture_fails():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _open_walk(db)
            result = await finish_session(
                SID,
                FinishIn(ended_at=WALK_T0 + timedelta(seconds=30)),
                db,
                TimeoutContextProvider(),
            )

            assert result.facts.session_id == SID
            context = await store.get_trail_context(db, SID)
            assert context is not None and context.status is ContextStatus.FAILED
            assert context.failure_reason == "provider_error:TimeoutError"
            assert (await db.execute(text(
                "SELECT count(*) FROM walk_fix WHERE session_id = :id"
            ), {"id": SID})).scalar_one() == 0
        finally:
            await _cleanup(db)


async def test_finish_retry_reuses_sealed_capsule_without_recapturing_context():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _open_walk(db)
            provider = CountingContextProvider()
            body = FinishIn(ended_at=WALK_T0 + timedelta(seconds=30))

            first = await finish_session(SID, body, db, provider)
            first_manifest = await store.get_capsule_manifest(db, SID)
            second = await finish_session(SID, body, db, provider)
            second_manifest = await store.get_capsule_manifest(db, SID)

            assert first == second
            assert first_manifest == second_manifest
            assert provider.calls == 1
        finally:
            await _cleanup(db)


async def test_manifest_failure_rolls_back_children_and_preserves_raw_fixes(monkeypatch):
    async with db_session() as db:
        await _cleanup(db)
        try:
            fixes, computed = await _open_walk(db)
            await db.commit()

            async def fail_manifest(*_args, **_kwargs):
                raise RuntimeError("fixture seal failure")

            monkeypatch.setattr(store, "_write_capsule_manifest", fail_manifest)
            with pytest.raises(RuntimeError, match="seal failure"):
                await store.finalize(
                    db,
                    computed.facts,
                    computed.quality,
                    computed.events,
                    capsule=capsule_for(computed, fixes),
                )
            await db.rollback()

            session = await store.get_session(db, SID)
            assert session is not None and session.state == "open"
            assert (await db.execute(text(
                "SELECT count(*) FROM walk_fix WHERE session_id = :id"
            ), {"id": SID})).scalar_one() == len(fixes)
            assert await store.get_facts(db, SID) is None
            assert await store.get_capsule_manifest(db, SID) is None
            assert await store.get_measurement_receipt(db, SID) is None
            assert await store.get_trail_context(db, SID) is None
            assert await store.get_cellophane(db, SID) is None
        finally:
            await _cleanup(db)


async def test_session_delete_cascades_every_capsule_layer():
    async with db_session() as db:
        await _cleanup(db)
        try:
            fixes, computed = await _open_walk(db)
            await store.finalize(
                db,
                computed.facts,
                computed.quality,
                computed.events,
                capsule=capsule_for(computed, fixes),
            )
            await db.commit()
            await db.execute(text("DELETE FROM walk_session WHERE id = :id"), {"id": SID})
            await db.commit()

            for table in (
                "walk_capsule_manifest",
                "walk_measurement_receipt",
                "walk_trail_context",
                "walk_cellophane_sheet",
                "walk_cellophane_cell",
            ):
                count = (await db.execute(text(
                    f"SELECT count(*) FROM {table} WHERE session_id = :id"
                ), {"id": SID})).scalar_one()
                assert count == 0, table
        finally:
            await _cleanup(db)
