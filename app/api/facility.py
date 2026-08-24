"""GET /facility/search — 반려동물 동반 문화시설 검색. 기반층(facility)만 읽는다.

의료(hospital/pharmacy)는 여기서 안 나온다 — 존재 권위가 place(인허가)에 있어
/hospital, /pharmacy 가 담당한다. 축 재배치가 끝나면 이 표면 밑으로 위임된다.

같은 시설이 두 원천에 있으면 노출 행은 하나지만 **필드는 병합한다** — 존재·이름·좌표는
최신 원천, 그 원천이 안 주는 운영시간·주차·홈페이지는 과거 원천에서 빌린다.
행 단위 승자독식으로 숨기면 KTO(목록만)가 KCISA(운영시간 보유)를 가려서 정보가 사라진다.
의료 쪽 `attach_facility_hours` 와 같은 철학이다: 존재는 한 원천이, 필드는 있는 쪽이.

빌린 필드에는 `field_sources` 로 어느 원천의 언제 값인지가 붙는다 —
2025-03 스냅샷이 낡았음을 숨기지 않는다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.geo.icons import IconGroup, icon_group

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
    id: int                            # 내부 PK. 외부가 잡을 식별자는 (source, source_ref)
    source_ref: str | None
    name: str
    kind: str
    icon_group: IconGroup      # 지도 마커 그룹. kind 가 늘어도 앱은 이 값만 본다
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
    field_sources: dict[str, FacilitySourceOut] = Field(default_factory=dict)


class FacilitySearchOut(BaseModel):
    params: FacilityParams
    results: list[FacilityOut]


# 노출 행: 교차 링크의 ref 로 잡힌 쪽(과거 원천)은 빼고, 그 행을 LATERAL 로 끌어와
# 빈 필드를 채운다. 링크가 없으면 o.* 는 전부 NULL 이고 결과는 원래 행 그대로다.
_SEARCH = text("""
SELECT f.id, f.source_ref, f.name, f.kind, f.category3,
       ST_Y(f.location::geometry) AS lat, ST_X(f.location::geometry) AS lng,
       ST_Distance(f.location, o.geom) AS distance_m,
       f.address, f.phone, f.homepage, f.hours_text, f.closed_days, f.parking,
       f.pet, f.source, COALESCE(f.last_written::text, f.snapshot) AS as_of,
       b.homepage AS b_homepage, b.hours_text AS b_hours_text,
       b.closed_days AS b_closed_days, b.parking AS b_parking, b.pet AS b_pet,
       b.source AS b_source, COALESCE(b.last_written::text, b.snapshot) AS b_as_of
FROM facility f
CROSS JOIN (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS geom) o
LEFT JOIN LATERAL (
    SELECT f2.homepage, f2.hours_text, f2.closed_days, f2.parking, f2.pet,
           f2.source, f2.last_written, f2.snapshot
    FROM facility_link l
    JOIN facility f2 ON f2.id = l.source_ref::bigint
    WHERE l.source = 'facility' AND l.facility_id = f.id
    ORDER BY (f2.hours_text IS NULL), f2.last_written DESC NULLS LAST
    LIMIT 1
) b ON true
WHERE f.kind <> ALL(:medical)
  AND (CAST(:kind AS text) IS NULL OR f.kind = :kind)
  AND ST_DWithin(f.location, o.geom, :radius_m)
  AND NOT EXISTS (SELECT 1 FROM facility_link l
                  WHERE l.source = 'facility' AND l.source_ref = f.id::text)
ORDER BY distance_m
LIMIT :limit
""")

# 빌려올 수 있는 필드. 값이 비어 있을 때만 뒤 원천에서 가져온다.
_BORROWABLE = ("homepage", "hours_text", "closed_days", "parking", "pet")


def _merge(row) -> tuple[dict, dict]:
    """(필드값, 필드별 출처). 자기 원천 값이 있으면 그대로, 없으면 링크된 원천에서 빌린다."""
    values = {name: getattr(row, name) for name in _BORROWABLE}
    borrowed: dict[str, FacilitySourceOut] = {}
    if row.b_source is None:
        return values, borrowed
    for name in _BORROWABLE:
        own, other = values[name], getattr(row, f"b_{name}")
        if own in (None, {}, "") and other not in (None, {}, ""):
            values[name] = other
            borrowed[name] = FacilitySourceOut(name=row.b_source, as_of=row.b_as_of)
    return values, borrowed


@router.get("/search", response_model=FacilitySearchOut)
async def facility_search(
    params: Annotated[FacilityParams, Query()],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> FacilitySearchOut:
    rows = await db.execute(_SEARCH, {
        "lat": params.lat, "lng": params.lng, "radius_m": params.radius_m,
        "kind": params.kind, "limit": params.limit, "medical": list(MEDICAL),
    })
    results = []
    for r in rows:
        values, borrowed = _merge(r)
        results.append(FacilityOut(
            id=r.id, source_ref=r.source_ref, name=r.name, kind=r.kind,
            icon_group=icon_group(r.kind), category3=r.category3,
            lat=r.lat, lng=r.lng, distance_m=int(r.distance_m),
            address=r.address, phone=r.phone,
            homepage=values["homepage"], hours_text=values["hours_text"],
            closed_days=values["closed_days"], parking=values["parking"],
            pet=values["pet"] or {},
            source=FacilitySourceOut(name=r.source, as_of=r.as_of),
            field_sources=borrowed,
        ))
    return FacilitySearchOut(params=params, results=results)
