"""종류별 Place 발견을 조율하는 canonical 검색 서비스.

각 resolver는 자기 원천의 존재·병합 규칙을 유지한다. 이 계층은 요청한 kind를 알맞은
resolver로 보내고 공통 `PlaceResult`로 바꾼 뒤, 종류 안에서만 순수 거리순을 보장한다.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.kcisa import KINDS as KCISA_KINDS
from app.ingest.kto import KINDS as KTO_KINDS
from app.ingest.mois import SOURCES as MOIS_SOURCES
from app.place.adapters import facility_place_result, medical_place_result
from app.place.contracts import PlaceResult
from app.place.evaluations import DogAccessEvaluation, evaluate_dog_access
from app.place.facility_resolver import (
    MAX_RESULTS,
    FacilityParams,
    resolve_facilities,
)
from app.place.medical_resolver import resolve_medical_places
from app.planning.facts import SystemClock
from app.profile.contract import SizeClass
from app.profile.source import profile_source


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
MAX_KINDS_PER_REQUEST = 6
MAX_TOTAL_RESULTS = 5000

_RESOLVER_KINDS = {
    *KCISA_KINDS.values(),
    *KTO_KINDS.values(),
    *(source.kind for source in MOIS_SOURCES.values()),
    "etc",
}
_DECLARED_KINDS = {kind.value for kind in PLACE_KINDS}
if _DECLARED_KINDS != _RESOLVER_KINDS:
    missing = sorted(_RESOLVER_KINDS - _DECLARED_KINDS)
    retired = sorted(_DECLARED_KINDS - _RESOLVER_KINDS)
    raise RuntimeError(
        "PlaceKind and resolver mappings differ: "
        f"missing={missing}, without_resolver={retired}"
    )


class PlaceSearchConditions(BaseModel):
    """사용자가 명시한 대조 조건. 장소를 제거하거나 순서를 바꾸지 않는다."""

    dog_id: str | None = Field(None, min_length=1, max_length=128)
    dog_size: SizeClass | None = None

    @model_validator(mode="after")
    def require_a_dog_subject(self) -> Self:
        if self.dog_id is None and self.dog_size is None:
            raise ValueError("conditions require dog_id or dog_size")
        return self


class AppliedPlaceSearchConditions(BaseModel):
    """실제 평가에 사용한 조건. 프로필을 못 읽으면 dog_size는 미상으로 남는다."""

    dog_id: str | None = None
    dog_size: SizeClass | None = None


class PlaceSearchRequest(BaseModel):
    lat: float = Field(ge=32, le=40)
    lng: float = Field(ge=123, le=133)
    radius_m: int = Field(3000, ge=100, le=20000)
    kinds: list[PlaceKind] = Field(min_length=1, max_length=MAX_KINDS_PER_REQUEST)
    # 지도는 반경 안 후보를 가능한 한 보되 서버 상한은 명시한다. 잘렸는지는 group이 말한다.
    limit_per_kind: int | None = Field(None, ge=1, le=MAX_RESULTS)
    conditions: PlaceSearchConditions | None = None

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

    @model_validator(mode="after")
    def stay_inside_request_budget(self) -> Self:
        if (
            self.limit_per_kind is not None
            and self.limit_per_kind * len(self.kinds) > MAX_TOTAL_RESULTS
        ):
            raise ValueError(
                f"limit_per_kind across all kinds must not exceed {MAX_TOTAL_RESULTS} results"
            )
        return self

    @property
    def effective_limit_per_kind(self) -> int:
        if self.limit_per_kind is not None:
            return self.limit_per_kind
        return min(MAX_RESULTS, MAX_TOTAL_RESULTS // len(self.kinds))
class PlaceSort(BaseModel):
    type: Literal["distance"] = "distance"
    basis: tuple[Literal["distance_m"], ...] = ("distance_m",)


class PlaceEvaluations(BaseModel):
    dog_access: DogAccessEvaluation | None = Field(
        None, exclude_if=lambda value: value is None,
    )


class PlaceSearchHit(BaseModel):
    place: PlaceResult
    evaluations: PlaceEvaluations = Field(default_factory=PlaceEvaluations)


class PlaceSearchGroup(BaseModel):
    kind: PlaceKind
    sort: PlaceSort = Field(default_factory=PlaceSort)
    limit: int = Field(ge=1)
    truncated: bool = False
    results: list[PlaceSearchHit]


class PlaceSearchResponse(BaseModel):
    conditions: AppliedPlaceSearchConditions | None = Field(
        None, exclude_if=lambda value: value is None,
    )
    groups: list[PlaceSearchGroup]


def _distance_key(result: PlaceResult) -> tuple[int, str, str]:
    return result.distance_m, result.key.source, result.key.ref


def _hit(result: PlaceResult, dog_size: SizeClass | None) -> PlaceSearchHit:
    dog_access = None
    if dog_size is not None and result.match.kind not in MEDICAL_KINDS:
        dog_access = evaluate_dog_access(result.facts.pet_access, dog_size)
    return PlaceSearchHit(
        place=result,
        evaluations=PlaceEvaluations(dog_access=dog_access),
    )


async def _medical_group(
    db: AsyncSession,
    request: PlaceSearchRequest,
    kind: PlaceKind,
    limit: int,
    dog_size: SizeClass | None,
) -> PlaceSearchGroup:
    rows = await resolve_medical_places(
        db,
        lat=request.lat,
        lng=request.lng,
        radius_m=request.radius_m,
        judge_at=SystemClock().now(),
        kind=kind.value,
        limit=limit + 1,
    )
    truncated = len(rows) > limit
    places = sorted((medical_place_result(row) for row in rows), key=_distance_key)[:limit]
    results = [_hit(place, dog_size) for place in places]
    return PlaceSearchGroup(kind=kind, limit=limit, truncated=truncated, results=results)


async def _facility_group(
    db: AsyncSession,
    request: PlaceSearchRequest,
    kind: PlaceKind,
    limit: int,
    dog_size: SizeClass | None,
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
        require_canonical_identity=True,
    )
    places = sorted(
        (facility_place_result(row) for row in resolved.results), key=_distance_key,
    )
    results = [_hit(place, dog_size) for place in places]
    return PlaceSearchGroup(
        kind=kind,
        limit=limit,
        truncated=resolved.truncated,
        results=results,
    )


async def _resolve_conditions(
    conditions: PlaceSearchConditions | None,
) -> AppliedPlaceSearchConditions | None:
    if conditions is None:
        return None
    dog_size = conditions.dog_size
    if dog_size is None and conditions.dog_id is not None:
        profile = await profile_source().get(conditions.dog_id)
        if profile is not None:
            dog_size = profile.size_class
    return AppliedPlaceSearchConditions(dog_id=conditions.dog_id, dog_size=dog_size)


async def search_place_groups(
    db: AsyncSession,
    request: PlaceSearchRequest,
) -> PlaceSearchResponse:
    """요청 kind 순서를 보존하고, 서로 다른 kind 사이에는 순위를 만들지 않는다."""
    limit = request.effective_limit_per_kind
    conditions = await _resolve_conditions(request.conditions)
    dog_size = conditions.dog_size if conditions is not None else None
    groups: list[PlaceSearchGroup] = []
    for kind in request.kinds:
        if kind in MEDICAL_KINDS:
            group = await _medical_group(db, request, kind, limit, dog_size)
        else:
            group = await _facility_group(db, request, kind, limit, dog_size)
        groups.append(group)
    return PlaceSearchResponse(conditions=conditions, groups=groups)
