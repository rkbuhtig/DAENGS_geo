"""산책 세션 저장. 원칙 하나: **fix 는 세션이 살아 있는 동안만 있다.**

finish 가 사실을 확정하면 같은 트랜잭션에서 fix 를 지운다. 궤적 영구 보관은
프라이버시 정책이 서기 전까지 하지 않는다 (007_walk_sessions.sql 머리말).
"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.walk.facts import FixQuality
from app.features.walk.models import WalkFacts, WalkFix, WalkSession


async def upsert_session(db: AsyncSession, s: WalkSession) -> WalkSession:
    """멱등 시작. 같은 id 가 다시 오면 기존 세션을 그대로 돌려준다 (재전송·재시작)."""
    await db.execute(text("""
        INSERT INTO walk_session (id, dog_id, started_at)
        VALUES (:id, :dog_id, :started_at)
        ON CONFLICT (id) DO NOTHING
    """), {"id": s.id, "dog_id": s.dog_id, "started_at": s.started_at})
    return await get_session(db, s.id)  # type: ignore[return-value]  # 방금 넣었다


async def get_session(db: AsyncSession, session_id: str) -> WalkSession | None:
    row = (await db.execute(text("""
        SELECT id, dog_id, started_at, ended_at, fix_count
        FROM walk_session WHERE id = :id
    """), {"id": session_id})).one_or_none()
    if row is None:
        return None
    return WalkSession(id=row.id, dog_id=row.dog_id, started_at=row.started_at,
                       ended_at=row.ended_at, fix_count=row.fix_count)


async def append_fixes(db: AsyncSession, session_id: str, fixes: list[WalkFix]) -> int:
    """수신 순서(seq)와 측정 시각(at)을 둘 다 보존한다. 반환은 세션 누적 수신 수."""
    offset = (await db.execute(text(
        "SELECT fix_count FROM walk_session WHERE id = :id FOR UPDATE"
    ), {"id": session_id})).scalar_one()
    await db.execute(text("""
        INSERT INTO walk_fix (session_id, seq, at, lat, lng, accuracy_m, is_mock)
        VALUES (:sid, :seq, :at, :lat, :lng, :accuracy_m, :is_mock)
    """), [
        {"sid": session_id, "seq": offset + i, "at": f.at, "lat": f.lat, "lng": f.lng,
         "accuracy_m": f.accuracy_m, "is_mock": f.is_mock}
        for i, f in enumerate(fixes)
    ])
    total = offset + len(fixes)
    await db.execute(text("""
        UPDATE walk_session SET
            fix_count = :n,
            mock_fix_count = mock_fix_count + :mocks,
            updated_at = now()
        WHERE id = :id
    """), {"id": session_id, "n": total,
           "mocks": sum(1 for f in fixes if f.is_mock)})
    return total


async def load_fixes_ordered(db: AsyncSession, session_id: str) -> list[WalkFix]:
    """계산 입력. 측정 시각 우선, 동시각이면 수신 순서 — 재생하면 같은 열이 나온다."""
    rows = await db.execute(text("""
        SELECT at, lat, lng, accuracy_m, is_mock
        FROM walk_fix WHERE session_id = :id ORDER BY at, seq
    """), {"id": session_id})
    return [WalkFix(at=r.at, lat=r.lat, lng=r.lng, accuracy_m=r.accuracy_m,
                    is_mock=r.is_mock) for r in rows]


async def finalize(db: AsyncSession, facts: WalkFacts, quality: FixQuality) -> None:
    """사실 확정 + 세션 종료 + **fix 삭제** — 한 트랜잭션."""
    await db.execute(text("""
        INSERT INTO walk_facts (session_id, record_version, dog_id, started_at, ended_at,
                                duration_s, distance_m, moving_distance_m, moving_s,
                                stop_count, stop_s, avg_speed_mps, fix_count, quality)
        VALUES (:session_id, :record_version, :dog_id, :started_at, :ended_at,
                :duration_s, :distance_m, :moving_distance_m, :moving_s,
                :stop_count, :stop_s, :avg_speed_mps, :fix_count, CAST(:quality AS jsonb))
    """), {**facts.model_dump(), "quality": json.dumps(quality.to_dict())})
    await db.execute(text("""
        UPDATE walk_session SET ended_at = :ended_at, updated_at = now() WHERE id = :id
    """), {"id": facts.session_id, "ended_at": facts.ended_at})
    await db.execute(text("DELETE FROM walk_fix WHERE session_id = :id"),
                     {"id": facts.session_id})


async def get_facts(db: AsyncSession, session_id: str) -> tuple[WalkFacts, dict] | None:
    row = (await db.execute(text("""
        SELECT session_id, dog_id, started_at, ended_at, duration_s, distance_m,
               moving_distance_m, moving_s, stop_count, stop_s, avg_speed_mps,
               fix_count, quality
        FROM walk_facts WHERE session_id = :id
    """), {"id": session_id})).one_or_none()
    if row is None:
        return None
    data = dict(row._mapping)
    quality = data.pop("quality")
    return WalkFacts(**data), quality
