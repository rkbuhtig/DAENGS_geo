"""Spatial Diary PR4: derived Candidate를 사용자 증언과 안정 Pin으로 승격한다."""

from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.spatial_diary.access import (
    SpatialDiaryPrincipal,
    get_spatial_diary_principal,
    require_dog_access,
)
from app.features.spatial_diary.contract import (
    AttestedClaim,
    ClaimAllowance,
    EpisodeCandidate,
    EpisodeOfferSnapshot,
    EpisodePin,
    MemoryAction,
    OfferInteraction,
    OfferInteractionKind,
    ReviewDisposition,
    WalkAttestation,
    WalkJournalProjection,
)
from app.features.spatial_diary.episode import (
    CANDIDATE_POLICY_VERSION,
    AttestationResult,
    OfferReviewState,
    SpatialDiaryEpisodeConflictError,
    SpatialDiaryEpisodeIntegrityError,
    SpatialDiaryEpisodeNotFoundError,
    attest_episode_offer,
    capsule_dog_id,
    get_episode_offer,
    list_episode_candidates,
    list_offer_review_states,
    offer_dog_id,
    put_episode_offer,
    put_offer_interaction,
)
from app.features.spatial_diary.journal import query_walk_journal
from app.features.spatial_diary.snapshot import (
    SpatialDiaryTransactionError,
    ensure_repeatable_read_snapshot,
)

router = APIRouter(prefix="/spatial-diary", tags=["spatial-diary"])
ResourceId = Annotated[str, Path(min_length=1, max_length=128)]

_EPISODE_ERRORS = (
    SpatialDiaryEpisodeNotFoundError,
    SpatialDiaryEpisodeConflictError,
    SpatialDiaryEpisodeIntegrityError,
    SpatialDiaryTransactionError,
)


class CandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: EpisodeCandidate
    claim_allowance: ClaimAllowance


class CandidateListOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    candidates: tuple[CandidateOut, ...]


class PutOfferIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1, max_length=128)
    source_observation_id: str = Field(min_length=1, max_length=128)
    candidate_policy_version: Literal[CANDIDATE_POLICY_VERSION] = CANDIDATE_POLICY_VERSION


class PutInteractionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[OfferInteractionKind.VIEWED, OfferInteractionKind.DISMISSED]


class PutAttestationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_disposition: ReviewDisposition
    claims: tuple[AttestedClaim, ...] = Field(default=(), max_length=16)
    memory_action: MemoryAction
    pin_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def pin_matches_memory_action(self) -> "PutAttestationIn":
        if (self.memory_action is MemoryAction.SAVE) != (self.pin_id is not None):
            raise ValueError("save requires pin_id and dismiss forbids pin_id")
        if self.review_disposition is ReviewDisposition.CONFIRMED and not self.claims:
            raise ValueError("confirmed attestation requires at least one claim")
        if self.review_disposition is ReviewDisposition.REJECTED and (
            self.claims or self.memory_action is MemoryAction.SAVE
        ):
            raise ValueError("rejected attestation cannot have claims or a saved pin")
        claim_keys = [
            (claim.subject_role, claim.meaning_code, claim.vocabulary_version)
            for claim in self.claims
        ]
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("attestation claims must be unique")
        return self


class AttestationOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attestation: WalkAttestation
    pin: EpisodePin | None


class OfferReviewStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    offer: EpisodeOfferSnapshot
    interactions: tuple[OfferInteraction, ...]
    attestation: WalkAttestation | None
    pin: EpisodePin | None


class OfferReviewListOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    offers: tuple[OfferReviewStateOut, ...]


def _raise_episode_http(exc: Exception) -> NoReturn:
    if isinstance(exc, SpatialDiaryEpisodeNotFoundError):
        raise HTTPException(404, "spatial diary resource not found") from exc
    if isinstance(exc, SpatialDiaryEpisodeConflictError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, SpatialDiaryEpisodeIntegrityError):
        raise HTTPException(500, "sealed spatial diary evidence is incomplete") from exc
    if isinstance(exc, SpatialDiaryTransactionError):
        raise HTTPException(500, "spatial diary snapshot could not be opened") from exc
    raise exc


async def _authorize_capsule(
    db: AsyncSession,
    principal: SpatialDiaryPrincipal,
    session_id: ResourceId,
) -> None:
    try:
        await ensure_repeatable_read_snapshot(db)
        dog_id = await capsule_dog_id(db, session_id)
    except (SpatialDiaryEpisodeNotFoundError, SpatialDiaryTransactionError) as exc:
        _raise_episode_http(exc)
    require_dog_access(principal, dog_id)


async def _authorize_offer(
    db: AsyncSession,
    principal: SpatialDiaryPrincipal,
    offer_id: ResourceId,
) -> None:
    try:
        await ensure_repeatable_read_snapshot(db)
        dog_id = await offer_dog_id(db, offer_id)
    except (SpatialDiaryEpisodeNotFoundError, SpatialDiaryTransactionError) as exc:
        _raise_episode_http(exc)
    require_dog_access(principal, dog_id)


@router.get("/walks/{session_id}/candidates", response_model=CandidateListOut)
async def read_candidates(
    session_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> CandidateListOut:
    await _authorize_capsule(db, principal, session_id)
    try:
        candidates = await list_episode_candidates(db, session_id)
    except _EPISODE_ERRORS as exc:
        _raise_episode_http(exc)
    return CandidateListOut(
        session_id=session_id,
        candidates=tuple(
            CandidateOut(candidate=item.candidate, claim_allowance=item.claim_allowance)
            for item in candidates
        ),
    )


@router.put("/offers/{offer_id}", response_model=EpisodeOfferSnapshot)
async def put_offer(
    offer_id: ResourceId,
    body: PutOfferIn,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> EpisodeOfferSnapshot:
    await _authorize_capsule(db, principal, body.session_id)
    try:
        offer = await put_episode_offer(
            db,
            offer_id=offer_id,
            session_id=body.session_id,
            source_observation_id=body.source_observation_id,
            candidate_policy_version=body.candidate_policy_version,
        )
        await db.commit()
        return offer
    except _EPISODE_ERRORS as exc:
        _raise_episode_http(exc)


@router.get("/walks/{session_id}/offers", response_model=OfferReviewListOut)
async def read_walk_offers(
    session_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> OfferReviewListOut:
    await _authorize_capsule(db, principal, session_id)
    try:
        states: list[OfferReviewState] = await list_offer_review_states(db, session_id)
    except _EPISODE_ERRORS as exc:
        _raise_episode_http(exc)
    return OfferReviewListOut(
        session_id=session_id,
        offers=tuple(
            OfferReviewStateOut(
                offer=state.offer,
                interactions=state.interactions,
                attestation=state.attestation,
                pin=state.pin,
            )
            for state in states
        ),
    )


@router.get("/walks/{session_id}/journal", response_model=WalkJournalProjection)
async def read_walk_journal(
    session_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> WalkJournalProjection:
    await _authorize_capsule(db, principal, session_id)
    try:
        return await query_walk_journal(db, session_id)
    except _EPISODE_ERRORS as exc:
        _raise_episode_http(exc)


@router.get("/offers/{offer_id}", response_model=EpisodeOfferSnapshot)
async def read_offer(
    offer_id: ResourceId,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> EpisodeOfferSnapshot:
    await _authorize_offer(db, principal, offer_id)
    offer = await get_episode_offer(db, offer_id)
    if offer is None:
        raise HTTPException(404, "spatial diary resource not found")
    return offer


@router.put(
    "/offers/{offer_id}/interactions/{interaction_id}",
    response_model=OfferInteraction,
)
async def put_interaction(
    offer_id: ResourceId,
    interaction_id: ResourceId,
    body: PutInteractionIn,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> OfferInteraction:
    await _authorize_offer(db, principal, offer_id)
    try:
        interaction = await put_offer_interaction(
            db,
            offer_id=offer_id,
            interaction_id=interaction_id,
            kind=body.kind,
        )
        await db.commit()
        return interaction
    except _EPISODE_ERRORS as exc:
        _raise_episode_http(exc)


@router.put(
    "/offers/{offer_id}/attestations/{attestation_id}",
    response_model=AttestationOut,
)
async def put_attestation(
    offer_id: ResourceId,
    attestation_id: ResourceId,
    body: PutAttestationIn,
    db: Annotated[AsyncSession, Depends(get_session)],
    principal: Annotated[SpatialDiaryPrincipal, Depends(get_spatial_diary_principal)],
) -> AttestationOut:
    await _authorize_offer(db, principal, offer_id)
    try:
        result: AttestationResult = await attest_episode_offer(
            db,
            offer_id=offer_id,
            attestation_id=attestation_id,
            review_disposition=body.review_disposition,
            claims=body.claims,
            memory_action=body.memory_action,
            pin_id=body.pin_id,
        )
        await db.commit()
        return AttestationOut(attestation=result.attestation, pin=result.pin)
    except _EPISODE_ERRORS as exc:
        _raise_episode_http(exc)
