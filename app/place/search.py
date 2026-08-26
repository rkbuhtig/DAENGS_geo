"""종류별 Place 발견을 조율하는 canonical 검색 서비스.

각 resolver는 자기 원천의 존재·병합 규칙을 유지한다. 이 계층은 요청한 kind를 알맞은
resolver로 보내고 공통 `PlaceResult`로 바꾼 뒤, 종류 안에서만 순수 거리순을 보장한다.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.search import find_places
from app.ingest.kcisa import KINDS as KCISA_KINDS
from app.ingest.kto import KINDS as KTO_KINDS
from app.place.adapters import facility_place_result, medical_place_result
from app.place.contracts import PlaceResult
from app.place.facility_resolver import (
    MAX_RESULTS,
    FacilityParams,
    resolve_facilities,
)
from app.planning.facts import SystemClock
from app.planning.plans import SearchMust, SearchPlan


class PlaceKind(StrEnum):
    HOSPITAL = "hospital"
    PHARMACY = "pharmacy"
    PET_SHOP = "pet_shop"
    SHOPPING = "shopping"
    GROOMING = "grooming"
    BOARDING = "boarding"
    TRAVEL = "travel"
    LEISURE = "leisure"
    MUSEUM = "museum"
    GALLERY = "gallery"
    ARTS_CENTER = "arts_center"
    CULTURE = "culture"
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    PENSION = "pension"
    HOTEL = "hotel"
    STAY = "stay"
    ETC = "etc"


MEDICAL_KINDS = frozenset({PlaceKind.HOSPITAL, PlaceKind.PHARMACY})
PLACE_KINDS = frozenset(PlaceKind)
_MAPPED_KINDS = {*KCISA_KINDS.values(), *KTO_KINDS.values(), "etc"}
_UNDECLARED_KINDS = _MAPPED_KINDS - {kind.value for kind in PLACE_KINDS}
if _UNDECLARED_KINDS:
    raise RuntimeError(
        "ingest mapping contains undeclared Place kinds: "
        + ", ".join(sorted(_UNDECLARED_KINDS))
    )


class PlaceSearchRequest(BaseModel):
    lat: float = Field(ge=32, le=40)
    lng: float = Field(ge=123, le=133)
    radius_m: int = Field(3000, ge=100, le=20000)
    kinds: list[PlaceKind] = Field(min_length=1, max_length=len(PLACE_KINDS))
    # 지도는 반경 안 후보를 가능한 한 보되 서버 상한은 명시한다. 잘렸는지는 group이 말한다.
    limit_per_kind: int | None = Field(None, ge=1, le=MAX_RESULTS)

    @field_validator("kinds", mode="before")
    @classmethod
    def reject_unknown_kinds(cls, values):
        if not isinstance(values, list):
            return values
        if "goods" in values:
            raise ValueError("goods was split into pet_shop and shopping")
        known = {kind.value for kind in PLACE_KINDS}
        unknown = sorted({value for value in values if isinstance(value, str)} - known)
        if unknown:
            raise ValueError(f"unknown place kinds: {', '.join(unknown)}")
        return values

    @field_validator("kinds")
    @classmethod
    def require_unique_kinds(cls, values: list[PlaceKind]) -> list[PlaceKind]:
        if len(set(values)) != len(values):
            raise ValueError("kinds must be unique")
        return values


class PlaceSort(BaseModel):
    type: Literal["distance"] = "distance"
    basis: tuple[Literal["distance_m"], ...] = ("distance_m",)


class PlaceSearchGroup(BaseModel):
    kind: PlaceKind
    sort: PlaceSort = Field(default_factory=PlaceSort)
    truncated: bool = False
    results: list[PlaceResult]


class PlaceSearchResponse(BaseModel):
    groups: list[PlaceSearchGroup]


def _distance_key(result: PlaceResult) -> tuple[int, str, str]:
    return result.distance_m, result.key.source, result.key.ref


async def _medical_group(
    db: AsyncSession,
    request: PlaceSearchRequest,
    kind: PlaceKind,
    limit: int,
) -> PlaceSearchGroup:
    rows = await find_places(
        db,
        SearchPlan(must=SearchMust(
            lat=request.lat,
            lng=request.lng,
            radius_m=request.radius_m,
            judge_at=SystemClock().now(),
            kind=kind.value,
            limit=limit + 1,
        )),
        # canonical category search는 이름 파생 cat_only 신호로 후보를 조용히 빼지 않는다.
        only_dog_ok=False,
    )
    truncated = len(rows) > limit
    results = sorted((medical_place_result(row) for row in rows), key=_distance_key)[:limit]
    return PlaceSearchGroup(kind=kind, truncated=truncated, results=results)


async def _facility_group(
    db: AsyncSession,
    request: PlaceSearchRequest,
    kind: PlaceKind,
    limit: int,
) -> PlaceSearchGroup:
    resolved = await resolve_facilities(
        FacilityParams(
            lat=request.lat,
            lng=request.lng,
            radius_m=request.radius_m,
            kind=kind.value,
            limit=limit,
            only_dog_ok=False,
        ),
        db,
    )
    results = sorted(
        (facility_place_result(row) for row in resolved.results), key=_distance_key,
    )
    return PlaceSearchGroup(kind=kind, truncated=resolved.truncated, results=results)


async def search_place_groups(
    db: AsyncSession,
    request: PlaceSearchRequest,
) -> PlaceSearchResponse:
    """요청 kind 순서를 보존하고, 서로 다른 kind 사이에는 순위를 만들지 않는다."""
    limit = request.limit_per_kind or MAX_RESULTS
    groups: list[PlaceSearchGroup] = []
    for kind in request.kinds:
        if kind in MEDICAL_KINDS:
            group = await _medical_group(db, request, kind, limit)
        else:
            group = await _facility_group(db, request, kind, limit)
        groups.append(group)
    return PlaceSearchResponse(groups=groups)
