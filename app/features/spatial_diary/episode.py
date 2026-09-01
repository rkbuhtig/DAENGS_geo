"""Capsule의 low-motion 재료를 실제 사용자 기억으로 승격하는 PR4 수직 경로."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.spatial_diary.contract import (
    AttestedClaim,
    ClaimAllowance,
    ClaimSupport,
    DriftAssessment,
    ElicitationMode,
    EpisodeCandidate,
    EpisodeOfferSnapshot,
    EpisodePin,
    EventFootprint,
    EvidenceValue,
    GeoPoint,
    MemoryAction,
    OfferInteraction,
    OfferInteractionKind,
    PinOrigin,
    ReviewDisposition,
    SubjectRole,
    TemporalPrecision,
    WalkAttestation,
)
from app.features.spatial_diary.snapshot import ensure_repeatable_read_snapshot

CANDIDATE_POLICY_VERSION = 1
CLAIM_POLICY_VERSION = 1
MAX_CANDIDATES_PER_WALK = 3
MIN_FOOTPRINT_RADIUS_M = 5.0


class SpatialDiaryEpisodeNotFoundError(LookupError):
    pass


class SpatialDiaryEpisodeConflictError(RuntimeError):
    pass


class SpatialDiaryEpisodeIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateWithAllowance:
    candidate: EpisodeCandidate
    claim_allowance: ClaimAllowance


@dataclass(frozen=True)
class AttestationResult:
    attestation: WalkAttestation
    pin: EpisodePin | None


@dataclass(frozen=True)
class PinEntry:
    pin: EpisodePin
    attestation: WalkAttestation


@dataclass(frozen=True)
class OfferReviewState:
    offer: EpisodeOfferSnapshot
    interactions: tuple[OfferInteraction, ...]
    attestation: WalkAttestation | None
    pin: EpisodePin | None


def _source_observation_id(session_id: str, version: int, index: int) -> str:
    readable = f"{session_id}:micro-v{version}:{index}"
    if len(readable) <= 128:
        return readable
    digest = sha256(f"{session_id}:{version}:{index}".encode()).hexdigest()[:32]
    return f"micro-v{version}:{digest}"


def _claim_allowance(
    evidence_ref: str,
    drift_assessment: DriftAssessment,
) -> ClaimAllowance:
    return ClaimAllowance(
        policy_version=CLAIM_POLICY_VERSION,
        evidence_ref=evidence_ref,
        # low-motion의 의미 시점은 관측창 중앙 투영이므로 exact라고 부르지 않는다.
        temporal=ClaimSupport.APPROXIMATE,
        # 현재 휴대폰만으로 drift 부재를 증명하지 못한다. suspected면 좌표 주장도 막는다.
        spatial=(
            ClaimSupport.UNSUPPORTED
            if drift_assessment is DriftAssessment.SUSPECTED
            else ClaimSupport.APPROXIMATE
        ),
        interpretation=ClaimSupport.ATTESTATION_REQUIRED,
    )


def _candidate_from_row(row, drift_assessment: DriftAssessment) -> CandidateWithAllowance:
    source_id = _source_observation_id(
        row.session_id,
        row.observation_version,
        row.observation_index,
    )
    point = GeoPoint(lat=row.lat, lng=row.lng)
    accuracy = float(row.accuracy_p50_m) if row.accuracy_p50_m is not None else 0.0
    radius_m = max(MIN_FOOTPRINT_RADIUS_M, float(row.span_m) + accuracy)
    evidence = (
        EvidenceValue(name="duration_s", value=float(row.duration_s), unit="s"),
        EvidenceValue(name="path_m", value=float(row.path_m), unit="m"),
        EvidenceValue(name="net_m", value=float(row.net_m), unit="m"),
        EvidenceValue(name="span_m", value=float(row.span_m), unit="m"),
        EvidenceValue(name="fix_count", value=row.fix_count, unit="fix"),
        EvidenceValue(
            name="accuracy_p50_m",
            value=(float(row.accuracy_p50_m) if row.accuracy_p50_m is not None else None),
            unit="m",
        ),
        EvidenceValue(name="abuts_break", value=row.abuts_break),
        EvidenceValue(name="route_offset_m", value=float(row.route_offset_m), unit="m"),
    )
    candidate = EpisodeCandidate(
        session_id=row.session_id,
        source_observation_ids=(source_id,),
        event_at=row.started_at + (row.ended_at - row.started_at) / 2,
        representative_point=point,
        event_footprint=EventFootprint(centre=point, radius_m=radius_m),
        evidence=evidence,
        candidate_policy_version=CANDIDATE_POLICY_VERSION,
    )
    return CandidateWithAllowance(
        candidate=candidate,
        claim_allowance=_claim_allowance(source_id, drift_assessment),
    )


async def capsule_dog_id(db: AsyncSession, session_id: str) -> str:
    row = (await db.execute(text("""
        SELECT dog_id
        FROM walk_capsule_manifest
        WHERE session_id = :session_id
    """), {"session_id": session_id})).one_or_none()
    if row is None:
        raise SpatialDiaryEpisodeNotFoundError("sealed walk capsule not found")
    return row.dog_id


async def offer_dog_id(db: AsyncSession, offer_id: str) -> str:
    row = (await db.execute(text("""
        SELECT manifest.dog_id
        FROM spatial_diary_episode_offer offer
        JOIN walk_capsule_manifest manifest ON manifest.session_id = offer.session_id
        WHERE offer.offer_id = :offer_id
    """), {"offer_id": offer_id})).one_or_none()
    if row is None:
        raise SpatialDiaryEpisodeNotFoundError("episode offer not found")
    return row.dog_id


async def list_episode_candidates(
    db: AsyncSession,
    session_id: str,
) -> list[CandidateWithAllowance]:
    await ensure_repeatable_read_snapshot(db)
    manifest = (await db.execute(text("""
        SELECT capabilities
        FROM walk_capsule_manifest
        WHERE session_id = :session_id
    """), {"session_id": session_id})).one_or_none()
    if manifest is None:
        raise SpatialDiaryEpisodeNotFoundError("sealed walk capsule not found")
    capabilities = {
        (item.get("name"), item.get("generation")) for item in manifest.capabilities
    }
    if ("low_motion", 1) not in capabilities:
        return []

    receipt = (await db.execute(text("""
        SELECT drift_assessment
        FROM walk_measurement_receipt
        WHERE session_id = :session_id
    """), {"session_id": session_id})).one_or_none()
    if receipt is None:
        raise SpatialDiaryEpisodeIntegrityError("sealed capsule is missing measurement receipt")
    drift_assessment = DriftAssessment(receipt.drift_assessment)

    rows = (await db.execute(text("""
        SELECT session_id, observation_index, observation_version,
               started_at, ended_at, duration_s,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng,
               path_m, net_m, span_m, fix_count, accuracy_p50_m,
               route_offset_m, abuts_break
        FROM walk_micro_observation
        WHERE session_id = :session_id
          AND observation_version = 1
          AND kind = 'slow'
          AND span_m + COALESCE(accuracy_p50_m, 0) <= 5000
        ORDER BY duration_s DESC, observation_index
        LIMIT :candidate_limit
    """), {
        "session_id": session_id,
        "candidate_limit": MAX_CANDIDATES_PER_WALK,
    })).all()
    return [_candidate_from_row(row, drift_assessment) for row in rows]


def _offer_prompt(candidate: EpisodeCandidate) -> str:
    duration = next(
        float(item.value) for item in candidate.evidence if item.name == "duration_s"
    )
    seconds = max(1, round(duration))
    return f"이 근처에서 약 {seconds}초 동안 천천히 움직였어요. 기억으로 남길 장면인가요?"


def _offer_from_row(row) -> EpisodeOfferSnapshot:
    return EpisodeOfferSnapshot(
        offer_id=row.offer_id,
        session_id=row.session_id,
        offer_version=row.offer_version,
        source_observation_ids=tuple(row.source_observation_ids),
        event_at=row.event_at,
        representative_point=GeoPoint(lat=row.representative_lat, lng=row.representative_lng),
        event_footprint=EventFootprint(
            kind=row.footprint_kind,
            centre=GeoPoint(lat=row.footprint_lat, lng=row.footprint_lng),
            radius_m=float(row.footprint_radius_m),
        ),
        evidence=tuple(EvidenceValue(**item) for item in row.evidence),
        candidate_policy_version=row.candidate_policy_version,
        claim_policy_version=row.claim_policy_version,
        prompt_snapshot=row.prompt_snapshot,
        offered_at=row.offered_at,
    )


_OFFER_SELECT = """
    SELECT offer_id, session_id, offer_version, source_observation_ids, event_at,
           ST_Y(representative_location::geometry) AS representative_lat,
           ST_X(representative_location::geometry) AS representative_lng,
           footprint_kind,
           ST_Y(footprint_centre::geometry) AS footprint_lat,
           ST_X(footprint_centre::geometry) AS footprint_lng,
           footprint_radius_m, evidence, candidate_policy_version,
           claim_policy_version, prompt_snapshot, offered_at
    FROM spatial_diary_episode_offer
"""


async def get_episode_offer(
    db: AsyncSession,
    offer_id: str,
) -> EpisodeOfferSnapshot | None:
    row = (await db.execute(
        text(_OFFER_SELECT + " WHERE offer_id = :offer_id"),
        {"offer_id": offer_id},
    )).one_or_none()
    return _offer_from_row(row) if row is not None else None


async def list_offer_review_states(
    db: AsyncSession,
    session_id: str,
) -> list[OfferReviewState]:
    await ensure_repeatable_read_snapshot(db)
    offer_rows = (await db.execute(
        text(_OFFER_SELECT + " WHERE session_id = :session_id ORDER BY offered_at, offer_id"),
        {"session_id": session_id},
    )).all()
    offers = [_offer_from_row(row) for row in offer_rows]
    states = []
    for offer in offers:
        interaction_rows = (await db.execute(text("""
            SELECT interaction_id, interaction_version, offer_id, kind, actor, occurred_at
            FROM spatial_diary_offer_interaction
            WHERE offer_id = :offer_id
            ORDER BY occurred_at, interaction_id
        """), {"offer_id": offer.offer_id})).all()
        attestation_row = (await db.execute(
            text(
                _ATTESTATION_SELECT
                + " WHERE offer_id = :offer_id ORDER BY attested_at DESC, attestation_id LIMIT 1"
            ),
            {"offer_id": offer.offer_id},
        )).one_or_none()
        attestation = (
            _attestation_from_row(attestation_row) if attestation_row is not None else None
        )
        pin = None
        if attestation is not None:
            pin_row = (await db.execute(
                text(_PIN_SELECT + " WHERE created_by_attestation_id = :attestation_id"),
                {"attestation_id": attestation.attestation_id},
            )).one_or_none()
            pin = _pin_from_row(pin_row) if pin_row is not None else None
        states.append(OfferReviewState(
            offer=offer,
            interactions=tuple(_interaction_from_row(row) for row in interaction_rows),
            attestation=attestation,
            pin=pin,
        ))
    return states


async def put_episode_offer(
    db: AsyncSession,
    *,
    offer_id: str,
    session_id: str,
    source_observation_id: str,
    candidate_policy_version: int,
    offered_at: datetime | None = None,
) -> EpisodeOfferSnapshot:
    await ensure_repeatable_read_snapshot(db)
    existing = await get_episode_offer(db, offer_id)
    if existing is not None:
        if (
            existing.session_id == session_id
            and existing.source_observation_ids == (source_observation_id,)
            and existing.candidate_policy_version == candidate_policy_version
        ):
            return existing
        raise SpatialDiaryEpisodeConflictError("offer id already has different content")
    if candidate_policy_version != CANDIDATE_POLICY_VERSION:
        raise SpatialDiaryEpisodeConflictError("candidate policy is stale")

    source_json = json.dumps([source_observation_id])
    prior_offer = (await db.execute(text("""
        SELECT offer_id
        FROM spatial_diary_episode_offer
        WHERE session_id = :session_id
          AND source_observation_ids = CAST(:source_observation_ids AS jsonb)
          AND candidate_policy_version = :candidate_policy_version
        LIMIT 1
    """), {
        "session_id": session_id,
        "source_observation_ids": source_json,
        "candidate_policy_version": candidate_policy_version,
    })).one_or_none()
    if prior_offer is not None:
        raise SpatialDiaryEpisodeConflictError("candidate already has an immutable offer")

    candidates = await list_episode_candidates(db, session_id)
    selected = next(
        (
            item
            for item in candidates
            if item.candidate.source_observation_ids == (source_observation_id,)
        ),
        None,
    )
    if selected is None:
        raise SpatialDiaryEpisodeConflictError("candidate is no longer offered by current policy")
    candidate = selected.candidate
    offer = EpisodeOfferSnapshot(
        offer_id=offer_id,
        session_id=session_id,
        source_observation_ids=candidate.source_observation_ids,
        event_at=candidate.event_at,
        representative_point=candidate.representative_point,
        event_footprint=candidate.event_footprint,
        evidence=candidate.evidence,
        candidate_policy_version=candidate.candidate_policy_version,
        claim_policy_version=selected.claim_allowance.policy_version,
        prompt_snapshot=_offer_prompt(candidate),
        offered_at=offered_at or datetime.now(UTC),
    )
    await db.execute(text("""
        INSERT INTO spatial_diary_episode_offer
            (offer_id, session_id, offer_version, source_observation_ids, event_at,
             representative_location, footprint_kind, footprint_centre,
             footprint_radius_m, evidence, candidate_policy_version,
             claim_policy_version, prompt_snapshot, offered_at)
        VALUES
            (:offer_id, :session_id, :offer_version,
             CAST(:source_observation_ids AS jsonb), :event_at,
             ST_SetSRID(ST_MakePoint(:representative_lng, :representative_lat), 4326)::geography,
             :footprint_kind,
             ST_SetSRID(ST_MakePoint(:footprint_lng, :footprint_lat), 4326)::geography,
             :footprint_radius_m, CAST(:evidence AS jsonb), :candidate_policy_version,
             :claim_policy_version, :prompt_snapshot, :offered_at)
        ON CONFLICT DO NOTHING
    """), {
        **offer.model_dump(
            exclude={
                "source_observation_ids",
                "representative_point",
                "event_footprint",
                "evidence",
            }
        ),
        "source_observation_ids": json.dumps(list(offer.source_observation_ids)),
        "representative_lat": offer.representative_point.lat,
        "representative_lng": offer.representative_point.lng,
        "footprint_kind": offer.event_footprint.kind,
        "footprint_lat": offer.event_footprint.centre.lat,
        "footprint_lng": offer.event_footprint.centre.lng,
        "footprint_radius_m": offer.event_footprint.radius_m,
        "evidence": json.dumps([item.model_dump(mode="json") for item in offer.evidence]),
    })
    stored = await get_episode_offer(db, offer_id)
    if stored is None:
        raise SpatialDiaryEpisodeConflictError("offer id or candidate already exists")
    if (
        stored.session_id != session_id
        or stored.source_observation_ids != (source_observation_id,)
        or stored.candidate_policy_version != candidate_policy_version
    ):
        raise SpatialDiaryEpisodeConflictError("offer id already has different content")
    return stored


def _interaction_from_row(row) -> OfferInteraction:
    return OfferInteraction(**dict(row._mapping))


async def put_offer_interaction(
    db: AsyncSession,
    *,
    offer_id: str,
    interaction_id: str,
    kind: OfferInteractionKind,
    occurred_at: datetime | None = None,
) -> OfferInteraction:
    await ensure_repeatable_read_snapshot(db)
    existing = (await db.execute(text("""
        SELECT interaction_id, interaction_version, offer_id, kind, actor, occurred_at
        FROM spatial_diary_offer_interaction
        WHERE interaction_id = :interaction_id
    """), {"interaction_id": interaction_id})).one_or_none()
    if existing is not None:
        interaction = _interaction_from_row(existing)
        if interaction.offer_id == offer_id and interaction.kind is kind:
            return interaction
        raise SpatialDiaryEpisodeConflictError("interaction id already has different content")
    offer_lock = (await db.execute(text("""
        SELECT offer_id
        FROM spatial_diary_episode_offer
        WHERE offer_id = :offer_id
        FOR UPDATE
    """), {"offer_id": offer_id})).one_or_none()
    if offer_lock is None:
        raise SpatialDiaryEpisodeNotFoundError("episode offer not found")
    terminal = (await db.execute(text("""
        SELECT kind
        FROM spatial_diary_offer_interaction
        WHERE offer_id = :offer_id AND kind IN ('dismissed', 'expired')
        ORDER BY occurred_at DESC, interaction_id
        LIMIT 1
    """), {"offer_id": offer_id})).one_or_none()
    if terminal is not None:
        raise SpatialDiaryEpisodeConflictError(f"offer is already {terminal.kind}")
    attestation = (await db.execute(text("""
        SELECT attestation_id
        FROM spatial_diary_walk_attestation
        WHERE offer_id = :offer_id
        LIMIT 1
    """), {"offer_id": offer_id})).one_or_none()
    if attestation is not None:
        raise SpatialDiaryEpisodeConflictError("offer already has an attestation")
    same_kind = (await db.execute(text("""
        SELECT interaction_id
        FROM spatial_diary_offer_interaction
        WHERE offer_id = :offer_id AND kind = :kind
        LIMIT 1
    """), {"offer_id": offer_id, "kind": kind.value})).one_or_none()
    if same_kind is not None:
        raise SpatialDiaryEpisodeConflictError(
            f"offer already has a {kind.value} interaction"
        )

    interaction = OfferInteraction(
        interaction_id=interaction_id,
        offer_id=offer_id,
        kind=kind,
        actor="user",
        occurred_at=occurred_at or datetime.now(UTC),
    )
    await db.execute(text("""
        INSERT INTO spatial_diary_offer_interaction
            (interaction_id, interaction_version, offer_id, kind, actor, occurred_at)
        VALUES
            (:interaction_id, :interaction_version, :offer_id, :kind, :actor, :occurred_at)
        ON CONFLICT (interaction_id) DO NOTHING
    """), interaction.model_dump())
    stored = (await db.execute(text("""
        SELECT interaction_id, interaction_version, offer_id, kind, actor, occurred_at
        FROM spatial_diary_offer_interaction
        WHERE interaction_id = :interaction_id
    """), {"interaction_id": interaction_id})).one()
    result = _interaction_from_row(stored)
    if result.offer_id != offer_id or result.kind is not kind:
        raise SpatialDiaryEpisodeConflictError("interaction id already has different content")
    return result


def _attestation_from_row(row) -> WalkAttestation:
    return WalkAttestation(
        attestation_id=row.attestation_id,
        attestation_version=row.attestation_version,
        session_id=row.session_id,
        elicitation_mode=row.elicitation_mode,
        offer_id=row.offer_id,
        review_disposition=row.review_disposition,
        claims=tuple(AttestedClaim(**item) for item in row.claims),
        memory_action=row.memory_action,
        attested_at=row.attested_at,
        supersedes_attestation_id=row.supersedes_attestation_id,
    )


def _pin_from_row(row) -> EpisodePin:
    return EpisodePin(
        pin_id=row.pin_id,
        pin_version=row.pin_version,
        session_id=row.session_id,
        origin=row.origin,
        source_offer_id=row.source_offer_id,
        created_by_attestation_id=row.created_by_attestation_id,
        event_at=row.event_at,
        temporal_precision=row.temporal_precision,
        representative_point=GeoPoint(lat=row.representative_lat, lng=row.representative_lng),
        event_footprint=EventFootprint(
            kind=row.footprint_kind,
            centre=GeoPoint(lat=row.footprint_lat, lng=row.footprint_lng),
            radius_m=float(row.footprint_radius_m),
        ),
        promoted_at=row.promoted_at,
    )


_ATTESTATION_SELECT = """
    SELECT attestation_id, attestation_version, session_id, offer_id,
           elicitation_mode, review_disposition, claims, memory_action,
           attested_at, supersedes_attestation_id
    FROM spatial_diary_walk_attestation
"""

_PIN_SELECT = """
    SELECT pin_id, pin_version, session_id, origin, source_offer_id,
           created_by_attestation_id, event_at, temporal_precision,
           ST_Y(representative_location::geometry) AS representative_lat,
           ST_X(representative_location::geometry) AS representative_lng,
           footprint_kind,
           ST_Y(footprint_centre::geometry) AS footprint_lat,
           ST_X(footprint_centre::geometry) AS footprint_lng,
           footprint_radius_m, promoted_at
    FROM spatial_diary_episode_pin
"""


async def _get_attestation_result(
    db: AsyncSession,
    attestation_id: str,
) -> AttestationResult | None:
    attestation_row = (await db.execute(
        text(_ATTESTATION_SELECT + " WHERE attestation_id = :attestation_id"),
        {"attestation_id": attestation_id},
    )).one_or_none()
    if attestation_row is None:
        return None
    pin_row = (await db.execute(
        text(_PIN_SELECT + " WHERE created_by_attestation_id = :attestation_id"),
        {"attestation_id": attestation_id},
    )).one_or_none()
    return AttestationResult(
        attestation=_attestation_from_row(attestation_row),
        pin=_pin_from_row(pin_row) if pin_row is not None else None,
    )


async def attest_episode_offer(
    db: AsyncSession,
    *,
    offer_id: str,
    attestation_id: str,
    review_disposition: ReviewDisposition,
    claims: tuple[AttestedClaim, ...],
    memory_action: MemoryAction,
    pin_id: str | None,
    attested_at: datetime | None = None,
) -> AttestationResult:
    await ensure_repeatable_read_snapshot(db)
    existing = await _get_attestation_result(db, attestation_id)
    if existing is not None:
        expected_pin_id = existing.pin.pin_id if existing.pin is not None else None
        attestation = existing.attestation
        if (
            attestation.offer_id == offer_id
            and attestation.review_disposition is review_disposition
            and attestation.claims == claims
            and attestation.memory_action is memory_action
            and expected_pin_id == pin_id
        ):
            return existing
        raise SpatialDiaryEpisodeConflictError("attestation id already has different content")

    offer_row = (await db.execute(
        text(_OFFER_SELECT + " WHERE offer_id = :offer_id FOR UPDATE"),
        {"offer_id": offer_id},
    )).one_or_none()
    if offer_row is None:
        raise SpatialDiaryEpisodeNotFoundError("episode offer not found")
    offer = _offer_from_row(offer_row)
    terminal = (await db.execute(text("""
        SELECT kind
        FROM spatial_diary_offer_interaction
        WHERE offer_id = :offer_id AND kind IN ('dismissed', 'expired')
        LIMIT 1
    """), {"offer_id": offer_id})).one_or_none()
    if terminal is not None:
        raise SpatialDiaryEpisodeConflictError(f"offer is already {terminal.kind}")
    prior = (await db.execute(text("""
        SELECT attestation_id
        FROM spatial_diary_walk_attestation
        WHERE offer_id = :offer_id
        LIMIT 1
    """), {"offer_id": offer_id})).one_or_none()
    if prior is not None:
        raise SpatialDiaryEpisodeConflictError("offer already has an attestation")

    attested = attested_at or datetime.now(UTC)
    attestation = WalkAttestation(
        attestation_id=attestation_id,
        session_id=offer.session_id,
        elicitation_mode=ElicitationMode.SYSTEM_OFFER,
        offer_id=offer.offer_id,
        review_disposition=review_disposition,
        claims=claims,
        memory_action=memory_action,
        attested_at=attested,
    )
    if (memory_action is MemoryAction.SAVE) != (pin_id is not None):
        raise SpatialDiaryEpisodeConflictError("save requires one pin id and dismiss forbids it")

    receipt = (await db.execute(text("""
        SELECT drift_assessment
        FROM walk_measurement_receipt
        WHERE session_id = :session_id
    """), {"session_id": offer.session_id})).one_or_none()
    if receipt is None:
        raise SpatialDiaryEpisodeIntegrityError("sealed capsule is missing measurement receipt")
    allowance = _claim_allowance(
        offer.source_observation_ids[0],
        DriftAssessment(receipt.drift_assessment),
    )
    if memory_action is MemoryAction.SAVE and allowance.spatial is ClaimSupport.UNSUPPORTED:
        raise SpatialDiaryEpisodeConflictError("current claim policy forbids a spatial pin")

    inserted_attestation = await db.execute(text("""
        INSERT INTO spatial_diary_walk_attestation
            (attestation_id, attestation_version, session_id, offer_id,
             elicitation_mode, review_disposition, claims, memory_action,
             attested_at, supersedes_attestation_id)
        VALUES
            (:attestation_id, :attestation_version, :session_id, :offer_id,
             :elicitation_mode, :review_disposition, CAST(:claims AS jsonb),
             :memory_action, :attested_at, :supersedes_attestation_id)
        ON CONFLICT (attestation_id) DO NOTHING
        RETURNING attestation_id
    """), {
        **attestation.model_dump(exclude={"claims"}),
        "claims": json.dumps([claim.model_dump(mode="json") for claim in claims]),
    })
    if inserted_attestation.scalar_one_or_none() is None:
        raise SpatialDiaryEpisodeConflictError(
            "attestation id already has different content"
        )

    pin = None
    if pin_id is not None:
        pin = EpisodePin(
            pin_id=pin_id,
            session_id=offer.session_id,
            origin=PinOrigin.SYSTEM_OFFER,
            source_offer_id=offer.offer_id,
            created_by_attestation_id=attestation.attestation_id,
            event_at=offer.event_at,
            temporal_precision=TemporalPrecision.APPROXIMATE,
            representative_point=offer.representative_point,
            event_footprint=offer.event_footprint,
            promoted_at=attested,
        )
        inserted_pin = await db.execute(text("""
            INSERT INTO spatial_diary_episode_pin
                (pin_id, pin_version, session_id, origin, source_offer_id,
                 created_by_attestation_id, event_at, temporal_precision,
                 representative_location, footprint_kind, footprint_centre,
                 footprint_radius_m, promoted_at)
            VALUES
                (:pin_id, :pin_version, :session_id, :origin, :source_offer_id,
                 :created_by_attestation_id, :event_at, :temporal_precision,
                 ST_SetSRID(ST_MakePoint(:representative_lng, :representative_lat),
                            4326)::geography,
                 :footprint_kind,
                 ST_SetSRID(ST_MakePoint(:footprint_lng, :footprint_lat), 4326)::geography,
                 :footprint_radius_m, :promoted_at)
            ON CONFLICT (pin_id) DO NOTHING
            RETURNING pin_id
        """), {
            **pin.model_dump(exclude={"representative_point", "event_footprint"}),
            "representative_lat": pin.representative_point.lat,
            "representative_lng": pin.representative_point.lng,
            "footprint_kind": pin.event_footprint.kind,
            "footprint_lat": pin.event_footprint.centre.lat,
            "footprint_lng": pin.event_footprint.centre.lng,
            "footprint_radius_m": pin.event_footprint.radius_m,
        })
        if inserted_pin.scalar_one_or_none() is None:
            raise SpatialDiaryEpisodeConflictError("pin id already has different content")
    return AttestationResult(attestation=attestation, pin=pin)


async def load_pin_entries(
    db: AsyncSession,
    session_ids: list[str],
    pin_ids: set[str] | None = None,
) -> list[PinEntry]:
    if not session_ids or pin_ids == set():
        return []
    pin_clause = " AND pin.pin_id IN :pin_ids" if pin_ids is not None else ""
    statement = text(f"""
        SELECT pin.pin_id, pin.pin_version, pin.session_id, pin.origin,
               pin.source_offer_id, pin.created_by_attestation_id,
               pin.event_at, pin.temporal_precision,
               ST_Y(pin.representative_location::geometry) AS representative_lat,
               ST_X(pin.representative_location::geometry) AS representative_lng,
               pin.footprint_kind,
               ST_Y(pin.footprint_centre::geometry) AS footprint_lat,
               ST_X(pin.footprint_centre::geometry) AS footprint_lng,
               pin.footprint_radius_m, pin.promoted_at,
               attestation.attestation_id, attestation.attestation_version,
               attestation.offer_id, attestation.elicitation_mode,
               attestation.review_disposition, attestation.claims,
               attestation.memory_action, attestation.attested_at,
               attestation.supersedes_attestation_id
        FROM spatial_diary_episode_pin pin
        JOIN spatial_diary_walk_attestation attestation
          ON attestation.attestation_id = pin.created_by_attestation_id
        WHERE pin.session_id IN :session_ids
        {pin_clause}
        ORDER BY pin.event_at NULLS LAST, pin.pin_id
    """).bindparams(bindparam("session_ids", expanding=True))
    parameters: dict[str, object] = {"session_ids": session_ids}
    if pin_ids is not None:
        statement = statement.bindparams(bindparam("pin_ids", expanding=True))
        parameters["pin_ids"] = sorted(pin_ids)
    rows = (await db.execute(statement, parameters)).all()
    entries = []
    for row in rows:
        pin = _pin_from_row(row)
        attestation = WalkAttestation(
            attestation_id=row.attestation_id,
            attestation_version=row.attestation_version,
            session_id=row.session_id,
            elicitation_mode=row.elicitation_mode,
            offer_id=row.offer_id,
            review_disposition=row.review_disposition,
            claims=tuple(AttestedClaim(**item) for item in row.claims),
            memory_action=row.memory_action,
            attested_at=row.attested_at,
            supersedes_attestation_id=row.supersedes_attestation_id,
        )
        entries.append(PinEntry(pin=pin, attestation=attestation))
    return entries


def pin_entry_matches(entry: PinEntry, roles: tuple[SubjectRole, ...], meanings: tuple[str, ...]) -> bool:
    if not roles and not meanings:
        return True
    return any(
        (not roles or claim.subject_role in roles)
        and (not meanings or claim.meaning_code in meanings)
        for claim in entry.attestation.claims
    )
