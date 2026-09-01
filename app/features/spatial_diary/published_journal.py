"""파생 WalkJournal을 사용자가 제목·요약·대표 Pin과 함께 고정하는 비공개 불변본."""

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.spatial_diary.contract import PublishedJournalSnapshot
from app.features.spatial_diary.episode import (
    SpatialDiaryEpisodeConflictError,
    SpatialDiaryEpisodeNotFoundError,
)
from app.features.spatial_diary.journal import query_walk_journal
from app.features.spatial_diary.snapshot import ensure_repeatable_read_snapshot


def _snapshot_from_row(row) -> PublishedJournalSnapshot:
    return PublishedJournalSnapshot(
        snapshot_id=row.snapshot_id,
        snapshot_version=row.snapshot_version,
        session_id=row.session_id,
        visibility=row.visibility,
        title=row.title,
        summary=row.summary,
        selected_pin_ids=tuple(row.selected_pin_ids),
        source_projection_version=row.source_projection_version,
        source_narration_policy_version=row.source_narration_policy_version,
        source_context_policy_version=row.source_context_policy_version,
        source_capsule_version=row.source_capsule_version,
        published_at=row.published_at,
    )


async def published_journal_dog_id(db: AsyncSession, snapshot_id: str) -> str:
    row = (
        await db.execute(
            text("""
        SELECT manifest.dog_id
        FROM spatial_diary_published_journal snapshot
        JOIN walk_capsule_manifest manifest ON manifest.session_id = snapshot.session_id
        WHERE snapshot.snapshot_id = :snapshot_id
    """),
            {"snapshot_id": snapshot_id},
        )
    ).one_or_none()
    if row is None:
        raise SpatialDiaryEpisodeNotFoundError("published journal snapshot not found")
    return row.dog_id


async def get_published_journal_snapshot(
    db: AsyncSession,
    snapshot_id: str,
) -> PublishedJournalSnapshot:
    await ensure_repeatable_read_snapshot(db)
    row = (
        await db.execute(
            text("""
        SELECT snapshot_id, snapshot_version, session_id, visibility,
               title, summary, selected_pin_ids,
               source_projection_version, source_narration_policy_version,
               source_context_policy_version, source_capsule_version,
               published_at
        FROM spatial_diary_published_journal
        WHERE snapshot_id = :snapshot_id
    """),
            {"snapshot_id": snapshot_id},
        )
    ).one_or_none()
    if row is None:
        raise SpatialDiaryEpisodeNotFoundError("published journal snapshot not found")
    return _snapshot_from_row(row)


async def list_published_journal_snapshots(
    db: AsyncSession,
    session_id: str,
) -> tuple[PublishedJournalSnapshot, ...]:
    await ensure_repeatable_read_snapshot(db)
    rows = (
        await db.execute(
            text("""
        SELECT snapshot_id, snapshot_version, session_id, visibility,
               title, summary, selected_pin_ids,
               source_projection_version, source_narration_policy_version,
               source_context_policy_version, source_capsule_version,
               published_at
        FROM spatial_diary_published_journal
        WHERE session_id = :session_id
        ORDER BY published_at, snapshot_id
    """),
            {"session_id": session_id},
        )
    ).all()
    return tuple(_snapshot_from_row(row) for row in rows)


def _same_request(
    snapshot: PublishedJournalSnapshot,
    *,
    session_id: str,
    title: str,
    summary: str,
    selected_pin_ids: tuple[str, ...],
) -> bool:
    return (
        snapshot.session_id == session_id
        and snapshot.title == title
        and snapshot.summary == summary
        and snapshot.selected_pin_ids == selected_pin_ids
    )


async def put_published_journal_snapshot(
    db: AsyncSession,
    *,
    snapshot_id: str,
    session_id: str,
    title: str,
    summary: str,
    selected_pin_ids: tuple[str, ...] = (),
    published_at: datetime | None = None,
) -> PublishedJournalSnapshot:
    """처음 PUT만 고정한다. 같은 내용의 재시도만 기존 불변본을 돌려준다."""

    await ensure_repeatable_read_snapshot(db)
    try:
        existing = await get_published_journal_snapshot(db, snapshot_id)
    except SpatialDiaryEpisodeNotFoundError:
        existing = None
    if existing is not None:
        if _same_request(
            existing,
            session_id=session_id,
            title=title,
            summary=summary,
            selected_pin_ids=selected_pin_ids,
        ):
            return existing
        raise SpatialDiaryEpisodeConflictError("snapshot id already has different content")

    journal = await query_walk_journal(db, session_id)
    available_pin_ids = {entry.pin.pin_id for entry in journal.entries}
    unknown_pin_ids = set(selected_pin_ids) - available_pin_ids
    if unknown_pin_ids:
        raise SpatialDiaryEpisodeConflictError(
            "selected pins must belong to the source walk journal"
        )

    snapshot = PublishedJournalSnapshot(
        snapshot_id=snapshot_id,
        session_id=session_id,
        title=title,
        summary=summary,
        selected_pin_ids=selected_pin_ids,
        source_projection_version=journal.receipt.projection_version,
        source_narration_policy_version=journal.receipt.narration_policy_version,
        source_context_policy_version=journal.receipt.context_policy_version,
        source_capsule_version=journal.receipt.capsule_version,
        published_at=published_at or datetime.now(UTC),
    )
    inserted = await db.execute(
        text("""
        INSERT INTO spatial_diary_published_journal
            (snapshot_id, snapshot_version, session_id, visibility,
             title, summary, selected_pin_ids,
             source_projection_version, source_narration_policy_version,
             source_context_policy_version, source_capsule_version, published_at)
        VALUES
            (:snapshot_id, :snapshot_version, :session_id, :visibility,
             :title, :summary, CAST(:selected_pin_ids AS jsonb),
             :source_projection_version, :source_narration_policy_version,
             :source_context_policy_version, :source_capsule_version, :published_at)
        ON CONFLICT (snapshot_id) DO NOTHING
        RETURNING snapshot_id
    """),
        {
            **snapshot.model_dump(exclude={"selected_pin_ids"}),
            "selected_pin_ids": json.dumps(list(snapshot.selected_pin_ids)),
        },
    )
    if inserted.scalar_one_or_none() is None:
        stored = await get_published_journal_snapshot(db, snapshot_id)
        if _same_request(
            stored,
            session_id=session_id,
            title=title,
            summary=summary,
            selected_pin_ids=selected_pin_ids,
        ):
            return stored
        raise SpatialDiaryEpisodeConflictError("snapshot id already has different content")
    return snapshot
