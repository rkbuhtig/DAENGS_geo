"""Spatial Diary의 첫 읽기 표면. v0는 Capsule 배경 field만 반환한다. Decision: #76."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.spatial_diary.contract import (
    SpatialDiaryViewReceipt,
    SpatialDiaryViewSpec,
    SpatialFieldMetric,
)
from app.features.territory.spatial_diary import (
    IncompleteCapsuleError,
    MixedPaintGenerationError,
    SpatialDiaryTransactionError,
    SpatialDiaryViewResult,
    SpatialDiaryViewTooLargeError,
    UnsupportedSpatialDiaryViewError,
    query_spatial_diary_view,
)

router = APIRouter(prefix="/spatial-diary", tags=["spatial-diary"])


@dataclass(frozen=True)
class SpatialDiaryPrincipal:
    """인증 계층이 주입하는 최소 권한 문맥. Profile source를 인증에 재사용하지 않는다."""

    owner_id: str
    dog_ids: frozenset[str]


def get_spatial_diary_principal() -> SpatialDiaryPrincipal:
    """앱 조립부가 실제 인증 dependency로 override하기 전에는 공개 조회를 닫는다."""

    raise HTTPException(503, "spatial diary authorization is not configured")


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


class SpatialDiaryViewOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    spec: SpatialDiaryViewSpec
    projection: ProjectionOut
    field: SpatialFieldOut
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
        receipt=result.receipt,
    )


@router.post("/views/query", response_model=SpatialDiaryViewOut)
async def query_view(
    body: SpatialDiaryViewSpec,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> SpatialDiaryViewOut:
    if body.walk_selector.dog_id not in principal.dog_ids:
        raise HTTPException(404, "spatial diary view not found")
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
