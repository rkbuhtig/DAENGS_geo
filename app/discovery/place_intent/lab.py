"""Gemini intent → planner → 실제 Place 검색을 대조하는 dev-only vertical slice."""

from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.discovery.place_intent.gemini import (
    GeminiIntentProposerResponseError,
    configured_gemini_intent_proposer,
)
from app.discovery.place_intent.service import (
    PlaceIntentSuggestionService,
    PlaceIntentSuggestionTrace,
)
from app.place.planning.contract import (
    PlaceSearchConditions,
    PlaceSpatialConstraint,
    PlanningModel,
)
from app.place.planning.preview import PlaceSearchPlanPreview
from app.place.search import PlaceSearchResponse, search_place_plan
from app.place.search_preview import preview_search_plan
from app.usage.http import usage_http_exception
from app.usage.models import UsageDenied

router = APIRouter(tags=["place-intent-lab"])
_SURFACE = Path(__file__).resolve().parents[2] / "static" / "place_intent_lab.html"


class PlaceIntentLabRequest(PlanningModel):
    utterance: str = Field(min_length=1, max_length=1000)
    lat: float = Field(ge=32, le=40)
    lng: float = Field(ge=123, le=133)
    radius_m: int = Field(3000, ge=100, le=20000)
    limit_per_kind: int = Field(20, ge=1, le=100)
    conditions: PlaceSearchConditions | None = None


class CandidateExecution(PlanningModel):
    candidate_key: str
    preview: PlaceSearchPlanPreview
    search: PlaceSearchResponse


class PlaceIntentLabResponse(PlanningModel):
    model: str
    trace: PlaceIntentSuggestionTrace
    executions: tuple[CandidateExecution, ...]


def _suggestion_service() -> PlaceIntentSuggestionService:
    return PlaceIntentSuggestionService(configured_gemini_intent_proposer())


@router.get("/place-intent-lab", include_in_schema=False)
async def place_intent_lab() -> FileResponse:
    return FileResponse(
        _SURFACE,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/dev/place-intent/search", response_model=PlaceIntentLabResponse)
async def search_place_intent(
    request: PlaceIntentLabRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> PlaceIntentLabResponse:
    try:
        service = _suggestion_service()
        trace = await service.inspect(
            request.utterance,
            spatial=PlaceSpatialConstraint(
                lat=request.lat,
                lng=request.lng,
                radius_m=request.radius_m,
            ),
            limit_per_kind=request.limit_per_kind,
            conditions=request.conditions,
        )
    except UsageDenied as exc:
        raise usage_http_exception(exc) from exc
    except RuntimeError as exc:
        if isinstance(exc, GeminiIntentProposerResponseError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini intent proposal failed",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini intent proposer is not configured",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini API request failed",
        ) from exc

    executions = []
    for candidate in trace.outcome.suggestions:
        plan = candidate.result.plan
        if plan is None:
            continue
        executions.append(
            CandidateExecution(
                candidate_key=candidate.candidate_key,
                preview=await preview_search_plan(db, plan),
                search=await search_place_plan(db, plan),
            )
        )
    return PlaceIntentLabResponse(
        model=settings.gemini_model,
        trace=trace,
        executions=tuple(executions),
    )
