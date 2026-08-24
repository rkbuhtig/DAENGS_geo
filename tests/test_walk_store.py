"""세션 저장 흐름 — 멱등 시작 · 배치 순서 보존 · **finish 후 fix 잔존 0**.

마지막 하나가 이 계층의 존재 이유다: 궤적은 정책 전까지 세션 수명만 산다.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.features.walk import store
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix, WalkSession
from tests.conftest import db_session
from tests.test_walk_facts import fix

T0 = datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
SID = "test:walk:store"


async def _cleanup(session):
    await session.execute(text("DELETE FROM walk_session WHERE id LIKE 'test:walk:%'"))
    await session.commit()


async def test_full_session_lifecycle():
    async with db_session() as db:
        await _cleanup(db)
        try:
            s = WalkSession(id=SID, dog_id="halmae", started_at=T0)
            first = await store.upsert_session(db, s)
            again = await store.upsert_session(db, s)      # 멱등 재전송
            assert first.id == again.id and again.fix_count == 0

            # 두 배치 — seq 가 이어지고 수신 수가 누적된다
            batch1 = [fix(t, t / 5 * 7) for t in range(0, 30, 5)]
            batch2 = [fix(t, t / 5 * 7) for t in range(30, 60, 5)]
            assert await store.append_fixes(db, SID, batch1) == 6
            assert await store.append_fixes(db, SID, batch2) == 12

            loaded = await store.load_fixes_ordered(db, SID)
            assert [f.at for f in loaded] == sorted(f.at for f in batch1 + batch2)

            ended = T0 + timedelta(seconds=60)
            computed = compute_facts(SID, "halmae", T0, ended, loaded)
            await store.finalize(db, computed.facts, computed.quality)
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
        finally:
            await _cleanup(db)


async def test_mock_fixes_are_counted_separately():
    async with db_session() as db:
        await _cleanup(db)
        try:
            sid = "test:walk:mock"
            await store.upsert_session(db, WalkSession(id=sid, dog_id="halmae", started_at=T0))
            mixed = [fix(0, 0), fix(5, 7)]
            mixed.append(WalkFix(at=T0 + timedelta(seconds=10), lat=mixed[0].lat,
                                 lng=mixed[0].lng, accuracy_m=10.0, is_mock=True))
            await store.append_fixes(db, sid, mixed)
            mocks = (await db.execute(text(
                "SELECT mock_fix_count FROM walk_session WHERE id = :id"), {"id": sid}
            )).scalar_one()
            assert mocks == 1
        finally:
            await _cleanup(db)
