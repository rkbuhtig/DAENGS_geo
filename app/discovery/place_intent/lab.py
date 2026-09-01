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
    preview_per_lens: int = Field(3, ge=2, le=4)
    conditions: PlaceSearchConditions | None = None


class CandidateExecution(PlanningModel):
    lens_id: str
    preview: PlaceSearchPlanPreview
    search: PlaceSearchResponse


class PlaceIntentLabResponse(PlanningModel):
    model: str
    trace: PlaceIntentSuggestionTrace
    executions: tuple[CandidateExecution, ...]


def _suggestion_service() -> PlaceIntentSuggestionService:
    return PlaceIntentSuggestionService(configured_gemini_intent_proposer())


def _limit_search_preview(
    search: PlaceSearchResponse,
    limit: int,
) -> PlaceSearchResponse:
    """그룹 순서를 유지한 round-robin으로 lens 전체 미리보기를 작게 제한한다."""

    selected = [[] for _ in search.groups]
    remaining = limit
    offset = 0
    while remaining:
        added = False
        for index, group in enumerate(search.groups):
            if offset >= len(group.results):
                continue
            selected[index].append(group.results[offset])
            remaining -= 1
            added = True
            if not remaining:
                break
        if not added:
            break
        offset += 1
    return search.model_copy(
        update={
            "groups": [
                group.model_copy(
                    update={
                        "results": selected[index],
                        "truncated": group.truncated or len(selected[index]) < len(group.results),
                    }
                )
                for index, group in enumerate(search.groups)
            ]
        }
    )


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
            limit_per_kind=request.preview_per_lens,
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
    executable_lenses = trace.lenses.executable_targets if trace.lenses is not None else ()
    for lens in executable_lenses:
        plan = lens.candidate.result.plan
        if plan is None:
            continue
        search = await search_place_plan(db, plan)
        executions.append(
            CandidateExecution(
                lens_id=lens.lens_id,
                preview=await preview_search_plan(db, plan),
                search=_limit_search_preview(search, request.preview_per_lens),
            )
        )
    return PlaceIntentLabResponse(
        model=settings.gemini_model,
        trace=trace,
        executions=tuple(executions),
    )
