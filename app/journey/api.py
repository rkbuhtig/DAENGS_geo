"""POST /journey — 카드를 눌렀을 때의 한 장. 검색과 분리된 공용 엔드포인트.

입력: 출발지, 목적지(우리 place id 또는 좌표), companion(dog|none), 프로필, journey 선호.
출력: 목적지별 Transport(실측 경로·spots·advice·핸드오프·폴리라인).
검색 응답(/hospital/search)은 휴리스틱만 실어 가볍게, 실측은 여기서 — 관심 있는 것만 호출.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.geo.models import Place
from app.journey.engine import snapshot
from app.journey.models import Companion, Transport
from app.profile.source import profile_source
from app.providers.base import LatLng
from app.refine.state import JourneyPrefs

router = APIRouter(prefix="/journey", tags=["journey"])


class Dest(BaseModel):
    id: int | None = None            # 우리 place id (있으면 좌표·이름을 DB에서)
    lat: float | None = None
    lng: float | None = None
    name: str = ""


class JourneyIn(BaseModel):
    origin: tuple[float, float]
    dests: list[Dest] = Field(min_length=1, max_length=10)
    companion: Companion = "dog"
    dog_id: str | None = None
    prefs: JourneyPrefs = Field(default_factory=JourneyPrefs)
    measured: bool = True
    with_polyline: bool = True
    arrive_note: str | None = None    # 도착 지점 한마디. 도메인이 넘긴다 (journey 는 병원을 모른다)


class JourneyItem(BaseModel):
    id: int | None
    name: str
    lat: float
    lng: float
    transport: Transport


class JourneyOut(BaseModel):
    companion: Companion
    items: list[JourneyItem]


@router.post("", response_model=JourneyOut)
async def journey(body: JourneyIn, db: Annotated[AsyncSession, Depends(get_session)]) -> JourneyOut:
    profile = await profile_source().get(body.dog_id) if (body.dog_id and body.companion == "dog") else None
    origin = LatLng(*body.origin)

    # id → 좌표·이름
    ids = [d.id for d in body.dests if d.id is not None]
    rows: dict[int, tuple[str, float, float]] = {}
    if ids:
        from geoalchemy2 import Geometry
        geom = cast(Place.location, Geometry)
        res = await db.execute(select(Place.id, Place.name, func.ST_Y(geom), func.ST_X(geom)).where(Place.id.in_(ids)))
        rows = {pid: (name, lat, lng) for pid, name, lat, lng in res.all()}

    items: list[JourneyItem] = []
    for d in body.dests:
        if d.id is not None:
            if d.id not in rows:
                raise HTTPException(404, f"place {d.id} not found")
            name, lat, lng = rows[d.id]
        elif d.lat is not None and d.lng is not None:
            name, lat, lng = d.name, d.lat, d.lng
        else:
            raise HTTPException(422, "dest needs id or lat/lng")
        t = await snapshot(
            origin, LatLng(lat, lng), companion=body.companion, measured=body.measured,
            mode=body.prefs.preferred_mode, walk_option=body.prefs.walk.option,
            walk_max=body.prefs.walk.max_walk_min, avoid=body.prefs.walk.avoid,
            profile=profile, dest_name=name, with_polyline=body.with_polyline,
            arrive_note=body.arrive_note,
        )
        items.append(JourneyItem(id=d.id, name=name, lat=lat, lng=lng, transport=t))
    return JourneyOut(companion=body.companion, items=items)
