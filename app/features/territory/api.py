"""Spatial Diary 읽기 표면: Capsule field, Episode Pin, Memory Place. #76·#77·#78."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.spatial_diary.access import (
    SpatialDiaryPrincipal,
    get_spatial_diary_principal,
    require_dog_access,
)
from app.features.spatial_diary.contract import (
    AttestedClaim,
    EpisodePin,
    MemoryPlace,
    MemoryPlaceBiography,
    MemoryPlaceBiographySpec,
    MemoryPlaceMembership,
    PrecipitationBiographyComparison,
    ReviewDisposition,
    SpatialDiaryViewReceipt,
    SpatialDiaryViewSpec,
    SpatialFieldMetric,
)
from app.features.spatial_diary.snapshot import (
    SpatialDiaryTransactionError,
    ensure_repeatable_read_snapshot,
)
from app.features.territory.memory_place import (
    MemoryPlaceConflictError,
    MemoryPlaceIntegrityError,
    MemoryPlaceNotFoundError,
    MemoryPlaceWithMemberships,
    compare_memory_place_precipitation,
    get_memory_place,
    list_memory_place_memberships,
    list_memory_places,
    memory_place_dog_id,
    put_memory_place,
    put_memory_place_membership,
    query_memory_place_biography,
)
from app.features.territory.spatial_diary import (
    IncompleteCapsuleError,
    MixedPaintGenerationError,
    SpatialDiaryViewResult,
    SpatialDiaryViewTooLargeError,
    UnsupportedSpatialDiaryViewError,
    query_spatial_diary_view,
)

router = APIRouter(prefix="/spatial-diary", tags=["spatial-diary"])
ResourceId = Annotated[str, Path(min_length=1, max_length=128)]

_MEMORY_PLACE_ERRORS = (
    MemoryPlaceNotFoundError,
    MemoryPlaceConflictError,
    MemoryPlaceIntegrityError,
    SpatialDiaryTransactionError,
    IncompleteCapsuleError,
    MixedPaintGenerationError,
    SpatialDiaryViewTooLargeError,
    UnsupportedSpatialDiaryViewError,
)


class ProjectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paint_version: int
    grid_version: str
    radius_u: float
    profile_name: str
    profile_fp: str
    sample_step_m: float
    paint_fp: str


class FieldCellOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    q: int
    r: int
    value: float
    numerator: float


class SpatialFieldOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: SpatialFieldMetric
    unit: str
    normalization: str
    denominator: float
    cells: tuple[FieldCellOut, ...]


class PinEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pin: EpisodePin
    review_disposition: ReviewDisposition
    claims: tuple[AttestedClaim, ...]


class SpatialDiaryViewOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    spec: SpatialDiaryViewSpec
    projection: ProjectionOut
    field: SpatialFieldOut
    pins: tuple[PinEntryOut, ...]
    receipt: SpatialDiaryViewReceipt


class PutMemoryPlaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dog_id: str = Field(min_length=1, max_length=128)
    seed_pin_ids: tuple[str, ...] = Field(min_length=2, max_length=100)
    label: str | None = Field(default=None, min_length=1, max_length=80)


class MemoryPlaceWithMembershipsOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    place: MemoryPlace
    memberships: tuple[MemoryPlaceMembership, ...]


class MemoryPlaceListOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dog_id: str
    places: tuple[MemoryPlace, ...]


def _raise_memory_place_http(exc: Exception) -> NoReturn:
    if isinstance(exc, MemoryPlaceNotFoundError):
        raise HTTPException(404, "spatial diary resource not found") from exc
    if isinstance(exc, MemoryPlaceConflictError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, MemoryPlaceIntegrityError):
        raise HTTPException(500, "sealed spatial diary evidence is incomplete") from exc
    if isinstance(exc, UnsupportedSpatialDiaryViewError):
        raise HTTPException(422, str(exc)) from exc
    if isinstance(exc, MixedPaintGenerationError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, SpatialDiaryViewTooLargeError):
        raise HTTPException(413, str(exc)) from exc
    if isinstance(exc, IncompleteCapsuleError):
        raise HTTPException(500, "sealed capsule is incomplete") from exc
    if isinstance(exc, SpatialDiaryTransactionError):
        raise HTTPException(500, "spatial diary snapshot could not be opened") from exc
    raise exc


async def _authorize_memory_place(
    db: AsyncSession,
    principal: SpatialDiaryPrincipal,
    place_id: ResourceId,
) -> None:
    try:
        await ensure_repeatable_read_snapshot(db)
        dog_id = await memory_place_dog_id(db, place_id)
    except (MemoryPlaceNotFoundError, SpatialDiaryTransactionError) as exc:
        _raise_memory_place_http(exc)
    require_dog_access(principal, dog_id)


def view_out(result: SpatialDiaryViewResult) -> SpatialDiaryViewOut:
    field = result.field
    if not isinstance(field.denominator, (float, int)):
        raise TypeError("SpatialDiaryView v0 field must have one shared denominator")
    projection = field.spec.projection
    return SpatialDiaryViewOut(
        spec=result.spec,
        projection=ProjectionOut(
            paint_version=projection.paint_version,
            grid_version=projection.grid_version,
            radius_u=projection.radius_u,
            profile_name=projection.brush,
            profile_fp=projection.profile_fp,
            sample_step_m=projection.sample_step_m,
            paint_fp=projection.paint_fp,
        ),
        field=SpatialFieldOut(
            metric=field.metric,
            unit=field.unit,
            normalization=field.normalization,
            denominator=float(field.denominator),
            cells=tuple(
                FieldCellOut(
                    q=q,
                    r=r,
                    value=value,
                    numerator=field.numerators[(q, r)],
                )
                for (q, r), value in sorted(field.values.items())
            ),
        ),
        pins=tuple(
            PinEntryOut(
                pin=entry.pin,
                review_disposition=entry.attestation.review_disposition,
                claims=entry.attestation.claims,
            )
            for entry in result.pins
        ),
        receipt=result.receipt,
    )


@router.post("/views/query", response_model=SpatialDiaryViewOut)
async def query_view(
    body: SpatialDiaryViewSpec,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> SpatialDiaryViewOut:
    require_dog_access(principal, body.walk_selector.dog_id)
    try:
        return view_out(await query_spatial_diary_view(db, body))
    except UnsupportedSpatialDiaryViewError as exc:
        raise HTTPException(422, str(exc)) from exc
    except MixedPaintGenerationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SpatialDiaryViewTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except IncompleteCapsuleError as exc:
        raise HTTPException(500, "sealed capsule is incomplete") from exc
    except SpatialDiaryTransactionError as exc:
        raise HTTPException(500, "spatial diary snapshot could not be opened") from exc


@router.put(
    "/memory-places/{place_id}",
    response_model=MemoryPlaceWithMembershipsOut,
)
async def put_place(
    place_id: ResourceId,
    body: PutMemoryPlaceIn,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> MemoryPlaceWithMembershipsOut:
    require_dog_access(principal, body.dog_id)
    try:
        result: MemoryPlaceWithMemberships = await put_memory_place(
            db,
            place_id=place_id,
            dog_id=body.dog_id,
            seed_pin_ids=body.seed_pin_ids,
            label=body.label,
        )
        await db.commit()
        return MemoryPlaceWithMembershipsOut(
            place=result.place,
            memberships=result.memberships,
        )
    except _MEMORY_PLACE_ERRORS as exc:
        _raise_memory_place_http(exc)


@router.get(
    "/dogs/{dog_id}/memory-places",
    response_model=MemoryPlaceListOut,
)
async def read_dog_places(
    dog_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> MemoryPlaceListOut:
    require_dog_access(principal, dog_id)
    try:
        await ensure_repeatable_read_snapshot(db)
        return MemoryPlaceListOut(
            dog_id=dog_id,
            places=await list_memory_places(db, dog_id),
        )
    except _MEMORY_PLACE_ERRORS as exc:
        _raise_memory_place_http(exc)


@router.get(
    "/memory-places/{place_id}",
    response_model=MemoryPlaceWithMembershipsOut,
)
async def read_place(
    place_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> MemoryPlaceWithMembershipsOut:
    await _authorize_memory_place(db, principal, place_id)
    place = await get_memory_place(db, place_id)
    if place is None:
        raise HTTPException(404, "spatial diary resource not found")
    return MemoryPlaceWithMembershipsOut(
        place=place,
        memberships=await list_memory_place_memberships(db, place_id),
    )


@router.put(
    "/memory-places/{place_id}/memberships/{pin_id}",
    response_model=MemoryPlaceMembership,
)
async def put_place_membership(
    place_id: ResourceId,
    pin_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> MemoryPlaceMembership:
    await _authorize_memory_place(db, principal, place_id)
    try:
        membership = await put_memory_place_membership(
            db,
            place_id=place_id,
            pin_id=pin_id,
        )
        await db.commit()
        return membership
    except _MEMORY_PLACE_ERRORS as exc:
        _raise_memory_place_http(exc)


@router.post(
    "/memory-places/{place_id}/biography/query",
    response_model=MemoryPlaceBiography,
)
async def query_place_biography(
    place_id: ResourceId,
    body: MemoryPlaceBiographySpec,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> MemoryPlaceBiography:
    require_dog_access(principal, body.walk_selector.dog_id)
    try:
        return await query_memory_place_biography(db, place_id, body)
    except _MEMORY_PLACE_ERRORS as exc:
        _raise_memory_place_http(exc)


@router.post(
    "/memory-places/{place_id}/comparisons/precipitation/query",
    response_model=PrecipitationBiographyComparison,
)
async def compare_place_precipitation(
    place_id: ResourceId,
    body: MemoryPlaceBiographySpec,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> PrecipitationBiographyComparison:
    require_dog_access(principal, body.walk_selector.dog_id)
    try:
        return await compare_memory_place_precipitation(db, place_id, body)
    except _MEMORY_PLACE_ERRORS as exc:
        _raise_memory_place_http(exc)
