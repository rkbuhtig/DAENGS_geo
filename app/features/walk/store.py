"""산책 세션 저장. 원칙 하나: **fix 는 파생 사실이 확정될 때까지만 있다.**

finish가 SEALED → DERIVED → PURGED를 같은 트랜잭션에서 통과한다. 공간 정지 이벤트를
포함한 파생 사실이 먼저고 삭제가 마지막이다. 궤적 영구 보관은 프라이버시 정책이
서기 전까지 하지 않는다 (008_walk_collection_hardening.sql).
"""

import json
import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.walk.facts import FixQuality
from app.features.walk.models import MotionEventOccurrence, WalkFacts, WalkFix, WalkSession


class WalkSessionNotFoundError(Exception):
    pass


class WalkSessionNotOpenError(Exception):
    pass


class EvidenceOriginConflictError(Exception):
    pass


class FixSequenceConflictError(Exception):
    pass


@dataclass(frozen=True)
class AppendResult:
    stored: int
    duplicates: int
    fix_count: int


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
        SELECT id, dog_id, started_at, ended_at, fix_count, state, evidence_origin
        FROM walk_session WHERE id = :id
    """), {"id": session_id})).one_or_none()
    if row is None:
        return None
    return WalkSession(id=row.id, dog_id=row.dog_id, started_at=row.started_at,
                       ended_at=row.ended_at, fix_count=row.fix_count, state=row.state,
                       evidence_origin=row.evidence_origin)


async def lock_session(db: AsyncSession, session_id: str) -> WalkSession | None:
    """업로드와 finish가 공유하는 직렬화 지점."""
    row = (await db.execute(text("""
        SELECT id, dog_id, started_at, ended_at, fix_count, state, evidence_origin
        FROM walk_session WHERE id = :id FOR UPDATE
    """), {"id": session_id})).one_or_none()
    if row is None:
        return None
    return WalkSession(id=row.id, dog_id=row.dog_id, started_at=row.started_at,
                       ended_at=row.ended_at, fix_count=row.fix_count, state=row.state,
                       evidence_origin=row.evidence_origin)


async def append_fixes(
    db: AsyncSession, session_id: str, fixes: list[WalkFix]
) -> AppendResult:
    """client_seq로 재전송을 제거하고, seq에는 서버 수신 순서를 따로 보존한다."""
    session = await lock_session(db, session_id)
    if session is None:
        raise WalkSessionNotFoundError(session_id)
    if session.state != "open":
        raise WalkSessionNotOpenError(session_id)

    origins = {f.is_mock for f in fixes}
    if len(origins) != 1:
        raise EvidenceOriginConflictError("one batch cannot mix device and mock fixes")
    incoming_origin = "mock" if True in origins else "device"
    if session.evidence_origin not in ("unknown", incoming_origin):
        raise EvidenceOriginConflictError("a session cannot mix device and mock fixes")

    seqs = [f.client_seq for f in fixes]
    if len(seqs) != len(set(seqs)):
        raise FixSequenceConflictError("client_seq must be unique within a batch")
    rows = await db.execute(text("""
        SELECT client_seq, at, lat, lng, accuracy_m, is_mock
        FROM walk_fix
        WHERE session_id = :id AND client_seq = ANY(CAST(:seqs AS integer[]))
    """), {"id": session_id, "seqs": seqs})
    existing = {r.client_seq: r for r in rows}
    for f in fixes:
        row = existing.get(f.client_seq)
        if row is None:
            continue
        same_accuracy = (
            row.accuracy_m is None and f.accuracy_m is None
            or row.accuracy_m is not None and f.accuracy_m is not None
            and math.isclose(row.accuracy_m, f.accuracy_m, abs_tol=1e-5)
        )
        if not (
            row.at == f.at
            and math.isclose(row.lat, f.lat, abs_tol=1e-12)
            and math.isclose(row.lng, f.lng, abs_tol=1e-12)
            and same_accuracy
            and row.is_mock == f.is_mock
        ):
            raise FixSequenceConflictError(
                f"client_seq {f.client_seq} was already stored with different data"
            )

    new_fixes = [f for f in fixes if f.client_seq not in existing]
    if new_fixes:
        await db.execute(text("""
            INSERT INTO walk_fix
                (session_id, seq, client_seq, at, lat, lng, accuracy_m, is_mock)
            VALUES (:sid, :seq, :client_seq, :at, :lat, :lng, :accuracy_m, :is_mock)
        """), [
            {"sid": session_id, "seq": session.fix_count + i,
             "client_seq": f.client_seq, "at": f.at, "lat": f.lat, "lng": f.lng,
             "accuracy_m": f.accuracy_m, "is_mock": f.is_mock}
            for i, f in enumerate(new_fixes)
        ])
    total = session.fix_count + len(new_fixes)
    await db.execute(text("""
        UPDATE walk_session SET
            fix_count = :n,
            mock_fix_count = mock_fix_count + :mocks,
            evidence_origin = :origin,
            updated_at = now()
        WHERE id = :id
    """), {"id": session_id, "n": total, "origin": incoming_origin,
           "mocks": sum(1 for f in new_fixes if f.is_mock)})
    return AppendResult(stored=len(new_fixes), duplicates=len(fixes) - len(new_fixes),
                        fix_count=total)


async def load_fixes_ordered(db: AsyncSession, session_id: str) -> list[WalkFix]:
    """계산 입력. 측정 시각 우선, 동시각이면 수신 순서 — 재생하면 같은 열이 나온다."""
    rows = await db.execute(text("""
        SELECT client_seq, at, lat, lng, accuracy_m, is_mock
        FROM walk_fix WHERE session_id = :id ORDER BY client_seq, seq
    """), {"id": session_id})
    return [WalkFix(client_seq=r.client_seq, at=r.at, lat=r.lat, lng=r.lng,
                    accuracy_m=r.accuracy_m, is_mock=r.is_mock) for r in rows]


async def finalize(
    db: AsyncSession,
    facts: WalkFacts,
    quality: FixQuality,
    events: list[MotionEventOccurrence],
) -> None:
    """SEALED → DERIVED → PURGED. 파생 사실을 쓴 뒤에만 원좌표를 지운다."""
    await db.execute(text("""
        UPDATE walk_session SET state = 'sealed', ended_at = :ended_at, updated_at = now()
        WHERE id = :id
    """), {"id": facts.session_id, "ended_at": facts.ended_at})
    await db.execute(text("""
        INSERT INTO walk_facts (session_id, record_version, calculation_version, dog_id,
                                evidence_origin, started_at, ended_at,
                                duration_s, distance_m, moving_distance_m, moving_s,
                                stop_count, stop_s, avg_speed_mps, fix_count, quality)
        VALUES (:session_id, :record_version, :calculation_version, :dog_id,
                :evidence_origin, :started_at, :ended_at,
                :duration_s, :distance_m, :moving_distance_m, :moving_s,
                :stop_count, :stop_s, :avg_speed_mps, :fix_count, CAST(:quality AS jsonb))
    """), {**facts.model_dump(), "quality": json.dumps(quality.to_dict())})
    if events:
        await db.execute(text("""
            INSERT INTO walk_motion_event
                (session_id, event_index, type, started_at, ended_at, duration_s, location,
                 route_offset_m, accuracy_p50_m, fix_count)
            VALUES (:session_id, :event_index, :type, :started_at, :ended_at, :duration_s,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    :route_offset_m, :accuracy_p50_m, :fix_count)
        """), [e.model_dump() for e in events])
    await db.execute(text("""
        UPDATE walk_session SET state = 'derived', updated_at = now() WHERE id = :id
    """), {"id": facts.session_id})
    await db.execute(text("DELETE FROM walk_fix WHERE session_id = :id"),
                     {"id": facts.session_id})
    await db.execute(text("""
        UPDATE walk_session SET state = 'purged', updated_at = now() WHERE id = :id
    """), {"id": facts.session_id})


async def get_facts(db: AsyncSession, session_id: str) -> tuple[WalkFacts, dict] | None:
    row = (await db.execute(text("""
        SELECT session_id, record_version, calculation_version, dog_id, evidence_origin,
               started_at, ended_at, duration_s, distance_m,
               moving_distance_m, moving_s, stop_count, stop_s, avg_speed_mps,
               fix_count, quality
        FROM walk_facts WHERE session_id = :id
    """), {"id": session_id})).one_or_none()
    if row is None:
        return None
    data = dict(row._mapping)
    quality = data.pop("quality")
    return WalkFacts(**data), quality


async def get_events(db: AsyncSession, session_id: str) -> list[MotionEventOccurrence]:
    rows = await db.execute(text("""
        SELECT session_id, event_index, type, started_at, ended_at, duration_s,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng,
               route_offset_m, accuracy_p50_m, fix_count
        FROM walk_motion_event WHERE session_id = :id ORDER BY event_index
    """), {"id": session_id})
    return [MotionEventOccurrence(**dict(r._mapping)) for r in rows]
