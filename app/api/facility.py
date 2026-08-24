"""GET /facility/search — 반려동물 동반 문화시설 검색. 기반층(facility)만 읽는다.

의료(hospital/pharmacy)는 여기서 안 나온다 — 존재 권위가 place(인허가)에 있어
/hospital, /pharmacy 가 담당한다. 축 재배치가 끝나면 이 표면 밑으로 위임된다.

같은 시설이 두 원천에 있으면(교차 링크) 링크의 ref로 잡힌 쪽(과거 원천)을 숨긴다.
결과엔 항목마다 원천과 기준일이 붙는다 — 2025-03 스냅샷이 낡았음을 숨기지 않는다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

router = APIRouter(prefix="/facility", tags=["facility"])

MEDICAL = ("hospital", "pharmacy")


class FacilityParams(BaseModel):
    lat: float = Field(ge=32, le=40)
    lng: float = Field(ge=123, le=133)
    radius_m: int = Field(3000, ge=100, le=20000)
    kind: str | None = None            # cafe/travel/grooming/... 미지정 = 비의료 전체
    limit: int = Field(20, ge=1, le=50)


class FacilitySourceOut(BaseModel):
    name: str                          # kcisa | kto
    as_of: str                         # 스냅샷 날짜 또는 원천 수정일


class FacilityOut(BaseModel):
    id: int
    name: str
    kind: str
    category3: str
    lat: float
    lng: float
    distance_m: int
    address: str | None
    phone: str | None
    homepage: str | None
    hours_text: str | None
    closed_days: str | None
    parking: bool | None
    pet: dict
    source: FacilitySourceOut


class FacilitySearchOut(BaseModel):
    params: FacilityParams
    results: list[FacilityOut]


_SEARCH = text("""
SELECT f.id, f.name, f.kind, f.category3,
       ST_Y(f.location::geometry) AS lat, ST_X(f.location::geometry) AS lng,
       ST_Distance(f.location, o.geom) AS distance_m,
       f.address, f.phone, f.homepage, f.hours_text, f.closed_days, f.parking,
       f.pet, f.source, COALESCE(f.last_written::text, f.snapshot) AS as_of
FROM facility f,
     (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS geom) o
WHERE f.kind <> ALL(:medical)
  AND (CAST(:kind AS text) IS NULL OR f.kind = :kind)
  AND ST_DWithin(f.location, o.geom, :radius_m)
  AND NOT EXISTS (SELECT 1 FROM facility_link l
                  WHERE l.source = 'facility' AND l.source_ref = f.id::text)
ORDER BY distance_m
LIMIT :limit
""")


@router.get("/search", response_model=FacilitySearchOut)
async def facility_search(
    params: Annotated[FacilityParams, Query()],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FacilitySearchOut:
    rows = await db.execute(_SEARCH, {
        "lat": params.lat, "lng": params.lng, "radius_m": params.radius_m,
        "kind": params.kind, "limit": params.limit, "medical": list(MEDICAL),
    })
    results = [
        FacilityOut(
            id=r.id, name=r.name, kind=r.kind, category3=r.category3,
            lat=r.lat, lng=r.lng, distance_m=int(r.distance_m),
            address=r.address, phone=r.phone, homepage=r.homepage,
            hours_text=r.hours_text, closed_days=r.closed_days, parking=r.parking,
            pet=r.pet or {},
            source=FacilitySourceOut(name=r.source, as_of=r.as_of),
        )
        for r in rows
    ]
    return FacilitySearchOut(params=params, results=results)
