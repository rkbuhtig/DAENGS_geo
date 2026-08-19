"""POST /hospital/search — 검색 상태 편집기 + 검색. **가볍다.**

진입: 메뉴(state 없음→초안) · 딥링크(클라가 파라미터→state) · 재조정(edits=UI, utterance=자연어/음성).
LLM은 utterance 있을 때만. 팀 챗봇은 여기 안 옴 — 카드 딥링크로 들어올 뿐.

transport는 휴리스틱(호출 0)만 실어 리스트 비교용. 실측 경로·spots·advice는 카드를 눌렀을 때 POST /journey.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.enrich.community import attach_evidence
from app.geo.schemas import MapOut, PlaceOut
from app.geo.search import build_map, find_places
from app.journey.engine import snapshot
from app.journey.models import Companion, Transport
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
    transport: Literal["none", "estimate"] = "estimate"   # 검색 응답은 휴리스틱까지만. 실측은 /journey
    companion: Companion = "dog"              # 병원은 개 동반이 기본. "나만 감"이면 none
    with_evidence: bool = True


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
    changes_by_policy: dict[str, list[str]] = Field(default_factory=dict)
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

    # --- target 정책: 결과 집합 결정. journey 값은 절대 여기 들어오지 않는다 (state.py 참조)
    tg = st.target
    places = await find_places(
        db, lat=st.lat, lng=st.lng, radius_m=tg.radius_m, kind="hospital",
        open_now=tg.open_now, night=tg.night, emergency=tg.emergency,
        specialty=tg.specialty, require_tags=tg.require_tags, exclude_ids=tg.exclude_ids,
        at=tg.at, limit=tg.limit,
    )

    # 근거는 맥락(발화·특화)이 있을 때만. 초안에 붙이면 무관한 부스트가 거리순을 흐린다
    want_ev = body.with_evidence and (bool(body.utterance) or bool(tg.specialty))
    ev = await attach_evidence(body.utterance, profile, places) if want_ev else {}
    origin_pt = LatLng(st.lat, st.lng)
    results: list[ResultOut] = []
    for p in places:
        t = None
        if body.transport == "estimate":
            # --- journey 정책: 경로·advice만. 결과를 빼지 않는다. 여기선 휴리스틱만(호출 0)
            jn = st.journey
            t = await snapshot(
                origin_pt, LatLng(p.lat, p.lng), companion=body.companion, measured=False, mode=jn.mode,
                walk_option=jn.walk.option, walk_max=jn.max_min, avoid=jn.walk.avoid,
                profile=profile, dest_name=p.name, with_polyline=False,
            )
        e = [EvidenceOut(source=x.source, text=x.text, url=x.url) for x in ev.get(p.id, [])]
        results.append(ResultOut(**p.model_dump(), transport=t, evidence=e,
                                 boost=len(p.specialty_hit) * 2 + len(e)))

    # journey.hard_limit: 정책 경계를 넘는 유일한 스위치. 사용자가 명시적으로 켤 때만
    dropped = 0
    if st.journey.hard_limit and st.journey.max_min is not None:
        keep, mode = [], st.journey.mode or "walk"
        for res in results:
            leg = getattr(res.transport, mode, None) if res.transport else None
            if leg and leg.min > st.journey.max_min:
                dropped += 1
                continue
            keep.append(res)
        results = keep

    results = _sort(results, st)
    mp = build_map(st.lat, st.lng, tg.radius_m, "hospital", tg.open_now, tg.night, results)
    return HospitalSearchOut(
        state=st, results=results, map=mp, changes=r.changes, changes_by_policy=r.grouped,
        applied=[Edit(tool=c.tool, args=c.args) for c in r.applied],
        question=r.question,
        reply=_reply(r.changes, len(results), r.question) + (f" ({dropped}곳은 시간 초과로 제외)" if dropped else ""),
    )


def _sort(results: list[ResultOut], st: SearchState) -> list[ResultOut]:
    """부스트는 '살짝 위' — 같은 밴드(500m / 5분) 안에서만 순서를 바꾼다. 거리·시간을 뒤집진 않는다."""
    def key(r: ResultOut):
        pinned = 0 if r.id in st.target.pin_ids else 1
        if st.sort == "open_first":
            primary, band = (0 if r.open_now else 1), (0 if r.open_now else 1)
        elif st.sort == "duration" and r.transport and st.journey.mode:
            leg = getattr(r.transport, st.journey.mode)
            primary = leg.min if leg else 10**6
            band = primary // 5
        else:
            primary = r.distance_m
            band = primary // 500
        return (pinned, band, -r.boost, primary)
    return sorted(results, key=key)
