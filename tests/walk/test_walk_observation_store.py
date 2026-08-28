"""미시 관측이 **원좌표 삭제를 넘어 산다** — 이 층의 존재 이유를 저장 계층에서 고정한다.

순수함수 쪽은 `test_walk_observation.py`. 여기서 묻는 것은 하나다: finish 가 fix 를 지운
뒤에도 지표를 다시 계산할 재료가 DB 에 남아 있나.
"""

from datetime import timedelta

from sqlalchemy import text

from app.features.walk import store
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkSession
from app.features.walk.observation import (
    MICRO_OBSERVATION_VERSION,
    extract_observations,
    moving_speed_profile,
)
from tests.conftest import WALK_T0, db_session, walk_fix

SID = "test:walk:observation"


async def _cleanup(session):
    await session.execute(text("DELETE FROM walk_session WHERE id LIKE 'test:walk:%'"))
    await session.commit()


async def test_observations_outlive_the_purge():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await store.upsert_session(
                db, WalkSession(id=SID, dog_id="halmae", started_at=WALK_T0))
            # 걷다(1.4m/s) → 서다 → 걷다. 가운데가 후보 창이 된다
            fixes = [walk_fix(t, t * 1.4) for t in range(20)]
            fixes += [walk_fix(t, 26.6) for t in range(20, 60)]
            fixes += [walk_fix(t, 26.6 + (t - 60) * 1.4) for t in range(60, 80)]
            await store.append_fixes(db, SID, fixes)

            loaded = await store.load_fixes_ordered(db, SID)
            ended = WALK_T0 + timedelta(seconds=80)
            computed = compute_facts(SID, "halmae", WALK_T0, ended, loaded)
            observations = extract_observations(SID, computed.segments, computed.gaps)
            profile = moving_speed_profile(computed.segments)
            assert observations and profile is not None

            await store.finalize(
                db, computed.facts, computed.quality, computed.events, (), None,
                observations, profile,
            )
            await db.commit()

            remaining = (await db.execute(text(
                "SELECT count(*) FROM walk_fix WHERE session_id = :id"), {"id": SID}
            )).scalar_one()
            assert remaining == 0, "원좌표가 남아 있다 — 저장 정책 위반"

            # 원좌표가 없는 지금, 관측은 그대로 읽힌다
            kept = await store.get_observations(db, SID)
            assert len(kept) == len(observations)
            for a, b in zip(kept, observations, strict=True):
                assert a.kind == b.kind and a.index == b.index
                assert abs(a.duration_s - b.duration_s) < 0.01
                assert abs(a.path_m - b.path_m) < 0.01
                assert abs(a.lat - b.lat) < 1e-6 and abs(a.lng - b.lng) < 1e-6

            kept_profile = await store.get_speed_profile(db, SID)
            assert kept_profile is not None
            assert abs(kept_profile.p80 - profile.p80) < 0.01

            # 그리고 그 재료로 지표를 다시 계산할 수 있다 — 이 PR 의 수용 기준
            excess = sum(max(0.0, o.duration_s - o.path_m / kept_profile.p50)
                         for o in kept if o.kind == "slow")
            assert excess > 30

            version = (await db.execute(text(
                "SELECT DISTINCT observation_version FROM walk_micro_observation "
                "WHERE session_id = :id"), {"id": SID})).scalars().all()
            assert version == [MICRO_OBSERVATION_VERSION]
        finally:
            await _cleanup(db)


async def test_deleting_a_session_takes_its_observations():
    """사용자 삭제가 파생층을 남기지 않는다 — cascade 가 실제로 걸려 있나."""
    async with db_session() as db:
        await _cleanup(db)
        try:
            await store.upsert_session(
                db, WalkSession(id=SID, dog_id="halmae", started_at=WALK_T0))
            fixes = [walk_fix(t, 0.0) for t in range(30)]
            await store.append_fixes(db, SID, fixes)
            loaded = await store.load_fixes_ordered(db, SID)
            computed = compute_facts(SID, "halmae", WALK_T0,
                                     WALK_T0 + timedelta(seconds=30), loaded)
            await store.finalize(
                db, computed.facts, computed.quality, computed.events, (), None,
                extract_observations(SID, computed.segments, computed.gaps),
                moving_speed_profile(computed.segments),
            )
            await db.commit()
            assert await store.get_observations(db, SID)

            await db.execute(text("DELETE FROM walk_session WHERE id = :id"), {"id": SID})
            await db.commit()
            assert await store.get_observations(db, SID) == []
        finally:
            await _cleanup(db)
