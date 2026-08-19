"""POST /hospital/search — 검색 상태 편집기 + 검색 + 스냅샷.

진입: 메뉴(state 없음→초안) · 딥링크(클라가 파라미터→state) · 재조정(edits=UI, utterance=자연어/음성).
LLM은 utterance 있을 때만. 팀 챗봇은 여기 안 옴 — 카드 딥링크로 들어올 뿐.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.enrich.community import attach_evidence
from app.geo.schemas import MapOut, PlaceOut
from app.geo.search import build_map, find_places
from app.geo.transport import Transport, snapshot_for
from app.profile.source import profile_source
from app.providers.base import LatLng
from app.refine.engine import refine
from app.refine.nl import ToolCall
from app.refine.state import SearchState

router = APIRouter(prefix="/hospital", tags=["hospital"])


class Edit(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class HospitalSearchIn(BaseModel):
    dog_id: str | None = None
    origin: tuple[float, float] | None = None       # (lat, lng). state 없을 때 필수
    state: SearchState | None = None
    edits: list[Edit] = Field(default_factory=list)
    utterance: str | None = None
    shown_ids: list[int] = Field(default_factory=list)
    with_transport: bool = True
    with_evidence: bool = True
    with_polyline_for: int | None = None      # 이 병원 id만 도보 폴리라인 포함 (상세 화면)


class EvidenceOut(BaseModel):
    source: str
    text: str
    url: str


class ResultOut(PlaceOut):
    transport: Transport | None = None
    evidence: list[EvidenceOut] = Field(default_factory=list)
    boost: int = 0                     # specialty_hit + evidence 수. 정렬 부스트 근거 (표시용)


class HospitalSearchOut(BaseModel):
    state: SearchState
    results: list[ResultOut]
    map: MapOut
    changes: list[str]
    applied: list[Edit]
    question: str | None = None
    reply: str


def _reply(changes: list[str], n: int, question: str | None) -> str:
    if question:
        return question
    head = " · ".join(changes)
    return f"{head}. {n}곳." if n else f"{head}. 조건에 맞는 곳이 없어요 — 반경을 넓히거나 필터를 풀어볼까요?"


@router.post("/search", response_model=HospitalSearchOut)
async def hospital_search(
    body: HospitalSearchIn,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> HospitalSearchOut:
    profile = await profile_source().get(body.dog_id) if body.dog_id else None
    if body.state is None and body.origin is None:
        raise ValueError("origin or state required")
    lat, lng = body.origin or (body.state.lat, body.state.lng)  # type: ignore[union-attr]

    r = await refine(
        body.state, [ToolCall(e.tool, e.args) for e in body.edits], body.utterance,
        body.shown_ids, profile, lat, lng, settings.default_radius_m,
    )
    st = r.state

    places = await find_places(
        db, lat=st.lat, lng=st.lng, radius_m=st.radius_m, kind="hospital",
        open_now=st.open_now, night=st.night, emergency=st.emergency,
        specialty=st.specialty, require_tags=st.require_tags, exclude_ids=st.exclude_ids,
        at=st.at, limit=st.limit,
    )

    # 근거는 맥락(발화·특화)이 있을 때만. 초안에 붙이면 무관한 부스트가 거리순을 흐린다
    want_ev = body.with_evidence and (bool(body.utterance) or bool(st.specialty))
    ev = await attach_evidence(body.utterance, profile, places) if want_ev else {}
    origin_pt = LatLng(st.lat, st.lng)
    results: list[ResultOut] = []
    for i, p in enumerate(places):
        t = None
        if body.with_transport:
            t = await snapshot_for(
                origin_pt, LatLng(p.lat, p.lng), rank=i, mode=st.mode,
                walk_option=st.walk.option, walk_max=st.walk.max_min, avoid=st.walk.avoid,
                profile=profile, dest_name=p.name,
                with_polyline=(body.with_polyline_for == p.id),
            )
        e = [EvidenceOut(source=x.source, text=x.text, url=x.url) for x in ev.get(p.id, [])]
        results.append(ResultOut(**p.model_dump(), transport=t, evidence=e,
                                 boost=len(p.specialty_hit) * 2 + len(e)))

    results = _sort(results, st)
    mp = build_map(st.lat, st.lng, st.radius_m, "hospital", st.open_now, st.night, results)
    return HospitalSearchOut(
        state=st, results=results, map=mp, changes=r.changes,
        applied=[Edit(tool=c.tool, args=c.args) for c in r.applied],
        question=r.question, reply=_reply(r.changes, len(results), r.question),
    )


def _sort(results: list[ResultOut], st: SearchState) -> list[ResultOut]:
    """부스트는 '살짝 위' — 같은 밴드(500m / 5분) 안에서만 순서를 바꾼다. 거리·시간을 뒤집진 않는다."""
    def key(r: ResultOut):
        pinned = 0 if r.id in st.pin_ids else 1
        if st.sort == "open_first":
            primary, band = (0 if r.open_now else 1), (0 if r.open_now else 1)
        elif st.sort == "duration" and r.transport and st.mode:
            leg = getattr(r.transport, st.mode)
            primary = leg.min if leg else 10**6
            band = primary // 5
        else:
            primary = r.distance_m
            band = primary // 500
        return (pinned, band, -r.boost, primary)
    return sorted(results, key=key)
