"""Spatial Diary 읽기 표면: Capsule field와 사용자 Episode Pin overlay. #76·#77."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
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
    ReviewDisposition,
    SpatialDiaryViewReceipt,
    SpatialDiaryViewSpec,
    SpatialFieldMetric,
)
from app.features.spatial_diary.snapshot import SpatialDiaryTransactionError
from app.features.territory.spatial_diary import (
    IncompleteCapsuleError,
    MixedPaintGenerationError,
    SpatialDiaryViewResult,
    SpatialDiaryViewTooLargeError,
    UnsupportedSpatialDiaryViewError,
    query_spatial_diary_view,
)

router = APIRouter(prefix="/spatial-diary", tags=["spatial-diary"])


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
