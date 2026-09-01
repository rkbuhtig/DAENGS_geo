"""dev intent lab 검색을 재현할 최소 append-only 관측 저장소."""

import json
import logging
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.place.planning.contract import PlanningModel

logger = logging.getLogger(__name__)


class AttemptStatus(StrEnum):
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class SearchEventType(StrEnum):
    SEARCH_COMPLETED = "search_completed"
    SEARCH_FAILED = "search_failed"
    SEARCH_REVISED = "search_revised"
    LENS_SELECTED = "lens_selected"
    FACET_SELECTED = "facet_selected"
    LENS_CONFIRMED = "lens_confirmed"
    SEARCH_RESET = "search_reset"


class SearchAttemptRecord(PlanningModel):
    attempt_id: UUID
    previous_attempt_id: UUID | None = None
    utterance: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=120)
    lat: float
    lng: float
    radius_m: int = Field(ge=100, le=20000)
    status: AttemptStatus
    failure_code: str | None = Field(None, max_length=120)
    interpretation_count: int = Field(ge=0)
    target_lens_count: int = Field(ge=0)
    executable_lens_count: int = Field(ge=0)
    result_count: int = Field(ge=0)
    snapshot: dict[str, Any] = Field(default_factory=dict)


class ObservedSearchAttempt(PlanningModel):
    attempt_id: UUID
    previous_attempt_id: UUID | None = None
    utterance: str
    model: str
    status: AttemptStatus
    failure_code: str | None = None
    interpretation_count: int
    target_lens_count: int
    executable_lens_count: int
    result_count: int
    snapshot: dict[str, Any]
    created_at: datetime


async def record_attempt(db: AsyncSession, record: SearchAttemptRecord) -> None:
    await db.execute(
        text(
            """
            INSERT INTO place_intent_lab_attempt (
                id, previous_attempt_id, utterance, model, lat, lng, radius_m,
                status, failure_code, interpretation_count, target_lens_count,
                executable_lens_count, result_count, snapshot
            ) VALUES (
                :id, :previous_attempt_id, :utterance, :model, :lat, :lng, :radius_m,
                :status, :failure_code, :interpretation_count, :target_lens_count,
                :executable_lens_count, :result_count, CAST(:snapshot AS jsonb)
            )
            """
        ),
        {
            "id": record.attempt_id,
            "previous_attempt_id": record.previous_attempt_id,
            "utterance": record.utterance,
            "model": record.model,
            "lat": record.lat,
            "lng": record.lng,
            "radius_m": record.radius_m,
            "status": record.status.value,
            "failure_code": record.failure_code,
            "interpretation_count": record.interpretation_count,
            "target_lens_count": record.target_lens_count,
            "executable_lens_count": record.executable_lens_count,
            "result_count": record.result_count,
            "snapshot": json.dumps(record.snapshot, ensure_ascii=False),
        },
    )
    await db.commit()


async def record_event(
    db: AsyncSession,
    *,
    attempt_id: UUID,
    event_type: SearchEventType,
    lens_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO place_intent_lab_event (attempt_id, event_type, lens_id, details)
            VALUES (:attempt_id, :event_type, :lens_id, CAST(:details AS jsonb))
            """
        ),
        {
            "attempt_id": attempt_id,
            "event_type": event_type.value,
            "lens_id": lens_id,
            "details": json.dumps(details or {}, ensure_ascii=False),
        },
    )
    await db.commit()


async def safely_record_attempt(db: AsyncSession, record: SearchAttemptRecord) -> bool:
    """관측 스키마 장애가 실제 검색 응답을 가리지 않게 한다."""

    try:
        await record_attempt(db, record)
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("place intent lab attempt observation failed")
        return False
    return True


async def safely_record_event(db: AsyncSession, **kwargs: Any) -> bool:
    try:
        await record_event(db, **kwargs)
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("place intent lab interaction observation failed")
        return False
    return True


async def list_attempts(
    db: AsyncSession,
    *,
    limit: int,
    failures_only: bool,
) -> tuple[ObservedSearchAttempt, ...]:
    where = "WHERE failure_code IS NOT NULL" if failures_only else ""
    result = await db.execute(
        text(
            f"""
            SELECT id, previous_attempt_id, utterance, model, status, failure_code,
                   interpretation_count, target_lens_count, executable_lens_count,
                   result_count, snapshot, created_at
            FROM place_intent_lab_attempt
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return tuple(
        ObservedSearchAttempt(
            attempt_id=row["id"],
            previous_attempt_id=row["previous_attempt_id"],
            utterance=row["utterance"],
            model=row["model"],
            status=AttemptStatus(row["status"]),
            failure_code=row["failure_code"],
            interpretation_count=row["interpretation_count"],
            target_lens_count=row["target_lens_count"],
            executable_lens_count=row["executable_lens_count"],
            result_count=row["result_count"],
            snapshot=row["snapshot"],
            created_at=row["created_at"],
        )
        for row in result.mappings()
    )
