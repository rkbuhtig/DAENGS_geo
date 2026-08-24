"""산책 세션 API — 수집만. Agent Router 바깥, Usage Gate 무관(외부 호출 0).

    POST /walk/sessions                시작. 멱등 — 같은 id 재전송 OK
    POST /walk/sessions/{id}/fixes     위치 배치 업로드 → 수신 계수만 응답
    POST /walk/sessions/{id}/finish    종료 → WalkFacts 확정·fix 삭제. 멱등
    GET  /walk/sessions/{id}           세션 + (끝났으면) 사실

응답에 판정·트리거·서술이 없는 것은 생략이 아니라 계약이다 — walk-record.md.
그건 WalkFacts 소비자의 일이고, 이 API 는 사실이 서버에 남게 하는 것까지만 한다.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.walk import store
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFacts, WalkFix, WalkSession

router = APIRouter(prefix="/walk", tags=["walk"])


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    dog_id: str = Field(min_length=1, max_length=128)
    started_at: datetime

    @field_validator("started_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("walk timestamps must include a timezone")
        return v


class FixBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixes: list[WalkFix] = Field(min_length=1, max_length=2000)


class FixBatchOut(BaseModel):
    stored: int
    fix_count: int


class FinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ended_at: datetime

    @field_validator("ended_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("walk timestamps must include a timezone")
        return v


class FinishOut(BaseModel):
    facts: WalkFacts
    quality: dict


class SessionOut(BaseModel):
    session: WalkSession
    facts: WalkFacts | None = None


async def _session_or_404(db: AsyncSession, session_id: str) -> WalkSession:
    s = await store.get_session(db, session_id)
    if s is None:
        raise HTTPException(404, "walk session not found")
    return s


@router.post("/sessions", response_model=WalkSession)
async def start_session(
    body: StartIn, db: Annotated[AsyncSession, Depends(get_session)]
) -> WalkSession:
    existing = await store.get_session(db, body.id)
    if existing is not None:
        if existing.dog_id != body.dog_id:
            raise HTTPException(409, "session id belongs to another dog")
        return existing                      # 멱등 재전송 — 상태 그대로
    s = await store.upsert_session(
        db, WalkSession(id=body.id, dog_id=body.dog_id, started_at=body.started_at)
    )
    await db.commit()
    return s


@router.post("/sessions/{session_id}/fixes", response_model=FixBatchOut)
async def upload_fixes(
    session_id: str, body: FixBatchIn, db: Annotated[AsyncSession, Depends(get_session)]
) -> FixBatchOut:
    s = await _session_or_404(db, session_id)
    if s.ended_at is not None:
        raise HTTPException(409, "walk session already finished")
    total = await store.append_fixes(db, session_id, body.fixes)
    await db.commit()
    return FixBatchOut(stored=len(body.fixes), fix_count=total)


@router.post("/sessions/{session_id}/finish", response_model=FinishOut)
async def finish_session(
    session_id: str, body: FinishIn, db: Annotated[AsyncSession, Depends(get_session)]
) -> FinishOut:
    s = await _session_or_404(db, session_id)
    stored = await store.get_facts(db, session_id)
    if stored is not None:                   # 멱등 — 확정된 사실은 다시 계산하지 않는다
        facts, quality = stored
        return FinishOut(facts=facts, quality=quality)
    if body.ended_at < s.started_at:
        raise HTTPException(422, "ended_at must not precede started_at")

    fixes = await store.load_fixes_ordered(db, session_id)
    computed = compute_facts(s.id, s.dog_id, s.started_at, body.ended_at, fixes)
    await store.finalize(db, computed.facts, computed.quality)
    await db.commit()
    return FinishOut(facts=computed.facts, quality=computed.quality.to_dict())


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def read_session(
    session_id: str, db: Annotated[AsyncSession, Depends(get_session)]
) -> SessionOut:
    s = await _session_or_404(db, session_id)
    stored = await store.get_facts(db, session_id)
    return SessionOut(session=s, facts=stored[0] if stored else None)
