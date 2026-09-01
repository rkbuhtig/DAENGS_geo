"""Gemini intent → planner → 실제 Place 검색을 대조하는 dev-only vertical slice."""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import Field, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.discovery.place_intent.confirmation import ConfirmedSearchLens, confirm_search_lens
from app.discovery.place_intent.gemini import (
    GeminiIntentProposerResponseError,
    configured_gemini_intent_proposer,
)
from app.discovery.place_intent.lenses import TargetSearchLens
from app.discovery.place_intent.observability import (
    AttemptStatus,
    ObservedSearchAttempt,
    SearchAttemptRecord,
    SearchEventType,
    SearchResponseMode,
    list_attempts,
    safely_record_attempt,
    safely_record_event,
)
from app.discovery.place_intent.refinement import resolve_search_facet
from app.discovery.place_intent.service import (
    PlaceIntentSuggestionService,
    PlaceIntentSuggestionTrace,
)
from app.discovery.place_intent.suggestions import SuggestionResolution
from app.place.planning.contract import (
    PlaceSearchConditions,
    PlaceSpatialConstraint,
    PlanningModel,
)
from app.place.planning.intents import PlannerStatus
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
    previous_search_id: UUID | None = None
    interaction_token: str | None = Field(None, min_length=20, max_length=200)

    @model_validator(mode="after")
    def revision_credentials_are_paired(self) -> Self:
        if (self.previous_search_id is None) != (self.interaction_token is None):
            raise ValueError("previous_search_id and interaction_token must be supplied together")
        return self


class CandidateExecution(PlanningModel):
    lens_id: str
    confirmation_token: str = Field(min_length=20, max_length=200)
    preview: PlaceSearchPlanPreview
    search: PlaceSearchResponse


class PlaceIntentLabResponse(PlanningModel):
    search_id: UUID
    interaction_token: str = Field(min_length=20, max_length=200)
    model: str
    trace: PlaceIntentSuggestionTrace
    executions: tuple[CandidateExecution, ...]


class PlaceIntentConfirmationRequest(PlanningModel):
    lens_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9_.:-]+$")
    confirmation_token: str = Field(min_length=20, max_length=200)


class PlaceIntentConfirmationResponse(PlanningModel):
    confirmation: ConfirmedSearchLens
    preview: PlaceSearchPlanPreview
    search: PlaceSearchResponse


class PlaceIntentRefinementRequest(PlanningModel):
    search_id: UUID
    interaction_token: str = Field(min_length=20, max_length=200)
    signal_lens_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9_.:-]+$")
    option_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.:-]+$")


class PlaceIntentInteractionRequest(PlanningModel):
    search_id: UUID
    interaction_token: str = Field(min_length=20, max_length=200)
    action: Literal["lens_selected", "search_reset"]
    lens_id: str | None = Field(None, min_length=1, max_length=160, pattern=r"^[a-z0-9_.:-]+$")

    @model_validator(mode="after")
    def lens_matches_action(self) -> Self:
        if self.action == "lens_selected" and self.lens_id is None:
            raise ValueError("lens_selected requires lens_id")
        if self.action == "search_reset" and self.lens_id is not None:
            raise ValueError("search_reset cannot carry lens_id")
        return self


class PlaceIntentInteractionResponse(PlanningModel):
    recorded: bool


class PlaceIntentObservationResponse(PlanningModel):
    attempts: tuple[ObservedSearchAttempt, ...]


@dataclass(frozen=True)
class _PendingConfirmation:
    lens: TargetSearchLens
    search_id: UUID
    expires_at: float


class _ConfirmationStore:
    """Dev lab의 명시적 확인 요청을 서버가 발급한 lens에 한 번만 연결한다."""

    def __init__(
        self,
        *,
        ttl_s: float = 15 * 60,
        max_entries: int = 256,
        clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] = lambda: token_urlsafe(32),
    ) -> None:
        if ttl_s <= 0 or max_entries <= 0:
            raise ValueError("confirmation store bounds must be positive")
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._token_factory = token_factory
        self._items: OrderedDict[str, _PendingConfirmation] = OrderedDict()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        expired = [token for token, item in self._items.items() if item.expires_at <= now]
        for token in expired:
            self._items.pop(token, None)

    def issue(self, lens: TargetSearchLens, search_id: UUID) -> str:
        now = self._clock()
        with self._lock:
            self._prune(now)
            while len(self._items) >= self._max_entries:
                self._items.popitem(last=False)
            token = self._token_factory()
            while token in self._items:
                token = self._token_factory()
            self._items[token] = _PendingConfirmation(
                lens=lens,
                search_id=search_id,
                expires_at=now + self._ttl_s,
            )
            return token

    def consume(self, token: str, lens_id: str) -> _PendingConfirmation:
        now = self._clock()
        with self._lock:
            self._prune(now)
            pending = self._items.get(token)
            if pending is None:
                raise KeyError("confirmation token is missing or expired")
            if pending.lens.lens_id != lens_id:
                raise ValueError("confirmation token does not match the selected lens")
            self._items.pop(token)
            return pending


_confirmation_store = _ConfirmationStore()


@dataclass(frozen=True)
class _PendingInteraction:
    search_id: UUID
    utterance: str
    trace: PlaceIntentSuggestionTrace
    preview_per_lens: int
    lat: float
    lng: float
    radius_m: int
    expires_at: float


class _InteractionStore:
    """브라우저 행동을 서버가 실제로 제안한 검색 시도에만 연결한다."""

    def __init__(
        self,
        *,
        ttl_s: float = 15 * 60,
        max_entries: int = 256,
        clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] = lambda: token_urlsafe(32),
    ) -> None:
        if ttl_s <= 0 or max_entries <= 0:
            raise ValueError("interaction store bounds must be positive")
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._token_factory = token_factory
        self._items: OrderedDict[str, _PendingInteraction] = OrderedDict()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        expired = [token for token, item in self._items.items() if item.expires_at <= now]
        for token in expired:
            self._items.pop(token, None)

    def issue(
        self,
        *,
        search_id: UUID,
        utterance: str,
        trace: PlaceIntentSuggestionTrace,
        preview_per_lens: int,
        lat: float,
        lng: float,
        radius_m: int,
    ) -> str:
        now = self._clock()
        with self._lock:
            self._prune(now)
            while len(self._items) >= self._max_entries:
                self._items.popitem(last=False)
            token = self._token_factory()
            while token in self._items:
                token = self._token_factory()
            self._items[token] = _PendingInteraction(
                search_id=search_id,
                utterance=utterance,
                trace=trace,
                preview_per_lens=preview_per_lens,
                lat=lat,
                lng=lng,
                radius_m=radius_m,
                expires_at=now + self._ttl_s,
            )
            return token

    def get(self, token: str, search_id: UUID) -> _PendingInteraction:
        now = self._clock()
        with self._lock:
            self._prune(now)
            pending = self._items.get(token)
            if pending is None:
                raise KeyError("interaction token is missing or expired")
            if pending.search_id != search_id:
                raise ValueError("interaction token does not match the search")
            self._items.move_to_end(token)
            return pending


_interaction_store = _InteractionStore()


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


def _result_count(execution: CandidateExecution) -> int:
    return sum(len(group.results) for group in execution.search.groups)


def _attempt_outcome(
    trace: PlaceIntentSuggestionTrace,
    executions: tuple[CandidateExecution, ...],
) -> tuple[AttemptStatus, str | None]:
    if trace.raw is None:
        code = trace.outcome.issues[0].code if trace.outcome.issues else "intent_invalid_output"
        return AttemptStatus.NEEDS_CLARIFICATION, code
    if not executions:
        lenses = trace.lenses.target_lenses if trace.lenses is not None else ()
        if any(item.availability.value == "needs_selection" for item in lenses):
            return AttemptStatus.NEEDS_CLARIFICATION, "facet_selection_required"
        return AttemptStatus.NEEDS_CLARIFICATION, "no_executable_lens"
    if not any(_result_count(item) for item in executions):
        initial_candidates = sum(item.preview.initial_candidates for item in executions)
        final_candidates = sum(
            item.preview.gates[-1].remaining
            if item.preview.gates
            else item.preview.initial_candidates
            for item in executions
        )
        if initial_candidates == 0:
            return AttemptStatus.NEEDS_CLARIFICATION, "spatial_candidates_empty"
        if final_candidates == 0:
            return AttemptStatus.NEEDS_CLARIFICATION, "gate_eliminated_all"
        return AttemptStatus.NEEDS_CLARIFICATION, "empty_result"
    return AttemptStatus.COMPLETED, None


def _response_mode(
    trace: PlaceIntentSuggestionTrace,
    attempt_status: AttemptStatus,
) -> SearchResponseMode:
    if attempt_status is not AttemptStatus.COMPLETED:
        if trace.outcome.status is PlannerStatus.UNSUPPORTED:
            return SearchResponseMode.UNSUPPORTED
        return SearchResponseMode.CLARIFICATION
    if trace.outcome.resolution is SuggestionResolution.EXPLORATORY:
        return SearchResponseMode.EXPLORATORY_RESULTS
    return SearchResponseMode.DIRECT_RESULTS


def _fallback_policy(trace: PlaceIntentSuggestionTrace) -> tuple[str, str] | None:
    lenses = trace.lenses.target_lenses if trace.lenses is not None else ()
    policies = {
        (candidate.basis_policy_id, candidate.basis_policy_version)
        for candidate in (lens.candidate for lens in lenses)
        if candidate.basis_policy_id is not None
        and candidate.basis_policy_version is not None
    }
    if not policies:
        return None
    if len(policies) != 1:
        raise ValueError("one search response cannot mix fallback policy versions")
    policy_id, version = next(iter(policies))
    return policy_id, version


def _attempt_snapshot(
    trace: PlaceIntentSuggestionTrace,
    executions: tuple[CandidateExecution, ...],
    *,
    response_mode: SearchResponseMode,
    failure_code: str | None,
    fallback_policy_id: str | None = None,
    fallback_policy_version: str | None = None,
) -> dict:
    execution_by_id = {item.lens_id: item for item in executions}
    lenses = trace.lenses.target_lenses if trace.lenses is not None else ()
    return {
        "proposer": {
            "disposition": trace.raw.disposition.value if trace.raw is not None else None,
            "reason": (
                trace.raw.reason.value
                if trace.raw is not None and trace.raw.reason is not None
                else None
            ),
        },
        "product_outcome": {
            "response_mode": response_mode.value,
            "failure_code": failure_code,
        },
        "fallback_policy": (
            {
                "policy_id": fallback_policy_id,
                "version": fallback_policy_version,
            }
            if fallback_policy_id is not None and fallback_policy_version is not None
            else None
        ),
        "planner_status": trace.outcome.status.value,
        "issues": [item.code for item in trace.outcome.issues],
        "lenses": [
            {
                "lens_id": lens.lens_id,
                "label": lens.display_label,
                "availability": lens.availability.value,
                "result_count": (
                    _result_count(execution_by_id[lens.lens_id])
                    if lens.lens_id in execution_by_id
                    else 0
                ),
                "gates": [
                    {
                        "capability_id": gate.capability_id.value,
                        "input": gate.input_candidates,
                        "remaining": gate.remaining,
                        "unknown": gate.unknown,
                    }
                    for gate in (
                        execution_by_id[lens.lens_id].preview.gates
                        if lens.lens_id in execution_by_id
                        else ()
                    )
                ],
            }
            for lens in lenses
        ],
    }


async def _execute_trace(
    db: AsyncSession,
    *,
    trace: PlaceIntentSuggestionTrace,
    search_id: UUID,
    preview_per_lens: int,
) -> tuple[CandidateExecution, ...]:
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
                confirmation_token=_confirmation_store.issue(lens, search_id),
                preview=await preview_search_plan(db, plan),
                search=_limit_search_preview(search, preview_per_lens),
            )
        )
    return tuple(executions)


async def _observe_trace(
    db: AsyncSession,
    *,
    search_id: UUID,
    previous_search_id: UUID | None,
    utterance: str,
    lat: float,
    lng: float,
    radius_m: int,
    trace: PlaceIntentSuggestionTrace,
    executions: tuple[CandidateExecution, ...],
) -> None:
    attempt_status, failure_code = _attempt_outcome(trace, executions)
    response_mode = _response_mode(trace, attempt_status)
    fallback_policy = _fallback_policy(trace)
    fallback_policy_id = fallback_policy[0] if fallback_policy is not None else None
    fallback_policy_version = fallback_policy[1] if fallback_policy is not None else None
    lenses = trace.lenses.target_lenses if trace.lenses is not None else ()
    recorded = await safely_record_attempt(
        db,
        SearchAttemptRecord(
            attempt_id=search_id,
            previous_attempt_id=previous_search_id,
            utterance=utterance,
            model=settings.gemini_model,
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            status=attempt_status,
            failure_code=failure_code,
            proposer_disposition=trace.raw.disposition if trace.raw is not None else None,
            proposer_reason=trace.raw.reason if trace.raw is not None else None,
            response_mode=response_mode,
            fallback_policy_id=fallback_policy_id,
            fallback_policy_version=fallback_policy_version,
            interpretation_count=len(trace.raw.interpretations) if trace.raw is not None else 0,
            target_lens_count=len(lenses),
            executable_lens_count=len(executions),
            result_count=sum(_result_count(item) for item in executions),
            snapshot=_attempt_snapshot(
                trace,
                executions,
                response_mode=response_mode,
                failure_code=failure_code,
                fallback_policy_id=fallback_policy_id,
                fallback_policy_version=fallback_policy_version,
            ),
        ),
    )
    if recorded:
        await safely_record_event(
            db,
            attempt_id=search_id,
            event_type=(
                SearchEventType.SEARCH_COMPLETED
                if attempt_status is AttemptStatus.COMPLETED
                else SearchEventType.SEARCH_FAILED
            ),
            details={
                "failure_code": failure_code,
                "response_mode": response_mode.value,
                "fallback_policy_id": fallback_policy_id,
                "fallback_policy_version": fallback_policy_version,
            },
        )


async def _observe_failed_attempt(
    db: AsyncSession,
    *,
    search_id: UUID,
    previous_search_id: UUID | None,
    source: PlaceIntentLabRequest | _PendingInteraction,
    failure_code: str,
) -> None:
    recorded = await safely_record_attempt(
        db,
        SearchAttemptRecord(
            attempt_id=search_id,
            previous_attempt_id=previous_search_id,
            utterance=source.utterance,
            model=settings.gemini_model,
            lat=source.lat,
            lng=source.lng,
            radius_m=source.radius_m,
            status=AttemptStatus.FAILED,
            failure_code=failure_code,
            response_mode=SearchResponseMode.PROVIDER_FAILURE,
            interpretation_count=0,
            target_lens_count=0,
            executable_lens_count=0,
            result_count=0,
            snapshot={
                "proposer": {"disposition": None, "reason": None},
                "product_outcome": {
                    "response_mode": SearchResponseMode.PROVIDER_FAILURE.value,
                    "failure_code": failure_code,
                },
                "fallback_policy": None,
            },
        ),
    )
    if recorded:
        await safely_record_event(
            db,
            attempt_id=search_id,
            event_type=SearchEventType.SEARCH_FAILED,
            details={
                "failure_code": failure_code,
                "response_mode": SearchResponseMode.PROVIDER_FAILURE.value,
            },
        )


def _issue_lab_response(
    *,
    search_id: UUID,
    utterance: str,
    trace: PlaceIntentSuggestionTrace,
    executions: tuple[CandidateExecution, ...],
    preview_per_lens: int,
    lat: float,
    lng: float,
    radius_m: int,
) -> PlaceIntentLabResponse:
    interaction_token = _interaction_store.issue(
        search_id=search_id,
        utterance=utterance,
        trace=trace,
        preview_per_lens=preview_per_lens,
        lat=lat,
        lng=lng,
        radius_m=radius_m,
    )
    return PlaceIntentLabResponse(
        search_id=search_id,
        interaction_token=interaction_token,
        model=settings.gemini_model,
        trace=trace,
        executions=executions,
    )


def _pending_interaction(token: str, search_id: UUID) -> _PendingInteraction:
    try:
        return _interaction_store.get(token, search_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="search interaction offer is missing or expired",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="interaction offer does not match the search",
        ) from exc


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
    search_id = uuid4()
    previous = None
    if request.previous_search_id is not None and request.interaction_token is not None:
        previous = _pending_interaction(request.interaction_token, request.previous_search_id)
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
        await _observe_failed_attempt(
            db,
            search_id=search_id,
            previous_search_id=previous.search_id if previous else None,
            source=request,
            failure_code="usage_denied",
        )
        raise usage_http_exception(exc) from exc
    except RuntimeError as exc:
        if isinstance(exc, GeminiIntentProposerResponseError):
            await _observe_failed_attempt(
                db,
                search_id=search_id,
                previous_search_id=previous.search_id if previous else None,
                source=request,
                failure_code="gemini_response_error",
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini intent proposal failed",
            ) from exc
        await _observe_failed_attempt(
            db,
            search_id=search_id,
            previous_search_id=previous.search_id if previous else None,
            source=request,
            failure_code="gemini_not_configured",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini intent proposer is not configured",
        ) from exc
    except httpx.HTTPError as exc:
        await _observe_failed_attempt(
            db,
            search_id=search_id,
            previous_search_id=previous.search_id if previous else None,
            source=request,
            failure_code="gemini_http_error",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini API request failed",
        ) from exc

    try:
        executions = await _execute_trace(
            db,
            trace=trace,
            search_id=search_id,
            preview_per_lens=request.preview_per_lens,
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        await _observe_failed_attempt(
            db,
            search_id=search_id,
            previous_search_id=previous.search_id if previous else None,
            source=request,
            failure_code="database_search_error",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="place search database request failed",
        ) from exc
    await _observe_trace(
        db,
        search_id=search_id,
        previous_search_id=previous.search_id if previous else None,
        utterance=request.utterance,
        lat=request.lat,
        lng=request.lng,
        radius_m=request.radius_m,
        trace=trace,
        executions=executions,
    )
    if previous is not None:
        await safely_record_event(
            db,
            attempt_id=previous.search_id,
            event_type=SearchEventType.SEARCH_REVISED,
            details={"next_search_id": str(search_id)},
        )
    return _issue_lab_response(
        search_id=search_id,
        utterance=request.utterance,
        trace=trace,
        executions=executions,
        preview_per_lens=request.preview_per_lens,
        lat=request.lat,
        lng=request.lng,
        radius_m=request.radius_m,
    )


@router.post("/dev/place-intent/refine", response_model=PlaceIntentLabResponse)
async def refine_place_intent(
    request: PlaceIntentRefinementRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> PlaceIntentLabResponse:
    pending = _pending_interaction(request.interaction_token, request.search_id)
    if pending.trace.lenses is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="search has no refinable lenses",
        )
    try:
        lenses = resolve_search_facet(
            pending.trace.lenses,
            signal_lens_id=request.signal_lens_id,
            option_id=request.option_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    search_id = uuid4()
    trace = pending.trace.model_copy(update={"lenses": lenses})
    try:
        executions = await _execute_trace(
            db,
            trace=trace,
            search_id=search_id,
            preview_per_lens=pending.preview_per_lens,
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        await _observe_failed_attempt(
            db,
            search_id=search_id,
            previous_search_id=pending.search_id,
            source=pending,
            failure_code="database_search_error",
        )
        await safely_record_event(
            db,
            attempt_id=pending.search_id,
            event_type=SearchEventType.FACET_SELECTED,
            lens_id=request.signal_lens_id,
            details={
                "option_id": request.option_id,
                "next_search_id": str(search_id),
                "execution_failed": True,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="place search database request failed",
        ) from exc
    await _observe_trace(
        db,
        search_id=search_id,
        previous_search_id=pending.search_id,
        utterance=pending.utterance,
        lat=pending.lat,
        lng=pending.lng,
        radius_m=pending.radius_m,
        trace=trace,
        executions=executions,
    )
    await safely_record_event(
        db,
        attempt_id=pending.search_id,
        event_type=SearchEventType.FACET_SELECTED,
        lens_id=request.signal_lens_id,
        details={"option_id": request.option_id, "next_search_id": str(search_id)},
    )
    return _issue_lab_response(
        search_id=search_id,
        utterance=pending.utterance,
        trace=trace,
        executions=executions,
        preview_per_lens=pending.preview_per_lens,
        lat=pending.lat,
        lng=pending.lng,
        radius_m=pending.radius_m,
    )


@router.post(
    "/dev/place-intent/interact",
    response_model=PlaceIntentInteractionResponse,
)
async def observe_place_intent_interaction(
    request: PlaceIntentInteractionRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> PlaceIntentInteractionResponse:
    pending = _pending_interaction(request.interaction_token, request.search_id)
    if request.action == "lens_selected":
        lens_ids = {
            item.lens_id
            for item in (
                pending.trace.lenses.target_lenses if pending.trace.lenses is not None else ()
            )
        }
        if request.lens_id not in lens_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="selected lens was not offered by this search",
            )
        event_type = SearchEventType.LENS_SELECTED
    else:
        event_type = SearchEventType.SEARCH_RESET
    recorded = await safely_record_event(
        db,
        attempt_id=pending.search_id,
        event_type=event_type,
        lens_id=request.lens_id,
    )
    return PlaceIntentInteractionResponse(recorded=recorded)


@router.get(
    "/dev/place-intent/observations",
    response_model=PlaceIntentObservationResponse,
)
async def place_intent_observations(
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    failures_only: bool = True,
) -> PlaceIntentObservationResponse:
    try:
        attempts = await list_attempts(db, limit=limit, failures_only=failures_only)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="place intent observation store is unavailable",
        ) from exc
    return PlaceIntentObservationResponse(attempts=attempts)


@router.post(
    "/dev/place-intent/confirm",
    response_model=PlaceIntentConfirmationResponse,
)
async def confirm_place_intent(
    request: PlaceIntentConfirmationRequest,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> PlaceIntentConfirmationResponse:
    try:
        pending = _confirmation_store.consume(request.confirmation_token, request.lens_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="confirmation offer is missing or expired",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="confirmation offer does not match the selected lens",
        ) from exc

    confirmation = confirm_search_lens(pending.lens)
    plan = confirmation.result.plan
    if plan is None:  # ConfirmedSearchLens가 강제하지만 type narrowing을 명시한다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="confirmed lens has no executable plan",
        )
    search = await search_place_plan(db, plan)
    await safely_record_event(
        db,
        attempt_id=pending.search_id,
        event_type=SearchEventType.LENS_CONFIRMED,
        lens_id=request.lens_id,
        details={
            "result_count": sum(len(group.results) for group in search.groups),
            "locked_capabilities": [
                gate.capability_id.value for gate in plan.gates if gate.locked
            ],
        },
    )
    return PlaceIntentConfirmationResponse(
        confirmation=confirmation,
        preview=await preview_search_plan(db, plan),
        search=_limit_search_preview(search, plan.limit_per_kind),
    )
