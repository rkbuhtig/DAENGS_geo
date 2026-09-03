"""점령지 적재를 눈으로 검수하는 dev 전용 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.territory.game.sites import inspect_bbox

router = APIRouter(prefix="/dev/territory-sites", tags=["dev-territory-sites"])

MAX_LIMIT = 3000


class TerritorySiteSearchParams(BaseModel):
    south: float = Field(ge=32, le=40)
    west: float = Field(ge=123, le=133)
    north: float = Field(ge=32, le=40)
    east: float = Field(ge=123, le=133)
    kind: str | None = None
    limit: int = Field(1500, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> "TerritorySiteSearchParams":
        if self.south >= self.north or self.west >= self.east:
            raise ValueError("south/west must be smaller than north/east")
        return self


class TerritorySiteInspectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site_id: str
    source: str
    kind: str
    lat: float
    lng: float
    instt: str | None
    as_of: str | None


class TerritorySiteSearchOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int
    truncated: bool
    sites: tuple[TerritorySiteInspectionOut, ...]


@router.get("/search", response_model=TerritorySiteSearchOut)
async def search_territory_sites(
    params: Annotated[TerritorySiteSearchParams, Query()],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> TerritorySiteSearchOut:
    sites, truncated = await inspect_bbox(
        db,
        south=params.south,
        west=params.west,
        north=params.north,
        east=params.east,
        kind=params.kind,
        limit=params.limit,
    )
    return TerritorySiteSearchOut(
        count=len(sites),
        truncated=truncated,
        sites=tuple(
            TerritorySiteInspectionOut.model_validate(site, from_attributes=True) for site in sites
        ),
    )
