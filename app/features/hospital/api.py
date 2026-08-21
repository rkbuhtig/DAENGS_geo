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
from app.planning.state import EditableState
from app.profile.source import profile_source
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


class HospitalSearchOut(BaseModel):
    state: EditableState
    results: list[ResultOut]
    map: MapOut
    changes: list[str]
    changes_by_policy: dict[str, list[str]] = Field(default_factory=dict)
    applied: list[Edit]
    question: str | None = None
    reply: str


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
    lat, lng = body.origin or (body.state.lat, body.state.lng)  # type: ignore[union-attr]

    try:
        r = await refine(
            body.state, [ToolCall(e.tool, e.args) for e in body.edits], body.utterance,
            body.shown_ids, profile, lat, lng, settings.default_radius_m,
        )
    except ToolInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    st = r.state

    # --- target 정책: 결과 집합 결정. journey 값은 절대 여기 들어오지 않는다 (state.py 참조)
    tg = st.target
    # time_intent → 영업 판정 시각. **이 사영은 resolver 자리다** (step 4): 지금은 한 줄이지만
    # journey 의 야간 판정도 같은 값을 봐야 하고, 그걸 각자 주워 쓰다 어긋난 게 이 사달이었다.
    service_at = (st.time_intent.at
                  if st.time_intent and st.time_intent.kind == "service_at" else None)
    places = await find_places(
        db, lat=st.lat, lng=st.lng, radius_m=tg.radius_m, kind="hospital",
        open_now=tg.open_now, night=tg.night_service, emergency=tg.emergency_service,
        specialty=tg.specialty, require_tags=tg.require_tags, exclude_ids=tg.exclude_ids,
        at=service_at, limit=tg.limit,
    )

    # 근거는 state 가 시킨다 — 그 턴에 말을 했는지가 아니라. utterance 는 여기 못 들어온다.
    ev = (await attach_evidence(tg.symptoms, tg.specialty, profile, places)
          if body.with_evidence else {})
    origin_pt = LatLng(st.lat, st.lng)
    results: list[ResultOut] = []
    for p in places:
        t = None
        if body.transport == "estimate":
            # --- journey 정책: 경로·advice만. 결과를 빼지 않는다. 여기선 휴리스틱만(호출 0)
            jn = st.journey
            t = await snapshot(
                origin_pt, LatLng(p.lat, p.lng), companion=body.companion, measured=False,
                mode=jn.preferred_mode, walk_option=jn.walk.option,
                walk_max=jn.walk.max_walk_min,          # 개가 걸어도 되는 시간 (전체 이동시간 아님)
                avoid=jn.walk.avoid, profile=profile, dest_name=p.name, with_polyline=False,
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
    if st.journey.hard_limit and st.journey.max_total_min is not None:
        keep, mode = [], st.journey.preferred_mode or "walk"
        for res in results:
            leg = getattr(res.transport, mode, None) if res.transport else None
            if leg and leg.min > st.journey.max_total_min:
                dropped += 1
                continue
            keep.append(res)
        results = keep

    results = _sort(results, st)
    mp = build_map(st.lat, st.lng, tg.radius_m, "hospital", tg.open_now, tg.night_service,
                   results)
    return HospitalSearchOut(
        state=st, results=results, map=mp, changes=r.changes, changes_by_policy=r.grouped,
        applied=[Edit(tool=c.tool, args=c.args) for c in r.applied],
        question=r.question,
        reply=_reply(r.changes, len(results), r.question,
                     sum(1 for x in results if x.open_now is None) if tg.open_now else 0)
        + (f" ({dropped}곳은 시간 초과로 제외)" if dropped else ""),
    )


def _sort(results: list[ResultOut], st: EditableState) -> list[ResultOut]:
    """부스트는 '살짝 위' — 같은 밴드(500m / 5분) 안에서만 순서를 바꾼다. 거리·시간을 뒤집진 않는다."""
    def key(r: ResultOut):
        pinned = 0 if r.id in st.target.pin_ids else 1
        if st.sort == "open_first":
            primary, band = (0 if r.open_now else 1), (0 if r.open_now else 1)
        elif st.sort == "duration" and r.transport and st.journey.preferred_mode:
            leg = getattr(r.transport, st.journey.preferred_mode)
            primary = leg.min if leg else 10**6
            band = primary // 5
        else:
            primary = r.distance_m
            band = primary // 500
        return (pinned, band, -r.boost, primary)
    return sorted(results, key=key)
