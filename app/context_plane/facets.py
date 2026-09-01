"""동결 Atom을 현재 정책으로 읽는 작은 파생 Facet 집합."""

from datetime import datetime

from app.context_plane.contract import (
    CONTEXT_FACET_POLICY_VERSION,
    ContextAtom,
    ContextAtomStatus,
    ContextCapabilityId,
    ContextFacet,
    DaylightFacetValueV1,
    MeasurementDriftFacetValueV1,
    PrecipitationFacetValueV1,
    SubjectAgeFacetValueV1,
    SubjectProfileSnapshotV1,
    TrailWeatherObservationV1,
    WalkMeasurementObservationV1,
)

RAIN_THRESHOLD_MM = 0.1


def trail_weather_facets(atom: ContextAtom) -> tuple[ContextFacet, ContextFacet]:
    if atom.capability_id is not ContextCapabilityId.WORLD_TRAIL_WEATHER:
        raise ValueError("weather facets require a trail weather atom")
    payload = atom.payload
    observed = atom.status in {ContextAtomStatus.KNOWN, ContextAtomStatus.PARTIAL}
    if observed and not isinstance(payload, TrailWeatherObservationV1):
        raise ValueError("observed weather atom requires typed weather payload")
    precipitation = (
        "unknown"
        if not isinstance(payload, TrailWeatherObservationV1) or payload.precipitation_mm is None
        else "rain"
        if payload.precipitation_mm >= RAIN_THRESHOLD_MM
        else "dry"
    )
    daylight = (
        "unknown"
        if not isinstance(payload, TrailWeatherObservationV1) or payload.sun_elevation_deg is None
        else "day"
        if payload.sun_elevation_deg >= 0
        else "night"
    )
    return (
        ContextFacet(
            facet_id=f"{atom.atom_id}:precipitation",
            value=PrecipitationFacetValueV1(state=precipitation),
            policy_version=CONTEXT_FACET_POLICY_VERSION,
            evidence_atom_ids=(atom.atom_id,),
        ),
        ContextFacet(
            facet_id=f"{atom.atom_id}:daylight",
            value=DaylightFacetValueV1(state=daylight),
            policy_version=CONTEXT_FACET_POLICY_VERSION,
            evidence_atom_ids=(atom.atom_id,),
        ),
    )


def subject_age_at_event_facet(atom: ContextAtom, event_at: datetime) -> ContextFacet:
    if atom.capability_id is not ContextCapabilityId.SUBJECT_DOG_PROFILE:
        raise ValueError("subject age facet requires a profile atom")
    payload = atom.payload
    if not isinstance(payload, SubjectProfileSnapshotV1):
        raise TypeError("age_at_event requires a captured profile snapshot, not only a revision ref")
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("event time must include a timezone")
    age_days = (event_at.date() - payload.birth_date).days
    if age_days < 0:
        raise ValueError("event cannot precede the subject birth date")
    return ContextFacet(
        facet_id=f"{atom.atom_id}:age_at_event",
        value=SubjectAgeFacetValueV1(age_years=round(age_days / 365.25, 1), at=event_at),
        policy_version=CONTEXT_FACET_POLICY_VERSION,
        evidence_atom_ids=(atom.atom_id,),
    )


def measurement_drift_facet(atom: ContextAtom) -> ContextFacet:
    if atom.capability_id is not ContextCapabilityId.MEASUREMENT_WALK_QUALITY:
        raise ValueError("drift facet requires a measurement atom")
    payload = atom.payload
    if not isinstance(payload, WalkMeasurementObservationV1):
        raise TypeError("drift facet requires a typed measurement payload")
    return ContextFacet(
        facet_id=f"{atom.atom_id}:drift",
        value=MeasurementDriftFacetValueV1(assessment=payload.drift_assessment),
        policy_version=CONTEXT_FACET_POLICY_VERSION,
        evidence_atom_ids=(atom.atom_id,),
    )
