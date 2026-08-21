"""POST /hospital/search — 검색 상태 편집기 + 검색. **가볍다.**

진입: 메뉴(state 없음→초안) · 딥링크(클라가 파라미터→state) · 재조정(edits=UI, utterance=자연어/음성).
LLM은 utterance 있을 때만. 팀 챗봇은 여기 안 옴 — 카드 딥링크로 들어올 뿐.

transport는 휴리스틱(호출 0)만 실어 리스트 비교용. 실측 경로·spots·advice는 카드를 눌렀을 때 POST /journey.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.enrich.community import attach_evidence
from app.geo.schemas import MapOut, PlaceOut
from app.geo.search import build_map, find_places
from app.journey.engine import snapshot
from app.journey.models import Companion, Transport
from app.planning.facts import RuntimeFacts, SystemClock
from app.planning.plans import JourneyPlan, ViewPlan
from app.planning.resolver import resolve_request
from app.planning.state import EditableState
from app.profile.source import owner_of, profile_source
from app.providers.base import LatLng
from app.refine.engine import refine
from app.refine.nl import ToolCall
from app.refine.tools import ToolInputError

router = APIRouter(prefix="/hospital", tags=["hospital"])

# 병원 도메인이 소유하는 문구. 공용 journey/spots 는 "진료"를 몰라야 한다.
ARRIVE_NOTE = "도착 — 간판·층수 확인, 진료 전 전화 권장"
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
Origin = tuple[Latitude, Longitude]
PositiveId = Annotated[int, Field(ge=1)]


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    args: dict = Field(default_factory=dict, max_length=10)


class HospitalSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dog_id: str | None = Field(None, max_length=128)
    origin: Origin | None = None                    # (lat, lng). state 없을 때 필수
    state: EditableState | None = None
    edits: list[Edit] = Field(default_factory=list, max_length=20)
    utterance: str | None = Field(None, max_length=2000)
    shown_ids: list[PositiveId] = Field(default_factory=list, max_length=100)
    transport: Literal["none", "estimate"] = "estimate"   # 검색 응답은 휴리스틱까지만. 실측은 /journey
    companion: Companion = "dog"              # 병원은 개 동반이 기본. "나만 감"이면 none
    with_evidence: bool = True

    @model_validator(mode="after")
    def location_is_required(self) -> "HospitalSearchIn":
        if self.state is None and self.origin is None:
            raise ValueError("origin or state required")
        return self


class EvidenceOut(BaseModel):
    source: str
    text: str
    url: str


class ResultOut(PlaceOut):
    transport: Transport | None = None
    evidence: list[EvidenceOut] = Field(default_factory=list)   # 표시 전용 — 순위에 안 들어간다
    boost: int = 0                     # prefer_hit 만. 정렬 부스트 근거 (표시용)


class ResolutionOut(BaseModel):
    axis: str
    what: str
    because: str = ""
    overrode: str = ""


class HospitalSearchOut(BaseModel):
    state: EditableState
    results: list[ResultOut]
    map: MapOut
    changes: list[str]
    changes_by_policy: dict[str, list[str]] = Field(default_factory=dict)
    applied: list[Edit]
    question: str | None = None
    reply: str
    resolution: list[ResolutionOut] = Field(default_factory=list)
    show_call_cta: bool = False
    call_reasons: list[str] = Field(default_factory=list)


def _reply(changes: list[str], n: int, question: str | None, unknown_hours: int = 0) -> str:
    if question:
        return question
    head = " · ".join(changes)
    if not n:
        return f"{head}. 조건에 맞는 곳이 없어요 — 반경을 넓히거나 필터를 풀어볼까요?"
    # '지금 영업중'을 걸었는데 영업시간을 모르는 곳이 섞여 있으면 말해줘야 한다.
    # 안 그러면 전부 확정 영업중으로 읽힌다 (공공데이터엔 영업시간이 없다).
    tail = f" 그중 {unknown_hours}곳은 영업시간 미상이에요 — 전화로 확인해주세요." if unknown_hours else ""
    return f"{head}. {n}곳.{tail}"


@router.post("/search", response_model=HospitalSearchOut)
async def hospital_search(
    body: HospitalSearchIn,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> HospitalSearchOut:
    profile = await profile_source().get(body.dog_id) if body.dog_id else None
    owner = await owner_of(body.dog_id) if body.dog_id else None
    lat, lng = body.origin or (body.state.lat, body.state.lng)  # type: ignore[union-attr]

    try:
        r = await refine(
            body.state, [ToolCall(e.tool, e.args) for e in body.edits], body.utterance,
            body.shown_ids, profile, lat, lng, settings.default_radius_m,
        )
    except ToolInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    st = r.state
    resolved = resolve_request(
        st,
        RuntimeFacts(now=SystemClock().now(), profile=profile, owner=owner),
        kind="hospital",
        companion=body.companion,
        measured=False,
        transport_available=body.transport == "estimate",
    )

    # 각 엔진에는 자기 plan만 준다. state·facts를 다시 주워 읽는 우회로는 없다.
    places = await find_places(db, resolved.search)

    # 근거는 state 가 시킨다 — 그 턴에 말을 했는지가 아니라. utterance 는 여기 못 들어온다.
    ev = (await attach_evidence(st.target.symptoms, st.target.specialty, profile, places)
          if body.with_evidence else {})
    results: list[ResultOut] = []
    for p in places:
        t = None
        if body.transport == "estimate":
            t = await snapshot(
                resolved.journey, LatLng(p.lat, p.lng),
                dest_name=p.name, with_polyline=False,
                arrive_note=ARRIVE_NOTE,
            )
        e = [EvidenceOut(source=x.source, text=x.text, url=x.url) for x in ev.get(p.id, [])]
        # evidence 가 과목 신호의 **본체**다 (query-rewrite-experiment.md) — 이름 태그(prefer_hit)는
        # 전국 몇 곳짜리 보조 신호일 뿐이다. 순위 권한을 줘도 되는 이유: 쿼리가 state(symptoms·
        # specialty)에서 나오므로 같은 state 는 같은 근거를 얻는다. 한 턴의 발화 유무로 순위가
        # 흔들리던 1번 버그와 다르다. 밴드 밖은 못 뒤집는 건 _sort 가 보장한다.
        results.append(ResultOut(**p.model_dump(), transport=t, evidence=e,
                                 boost=len(p.prefer_hit) * 2 + len(e)))

    # journey.hard_limit: 정책 경계를 넘는 유일한 스위치. 사용자가 명시적으로 켤 때만
    dropped = 0
    if resolved.journey.hard_limit and resolved.journey.max_total_min is not None:
        keep, mode = [], resolved.journey.mode_priority[0]
        for res in results:
            leg = getattr(res.transport, mode, None) if res.transport else None
            if leg and leg.min > resolved.journey.max_total_min:
                dropped += 1
                continue
            keep.append(res)
        results = keep

    results = _sort(results, resolved.view, resolved.journey)
    must = resolved.search.must
    mp = build_map(must.lat, must.lng, must.radius_m, "hospital", must.open_now,
                   st.target.night_service, results)
    return HospitalSearchOut(
        state=st, results=results, map=mp, changes=r.changes, changes_by_policy=r.grouped,
        applied=[Edit(tool=c.tool, args=c.args) for c in r.applied],
        question=r.question,
        reply=_reply(r.changes, len(results), r.question,
                     sum(1 for x in results if x.open_now is None) if must.open_now else 0)
        + (f" ({dropped}곳은 시간 초과로 제외)" if dropped else ""),
        resolution=[ResolutionOut(**vars(entry)) for entry in resolved.trace.entries],
        show_call_cta=resolved.view.show_call_cta,
        call_reasons=list(resolved.view.call_reasons),
    )


def _sort(results: list[ResultOut], view: ViewPlan, journey: JourneyPlan) -> list[ResultOut]:
    """부스트는 '살짝 위' — 같은 밴드(500m / 5분) 안에서만 순서를 바꾼다. 거리·시간을 뒤집진 않는다."""
    def key(r: ResultOut):
        pinned = 0 if r.id in view.pin_ids else 1
        if view.sort == "open_first":
            primary, band = (0 if r.open_now else 1), (0 if r.open_now else 1)
        elif view.sort == "duration" and r.transport and journey.mode_priority:
            leg = getattr(r.transport, journey.mode_priority[0])
            primary = leg.min if leg else 10**6
            band = primary // 5
        else:
            primary = r.distance_m
            band = primary // 500
        return (pinned, band, -r.boost, primary)
    return sorted(results, key=key)
