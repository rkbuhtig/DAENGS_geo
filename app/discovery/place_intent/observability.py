"""dev intent lab 검색을 재현할 최소 append-only 관측 저장소."""

import json
import logging
from datetime import datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.place_intent.contract import ProposalDisposition, ProposalReason
from app.place.planning.contract import PlanningModel

logger = logging.getLogger(__name__)


class AttemptStatus(StrEnum):
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class SearchResponseMode(StrEnum):
    """사용자에게 실제로 반환한 제품 응답의 형태."""

    DIRECT_RESULTS = "direct_results"
    EXPLORATORY_RESULTS = "exploratory_results"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"
    PROVIDER_FAILURE = "provider_failure"


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
    proposer_disposition: ProposalDisposition | None = None
    proposer_reason: ProposalReason | None = None
    response_mode: SearchResponseMode
    fallback_policy_id: str | None = Field(
        None,
        max_length=120,
        pattern=r"^[a-z0-9_.:-]+$",
    )
    fallback_policy_version: str | None = Field(
        None,
        max_length=40,
        pattern=r"^[a-z0-9_.:-]+$",
    )
    interpretation_count: int = Field(ge=0)
    target_lens_count: int = Field(ge=0)
    executable_lens_count: int = Field(ge=0)
    result_count: int = Field(ge=0)
    snapshot: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def observation_metadata_is_consistent(self) -> Self:
        if self.proposer_disposition is None:
            if self.proposer_reason is not None:
                raise ValueError("proposer reason requires a proposer disposition")
        elif self.proposer_disposition is ProposalDisposition.PROPOSED:
            if self.proposer_reason is not None:
                raise ValueError("proposed disposition cannot carry a reason")
        elif self.proposer_disposition is ProposalDisposition.AMBIGUOUS:
            if self.proposer_reason is not ProposalReason.MULTIPLE_PLAUSIBLE_READINGS:
                raise ValueError("ambiguous disposition requires its matching reason")
        elif self.proposer_reason is None:
            raise ValueError("abstained disposition requires a reason")
        if (self.fallback_policy_id is None) != (self.fallback_policy_version is None):
            raise ValueError("fallback policy id and version must be supplied together")
        if self.status is AttemptStatus.COMPLETED and self.response_mode not in {
            SearchResponseMode.DIRECT_RESULTS,
            SearchResponseMode.EXPLORATORY_RESULTS,
        }:
            raise ValueError("completed attempt requires a result response mode")
        if self.status is AttemptStatus.NEEDS_CLARIFICATION and self.response_mode not in {
            SearchResponseMode.CLARIFICATION,
            SearchResponseMode.UNSUPPORTED,
        }:
            raise ValueError("non-completed product outcome requires clarification or unsupported")
        if (
            self.status is AttemptStatus.FAILED
            and self.response_mode is not SearchResponseMode.PROVIDER_FAILURE
        ):
            raise ValueError("failed attempt requires provider_failure response mode")
        return self


class ObservedSearchAttempt(PlanningModel):
    attempt_id: UUID
    previous_attempt_id: UUID | None = None
    utterance: str
    model: str
    status: AttemptStatus
    failure_code: str | None = None
    proposer_disposition: ProposalDisposition | None = None
    proposer_reason: ProposalReason | None = None
    response_mode: SearchResponseMode
    fallback_policy_id: str | None = None
    fallback_policy_version: str | None = None
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
                status, failure_code, proposer_disposition, proposer_reason,
                response_mode, fallback_policy_id, fallback_policy_version,
                interpretation_count, target_lens_count,
                executable_lens_count, result_count, snapshot
            ) VALUES (
                :id, :previous_attempt_id, :utterance, :model, :lat, :lng, :radius_m,
                :status, :failure_code, :proposer_disposition, :proposer_reason,
                :response_mode, :fallback_policy_id, :fallback_policy_version,
                :interpretation_count, :target_lens_count,
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
            "proposer_disposition": (
                record.proposer_disposition.value if record.proposer_disposition else None
            ),
            "proposer_reason": record.proposer_reason.value if record.proposer_reason else None,
            "response_mode": record.response_mode.value,
            "fallback_policy_id": record.fallback_policy_id,
            "fallback_policy_version": record.fallback_policy_version,
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
                   proposer_disposition, proposer_reason, response_mode,
                   fallback_policy_id, fallback_policy_version,
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
            proposer_disposition=(
                ProposalDisposition(row["proposer_disposition"])
                if row["proposer_disposition"]
                else None
            ),
            proposer_reason=(ProposalReason(row["proposer_reason"]) if row["proposer_reason"] else None),
            response_mode=SearchResponseMode(row["response_mode"]),
            fallback_policy_id=row["fallback_policy_id"],
            fallback_policy_version=row["fallback_policy_version"],
            interpretation_count=row["interpretation_count"],
            target_lens_count=row["target_lens_count"],
            executable_lens_count=row["executable_lens_count"],
            result_count=row["result_count"],
            snapshot=row["snapshot"],
            created_at=row["created_at"],
        )
        for row in result.mappings()
    )
