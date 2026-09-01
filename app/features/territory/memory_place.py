"""안정 Memory Place와 capability-aware biography. Decision #78."""

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.spatial_diary.contract import (
    NEGATIVE_SPATIAL_CLAIM_POLICY_VERSION,
    CapabilitySupport,
    ContextFacetFilter,
    DriftAssessment,
    EntrySelector,
    EventFootprint,
    GeoPoint,
    MacroExposure,
    MemoryPlace,
    MemoryPlaceBiography,
    MemoryPlaceBiographyReceipt,
    MemoryPlaceBiographySpec,
    MemoryPlaceClaimCount,
    MemoryPlaceCohortSummary,
    MemoryPlaceMembership,
    MemoryPlaceMembershipOrigin,
    MemoryPlaceTimelineEntry,
    MemoryPlaceWalkReading,
    NegativeSpatialClaimAllowance,
    PlaceObservation,
    PrecipitationBiographyComparison,
    SpatialDiaryViewSpec,
    UnjudgeableReason,
)
from app.features.spatial_diary.episode import PinEntry, load_pin_entries, pin_entry_matches
from app.features.spatial_diary.snapshot import ensure_repeatable_read_snapshot
from app.features.territory.spatial_diary import (
    _CURRENT_PAINT_SPEC,
    CONTEXT_POLICY_VERSION,
    MAX_SELECTED_CAPSULES,
    QUALITY_POLICY_VERSION,
    MixedPaintGenerationError,
    SpatialDiaryViewTooLargeError,
    _count_capsules,
    _load_capsule_index,
    _load_sheets,
    _matches,
    _validate_spec,
    context_facets,
)
from app.features.walk.observation import MICRO_OBSERVATION_VERSION
from app.geo.cells import cell_size_m, hex_center_latlng

GROUPING_POLICY_VERSION = 1
EXPOSURE_POLICY_VERSION = 1
OBSERVATION_POLICY_VERSION = 2
MIN_PLACE_SUPPORT_WALKS = 2
MAX_SEED_PINS = 100
MAX_MEMORY_PLACES = 2_000
MAX_PLACE_MEMBERSHIPS = 2_000
MAX_RAW_OBSERVATIONS = 50_000
MIN_EVENT_RADIUS_M = 5.0
EARTH_R_M = 6_371_000.0

_DRIFT_UNJUDGEABLE_REASON = {
    DriftAssessment.NOT_ASSESSED: UnjudgeableReason.SPATIAL_DRIFT_NOT_ASSESSED,
    DriftAssessment.INSUFFICIENT_EVIDENCE: (
        UnjudgeableReason.SPATIAL_DRIFT_INSUFFICIENT_EVIDENCE
    ),
    DriftAssessment.NOT_SUSPECTED: None,
    DriftAssessment.SUSPECTED: UnjudgeableReason.SPATIAL_DRIFT_SUSPECTED,
}


class MemoryPlaceNotFoundError(LookupError):
    pass


class MemoryPlaceConflictError(RuntimeError):
    pass


class MemoryPlaceIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MemoryPlaceWithMemberships:
    place: MemoryPlace
    memberships: tuple[MemoryPlaceMembership, ...]


def _distance_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(h)))


def _seed_fingerprint(pin_ids: tuple[str, ...]) -> str:
    payload = {"grouping_policy_version": GROUPING_POLICY_VERSION, "pin_ids": pin_ids}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _biography_fingerprint(place_id: str, spec: MemoryPlaceBiographySpec) -> str:
    payload = {
        "place_id": place_id,
        "spec": spec.model_dump(mode="json"),
        "context_policy_version": CONTEXT_POLICY_VERSION,
        "exposure_policy_version": EXPOSURE_POLICY_VERSION,
        "observation_policy_version": OBSERVATION_POLICY_VERSION,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _place_from_row(row) -> MemoryPlace:
    return MemoryPlace(
        place_id=row.place_id,
        place_version=row.place_version,
        dog_id=row.dog_id,
        label=row.label,
        footprint=EventFootprint(
            kind=row.footprint_kind,
            centre=GeoPoint(lat=row.footprint_lat, lng=row.footprint_lng),
            radius_m=float(row.footprint_radius_m),
        ),
        grouping_policy_version=row.grouping_policy_version,
        seed_fingerprint=row.seed_fingerprint,
        created_at=row.created_at,
    )


_PLACE_SELECT = """
    SELECT place_id, place_version, dog_id, label, footprint_kind,
           ST_Y(footprint_centre::geometry) AS footprint_lat,
           ST_X(footprint_centre::geometry) AS footprint_lng,
           footprint_radius_m, grouping_policy_version, seed_fingerprint, created_at
    FROM spatial_diary_memory_place
"""


async def get_memory_place(db: AsyncSession, place_id: str) -> MemoryPlace | None:
    row = (
        await db.execute(
            text(_PLACE_SELECT + " WHERE place_id = :place_id"),
            {"place_id": place_id},
        )
    ).one_or_none()
    return _place_from_row(row) if row is not None else None


async def list_memory_places(db: AsyncSession, dog_id: str) -> tuple[MemoryPlace, ...]:
    rows = (await db.execute(text(_PLACE_SELECT + """
        WHERE dog_id = :dog_id
        ORDER BY created_at, place_id
        LIMIT :row_limit
    """), {"dog_id": dog_id, "row_limit": MAX_MEMORY_PLACES + 1})).all()
    if len(rows) > MAX_MEMORY_PLACES:
        raise SpatialDiaryViewTooLargeError(
            f"Memory Place v0 목록은 최대 {MAX_MEMORY_PLACES}개다"
        )
    return tuple(_place_from_row(row) for row in rows)


async def memory_place_dog_id(db: AsyncSession, place_id: str) -> str:
    row = (
        await db.execute(
            text("""
        SELECT dog_id FROM spatial_diary_memory_place WHERE place_id = :place_id
    """),
            {"place_id": place_id},
        )
    ).one_or_none()
    if row is None:
        raise MemoryPlaceNotFoundError("memory place not found")
    return row.dog_id


def _membership_from_row(row) -> MemoryPlaceMembership:
    return MemoryPlaceMembership(
        place_id=row.place_id,
        pin_id=row.pin_id,
        session_id=row.session_id,
        membership_version=row.membership_version,
        origin=row.origin,
        linked_at=row.linked_at,
    )


async def list_memory_place_memberships(
    db: AsyncSession,
    place_id: str,
) -> tuple[MemoryPlaceMembership, ...]:
    rows = (
        await db.execute(
            text("""
        SELECT membership.place_id, membership.pin_id, pin.session_id,
               membership.membership_version, membership.origin, membership.linked_at
        FROM spatial_diary_memory_place_membership membership
        JOIN spatial_diary_episode_pin pin ON pin.pin_id = membership.pin_id
        WHERE membership.place_id = :place_id
        ORDER BY pin.event_at NULLS LAST, membership.pin_id
        LIMIT :row_limit
    """),
            {
                "place_id": place_id,
                "row_limit": MAX_PLACE_MEMBERSHIPS + 1,
            },
        )
    ).all()
    if len(rows) > MAX_PLACE_MEMBERSHIPS:
        raise SpatialDiaryViewTooLargeError(
            f"Memory Place v0 membership는 최대 {MAX_PLACE_MEMBERSHIPS}개다"
        )
    return tuple(_membership_from_row(row) for row in rows)


def _covering_footprint(pin_rows) -> EventFootprint:
    points = tuple(GeoPoint(lat=row.lat, lng=row.lng) for row in pin_rows)
    centre = GeoPoint(
        lat=math.fsum(point.lat for point in points) / len(points),
        lng=math.fsum(point.lng for point in points) / len(points),
    )
    radius_m = max(
        _distance_m(centre, point) + float(row.radius_m)
        for point, row in zip(points, pin_rows, strict=True)
    )
    if radius_m > 5_000:
        raise MemoryPlaceConflictError("seed pins do not form one v1 Memory Place")
    return EventFootprint(centre=centre, radius_m=max(MIN_EVENT_RADIUS_M, radius_m))


async def put_memory_place(
    db: AsyncSession,
    *,
    place_id: str,
    dog_id: str,
    seed_pin_ids: tuple[str, ...],
    label: str | None = None,
    created_at: datetime | None = None,
) -> MemoryPlaceWithMemberships:
    """서로 다른 산책의 명시적 Pin 묶음을 안정 장소 identity로 승격한다."""

    await ensure_repeatable_read_snapshot(db)
    normalized = tuple(sorted(set(seed_pin_ids)))
    if len(normalized) != len(seed_pin_ids):
        raise MemoryPlaceConflictError("seed pin ids must be unique")
    if not MIN_PLACE_SUPPORT_WALKS <= len(normalized) <= MAX_SEED_PINS:
        raise MemoryPlaceConflictError(
            f"Memory Place v1 seed는 {MIN_PLACE_SUPPORT_WALKS}..{MAX_SEED_PINS}개 Pin이어야 한다"
        )
    seed_fp = _seed_fingerprint(normalized)
    existing = await get_memory_place(db, place_id)
    if existing is not None:
        if (
            existing.dog_id == dog_id
            and existing.seed_fingerprint == seed_fp
            and existing.label == label
        ):
            return MemoryPlaceWithMemberships(
                place=existing,
                memberships=await list_memory_place_memberships(db, place_id),
            )
        raise MemoryPlaceConflictError("place id already has different content")

    statement = text("""
        SELECT pin.pin_id, pin.session_id,
               ST_Y(pin.footprint_centre::geometry) AS lat,
               ST_X(pin.footprint_centre::geometry) AS lng,
               pin.footprint_radius_m AS radius_m,
               manifest.dog_id
        FROM spatial_diary_episode_pin pin
        JOIN walk_capsule_manifest manifest ON manifest.session_id = pin.session_id
        WHERE pin.pin_id IN :pin_ids
        ORDER BY pin.pin_id
    """).bindparams(bindparam("pin_ids", expanding=True))
    pin_rows = (await db.execute(statement, {"pin_ids": list(normalized)})).all()
    if len(pin_rows) != len(normalized):
        raise MemoryPlaceNotFoundError("one or more seed pins were not found")
    if {row.dog_id for row in pin_rows} != {dog_id}:
        raise MemoryPlaceNotFoundError("one or more seed pins were not found")
    if len({row.session_id for row in pin_rows}) < MIN_PLACE_SUPPORT_WALKS:
        raise MemoryPlaceConflictError("Memory Place requires distinct-walk support")

    footprint = _covering_footprint(pin_rows)
    place = MemoryPlace(
        place_id=place_id,
        dog_id=dog_id,
        label=label,
        footprint=footprint,
        grouping_policy_version=GROUPING_POLICY_VERSION,
        seed_fingerprint=seed_fp,
        created_at=created_at or datetime.now(UTC),
    )
    inserted = await db.execute(
        text("""
        INSERT INTO spatial_diary_memory_place
            (place_id, place_version, dog_id, label, footprint_kind, footprint_centre,
             footprint_radius_m, grouping_policy_version, seed_fingerprint, created_at)
        VALUES
            (:place_id, :place_version, :dog_id, :label, :footprint_kind,
             ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
             :radius_m, :grouping_policy_version, :seed_fingerprint, :created_at)
        ON CONFLICT DO NOTHING
        RETURNING place_id
    """),
        {
            **place.model_dump(exclude={"footprint"}),
            "footprint_kind": footprint.kind,
            "lat": footprint.centre.lat,
            "lng": footprint.centre.lng,
            "radius_m": footprint.radius_m,
        },
    )
    if inserted.scalar_one_or_none() is None:
        raise MemoryPlaceConflictError("place id or seed pins already belong to a place")

    linked_at = place.created_at
    for row in pin_rows:
        inserted_membership = await db.execute(
            text("""
            INSERT INTO spatial_diary_memory_place_membership
                (place_id, pin_id, membership_version, origin, linked_at)
            VALUES (:place_id, :pin_id, 1, 'seed', :linked_at)
            ON CONFLICT DO NOTHING
            RETURNING pin_id
        """),
            {"place_id": place_id, "pin_id": row.pin_id, "linked_at": linked_at},
        )
        if inserted_membership.scalar_one_or_none() is None:
            raise MemoryPlaceConflictError("one or more seed pins already belong to a place")
    return MemoryPlaceWithMemberships(
        place=place,
        memberships=await list_memory_place_memberships(db, place_id),
    )


async def put_memory_place_membership(
    db: AsyncSession,
    *,
    place_id: str,
    pin_id: str,
    linked_at: datetime | None = None,
) -> MemoryPlaceMembership:
    await ensure_repeatable_read_snapshot(db)
    existing = (
        await db.execute(
            text("""
        SELECT membership.place_id, membership.pin_id, pin.session_id,
               membership.membership_version, membership.origin, membership.linked_at
        FROM spatial_diary_memory_place_membership membership
        JOIN spatial_diary_episode_pin pin ON pin.pin_id = membership.pin_id
        WHERE membership.pin_id = :pin_id
    """),
            {"pin_id": pin_id},
        )
    ).one_or_none()
    if existing is not None:
        membership = _membership_from_row(existing)
        if membership.place_id == place_id:
            return membership
        raise MemoryPlaceConflictError("pin already belongs to another Memory Place")

    row = (
        await db.execute(
            text("""
        SELECT place.dog_id AS place_dog_id, pin.session_id,
               manifest.dog_id AS pin_dog_id,
               ST_DWithin(place.footprint_centre, pin.footprint_centre,
                          place.footprint_radius_m + pin.footprint_radius_m) AS overlaps
        FROM spatial_diary_memory_place place
        CROSS JOIN spatial_diary_episode_pin pin
        JOIN walk_capsule_manifest manifest ON manifest.session_id = pin.session_id
        WHERE place.place_id = :place_id AND pin.pin_id = :pin_id
    """),
            {"place_id": place_id, "pin_id": pin_id},
        )
    ).one_or_none()
    if row is None:
        raise MemoryPlaceNotFoundError("memory place or pin not found")
    if row.place_dog_id != row.pin_dog_id:
        raise MemoryPlaceNotFoundError("memory place or pin not found")
    if not row.overlaps:
        raise MemoryPlaceConflictError("pin footprint does not overlap the Memory Place")

    membership = MemoryPlaceMembership(
        place_id=place_id,
        pin_id=pin_id,
        session_id=row.session_id,
        origin=MemoryPlaceMembershipOrigin.USER_LINKED,
        linked_at=linked_at or datetime.now(UTC),
    )
    inserted = await db.execute(
        text("""
        INSERT INTO spatial_diary_memory_place_membership
            (place_id, pin_id, membership_version, origin, linked_at)
        VALUES (:place_id, :pin_id, :membership_version, :origin, :linked_at)
        ON CONFLICT DO NOTHING
        RETURNING pin_id
    """),
        membership.model_dump(exclude={"session_id"}),
    )
    if inserted.scalar_one_or_none() is None:
        raise MemoryPlaceConflictError("pin membership changed concurrently")
    return membership


def _macro_exposure(sheet, footprint: EventFootprint) -> MacroExposure:
    """셀 중심 안쪽은 exposed, 셀 경계만 겹치면 uncertain으로 보수적으로 분리한다."""

    uncertain = False
    cell_radius_m = cell_size_m(sheet.radius_u, footprint.centre.lat)
    for cell, occupancy in sheet.occupancy.items():
        if occupancy <= 0 or sheet.peak.get(cell, 0.0) < 0:
            continue
        lat, lng = hex_center_latlng(*cell, sheet.radius_u)
        distance = _distance_m(footprint.centre, GeoPoint(lat=lat, lng=lng))
        if distance <= footprint.radius_m:
            return MacroExposure.EXPOSED
        if distance <= footprint.radius_m + cell_radius_m:
            uncertain = True
    return MacroExposure.UNCERTAIN if uncertain else MacroExposure.NOT_EXPOSED


async def _observation_counts(
    db: AsyncSession,
    session_ids: list[str],
    footprint: EventFootprint,
) -> dict[str, int]:
    if not session_ids:
        return {}
    statement = text("""
        SELECT session_id, observation_version,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng,
               span_m, accuracy_p50_m
        FROM walk_micro_observation
        WHERE session_id IN :session_ids AND kind = 'slow'
        ORDER BY session_id, observation_index
        LIMIT :row_limit
    """).bindparams(bindparam("session_ids", expanding=True))
    rows = (await db.execute(statement, {
        "session_ids": session_ids,
        "row_limit": MAX_RAW_OBSERVATIONS + 1,
    })).all()
    if len(rows) > MAX_RAW_OBSERVATIONS:
        raise SpatialDiaryViewTooLargeError(
            f"Memory Place v0 원시 observation은 최대 {MAX_RAW_OBSERVATIONS}개다"
        )
    counts: Counter[str] = Counter()
    for row in rows:
        if row.observation_version != MICRO_OBSERVATION_VERSION:
            continue
        radius_m = max(
            MIN_EVENT_RADIUS_M,
            float(row.span_m) + (float(row.accuracy_p50_m) if row.accuracy_p50_m else 0.0),
        )
        if _distance_m(footprint.centre, GeoPoint(lat=row.lat, lng=row.lng)) <= (
            footprint.radius_m + radius_m
        ):
            counts[row.session_id] += 1
    return dict(counts)


def _timeline_and_claims(
    entries: list[PinEntry],
    member_pin_ids: set[str],
    entry_selector: EntrySelector,
) -> tuple[tuple[MemoryPlaceTimelineEntry, ...], tuple[MemoryPlaceClaimCount, ...]]:
    selected = [
        entry
        for entry in entries
        if entry.pin.pin_id in member_pin_ids
        and pin_entry_matches(
            entry,
            entry_selector.subject_roles,
            entry_selector.meaning_codes,
        )
    ]
    claim_counter = Counter(
        (claim.subject_role, claim.meaning_code, claim.vocabulary_version)
        for entry in selected
        for claim in entry.attestation.claims
    )
    claims = tuple(
        MemoryPlaceClaimCount(
            subject_role=role,
            meaning_code=meaning,
            vocabulary_version=version,
            pin_count=count,
        )
        for (role, meaning, version), count in sorted(
            claim_counter.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
        )
    )
    return tuple(
        MemoryPlaceTimelineEntry(pin=entry.pin, attestation=entry.attestation)
        for entry in selected
    ), claims


async def query_memory_place_biography(
    db: AsyncSession,
    place_id: str,
    spec: MemoryPlaceBiographySpec,
    *,
    view_as_of: datetime | None = None,
) -> MemoryPlaceBiography:
    view_spec = SpatialDiaryViewSpec(
        walk_selector=spec.walk_selector,
        entry_selector=spec.entry_selector,
        field_metric="visit_rate",
        quality_policy=spec.quality_policy,
    )
    _validate_spec(view_spec)
    await ensure_repeatable_read_snapshot(db)
    place = await get_memory_place(db, place_id)
    if place is None:
        raise MemoryPlaceNotFoundError("memory place not found")
    if place.dog_id != spec.walk_selector.dog_id:
        raise MemoryPlaceNotFoundError("memory place not found")

    total_capsules = await _count_capsules(db, place.dog_id)
    candidates = await _load_capsule_index(db, spec.walk_selector)
    selected = [capsule for capsule in candidates if _matches(spec.walk_selector, capsule)]
    if len(selected) > MAX_SELECTED_CAPSULES:
        raise SpatialDiaryViewTooLargeError(
            f"Memory Place v0 선택 Capsule은 최대 {MAX_SELECTED_CAPSULES}개다"
        )
    generations = {capsule.paint_spec.fingerprint for capsule in selected}
    if len(generations) > 1:
        raise MixedPaintGenerationError(
            f"한 biography에 paint 세대를 섞을 수 없다: {sorted(generations)}"
        )
    sheets = await _load_sheets(db, selected)
    sheet_by_session = {sheet.walk_id: sheet for sheet in sheets}
    session_ids = [capsule.session_id for capsule in selected]
    observed_counts = await _observation_counts(db, session_ids, place.footprint)

    memberships = await list_memory_place_memberships(db, place_id)
    member_pin_ids = {membership.pin_id for membership in memberships}
    all_entries = await load_pin_entries(db, session_ids, member_pin_ids)
    timeline, claim_counts = _timeline_and_claims(
        all_entries,
        member_pin_ids,
        spec.entry_selector,
    )
    pin_counts = Counter(entry.pin.session_id for entry in timeline)

    readings = []
    for capsule in selected:
        exposure = _macro_exposure(sheet_by_session[capsule.session_id], place.footprint)
        supported = any(
            capability.name == "low_motion" and capability.generation == MICRO_OBSERVATION_VERSION
            for capability in capsule.capabilities
        )
        capability = CapabilitySupport.SUPPORTED if supported else CapabilitySupport.UNSUPPORTED
        reasons = []
        if exposure is MacroExposure.NOT_EXPOSED:
            reasons.append(UnjudgeableReason.NOT_EXPOSED)
        elif exposure is MacroExposure.UNCERTAIN:
            reasons.append(UnjudgeableReason.EXPOSURE_UNCERTAIN)
        if capability is CapabilitySupport.UNSUPPORTED:
            reasons.append(UnjudgeableReason.CAPABILITY_UNSUPPORTED)
        episode_count = observed_counts.get(capsule.session_id, 0)
        drift_reason = _DRIFT_UNJUDGEABLE_REASON[capsule.drift_assessment]
        negative_blockers = [*reasons]
        if drift_reason is not None:
            negative_blockers.append(drift_reason)
        negative_spatial_claim = NegativeSpatialClaimAllowance(
            policy_version=NEGATIVE_SPATIAL_CLAIM_POLICY_VERSION,
            eligible=not negative_blockers,
            macro_exposure=exposure,
            capability=capability,
            drift_assessment=capsule.drift_assessment,
            blocking_reasons=tuple(negative_blockers),
        )
        # suspected drift는 좌표가 있는 긍정 관측도 막는다. 그 밖의 미평가 상태는 관측된
        # 사건을 approximate로 남기되, 사건 부재를 `not_observed`로 바꾸는 것만 막는다.
        if capsule.drift_assessment is DriftAssessment.SUSPECTED:
            reasons.append(UnjudgeableReason.SPATIAL_DRIFT_SUSPECTED)
        elif episode_count == 0 and drift_reason is not None:
            reasons.append(drift_reason)
        observation = (
            PlaceObservation.UNJUDGEABLE
            if reasons
            else PlaceObservation.OBSERVED
            if episode_count
            else PlaceObservation.NOT_OBSERVED
        )
        facets = context_facets(capsule.context)
        readings.append(
            MemoryPlaceWalkReading(
                session_id=capsule.session_id,
                walked_at=capsule.started_at,
                precipitation=facets["precipitation"],
                daylight=facets["daylight"],
                macro_exposure=exposure,
                capability=capability,
                observation=observation,
                negative_spatial_claim=negative_spatial_claim,
                observed_episode_count=episode_count,
                member_pin_count=pin_counts[capsule.session_id],
                unjudgeable_reasons=tuple(reasons),
            )
        )

    summary = MemoryPlaceCohortSummary(
        selected_walks=len(readings),
        exposed_walks=sum(item.macro_exposure is MacroExposure.EXPOSED for item in readings),
        not_exposed_walks=sum(
            item.macro_exposure is MacroExposure.NOT_EXPOSED for item in readings
        ),
        uncertain_exposure_walks=sum(
            item.macro_exposure is MacroExposure.UNCERTAIN for item in readings
        ),
        capability_supported_walks=sum(
            item.capability is CapabilitySupport.SUPPORTED for item in readings
        ),
        capability_unsupported_walks=sum(
            item.capability is CapabilitySupport.UNSUPPORTED for item in readings
        ),
        judgeable_walks=sum(
            item.observation is not PlaceObservation.UNJUDGEABLE for item in readings
        ),
        observed_walks=sum(item.observation is PlaceObservation.OBSERVED for item in readings),
        not_observed_walks=sum(
            item.observation is PlaceObservation.NOT_OBSERVED for item in readings
        ),
        unjudgeable_walks=sum(
            item.observation is PlaceObservation.UNJUDGEABLE for item in readings
        ),
        member_pin_count=len(timeline),
        distinct_member_walks=len({entry.pin.session_id for entry in timeline}),
    )
    paint_fp = selected[0].paint_spec.fingerprint if selected else _CURRENT_PAINT_SPEC.fingerprint
    receipt = MemoryPlaceBiographyReceipt(
        selector_fingerprint=_biography_fingerprint(place_id, spec),
        view_as_of=view_as_of or datetime.now(UTC),
        total_capsules=total_capsules,
        exposure_policy_version=EXPOSURE_POLICY_VERSION,
        observation_policy_version=OBSERVATION_POLICY_VERSION,
        context_policy_version=CONTEXT_POLICY_VERSION,
        quality_policy_version=QUALITY_POLICY_VERSION,
        paint_fp=paint_fp,
    )
    return MemoryPlaceBiography(
        place=place,
        spec=spec,
        summary=summary,
        readings=tuple(readings),
        timeline=timeline,
        claim_counts=claim_counts,
        receipt=receipt,
    )


def _with_precipitation(
    spec: MemoryPlaceBiographySpec,
    value: str,
) -> MemoryPlaceBiographySpec:
    facets = spec.walk_selector.context_facets + (
        ContextFacetFilter(
            axis="precipitation",
            values=(value,),
            policy_version=CONTEXT_POLICY_VERSION,
        ),
    )
    selector = spec.walk_selector.model_copy(update={"context_facets": facets})
    return spec.model_copy(update={"walk_selector": selector})


async def compare_memory_place_precipitation(
    db: AsyncSession,
    place_id: str,
    base_spec: MemoryPlaceBiographySpec,
    *,
    view_as_of: datetime | None = None,
) -> PrecipitationBiographyComparison:
    if any(facet.axis == "precipitation" for facet in base_spec.walk_selector.context_facets):
        raise MemoryPlaceConflictError(
            "precipitation comparison base selector cannot already filter precipitation"
        )
    as_of = view_as_of or datetime.now(UTC)
    rain = await query_memory_place_biography(
        db, place_id, _with_precipitation(base_spec, "rain"), view_as_of=as_of
    )
    dry = await query_memory_place_biography(
        db, place_id, _with_precipitation(base_spec, "dry"), view_as_of=as_of
    )
    unknown = await query_memory_place_biography(
        db, place_id, _with_precipitation(base_spec, "unknown"), view_as_of=as_of
    )
    return PrecipitationBiographyComparison(
        rain=rain,
        dry=dry,
        excluded_unknown_context_walks=unknown.summary.selected_walks,
    )
