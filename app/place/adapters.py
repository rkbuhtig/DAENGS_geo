"""기존 의료·시설 결과를 공통 Place 계약으로 옮기는 순수 adapter.

기존 API 응답은 유지한다. 다음 `/v2/places/search` resolver가 이 함수들을 호출하며, 현재
facility_link는 검증된 identity가 아니므로 aliases로 자동 변환하지 않는다.
"""

from datetime import datetime

from app.api.facility import FacilityOut
from app.geo.schemas import PlaceOut
from app.ingest.kcisa import KIND_MAPPING_VERSION as KCISA_MAPPING_VERSION
from app.ingest.kto import KIND_MAPPING_VERSION as KTO_MAPPING_VERSION
from app.ingest.mois import KIND_MAPPING_VERSION as MOIS_MAPPING_VERSION
from app.ingest.mois import SOURCES
from app.place.contracts import (
    FieldProvenance,
    MedicalFacts,
    PetAccessFacts,
    PlaceClassification,
    PlaceFacts,
    PlaceRef,
    PlaceResult,
)

_FACILITY_MAPPING_VERSIONS = {
    "kcisa": KCISA_MAPPING_VERSION,
    "kto": KTO_MAPPING_VERSION,
}
_MEDICAL_SOURCE_CATEGORIES = {
    definition.source: definition.slug for definition in SOURCES.values()
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _required_ref(source: str | None, ref: str | None) -> PlaceRef:
    if not source or not ref:
        raise ValueError("PlaceResult requires an external (source, ref) key")
    return PlaceRef(source=source, ref=ref)


def medical_place_result(value: PlaceOut) -> PlaceResult:
    """MOIS `PlaceOut` → 공통 계약. ORM 내부 id는 결과에 복사하지 않는다."""
    key = _required_ref(value.source, value.source_ref)
    try:
        source_category = _MEDICAL_SOURCE_CATEGORIES[key.source]
    except KeyError as exc:
        raise ValueError(f"unknown medical classification source: {key.source}") from exc

    field_sources: dict[str, FieldProvenance] = {}
    if value.hours_source:
        if not value.hours_source_ref:
            raise ValueError("borrowed medical hours require an external source ref")
        borrowed = FieldProvenance(
            source=PlaceRef(
                source=str(value.hours_source["name"]), ref=value.hours_source_ref,
            ),
            as_of=value.hours_source.get("as_of"),
        )
        if value.hours_text is not None:
            field_sources["facts.hours_text"] = borrowed
        if value.closed_days is not None:
            field_sources["facts.closed_days"] = borrowed

    return PlaceResult(
        key=key,
        name=value.name,
        lat=value.lat,
        lng=value.lng,
        distance_m=value.distance_m,
        matched_kind=value.kind,
        classifications=[PlaceClassification(
            source=key,
            source_category=source_category,
            kind=value.kind,
            mapping_version=MOIS_MAPPING_VERSION,
            as_of=_iso(value.source_updated_at),
        )],
        facts=PlaceFacts(
            address=value.address,
            phone=value.phone,
            hours_text=value.hours_text,
            closed_days=value.closed_days,
            medical=MedicalFacts(
                active=value.active,
                license_status_code=value.license_status_code,
                license_status_name=value.license_status_name,
                is_night=value.is_night,
                is_24h=value.is_24h,
                open_now=value.open_now,
                hours_today=value.hours_today,
                tags=value.tags,
                area_m2=value.area_m2,
                staff_count=value.staff_count,
            ),
        ),
        field_sources=field_sources,
    )


def facility_place_result(value: FacilityOut) -> PlaceResult:
    """KCISA/KTO `FacilityOut` → 공통 계약. legacy category3 표시는 그대로 둔다."""
    key = _required_ref(value.source.name, value.source_ref)
    try:
        mapping_version = _FACILITY_MAPPING_VERSIONS[key.source]
    except KeyError as exc:
        raise ValueError(f"unknown facility classification source: {key.source}") from exc
    if not value.classification_category:
        raise ValueError(f"missing mapping input category for {key.source}:{key.ref}")

    field_sources: dict[str, FieldProvenance] = {}
    borrowed_fields = value.place_field_sources or value.field_sources
    for field, source in borrowed_fields.items():
        borrowed_key = _required_ref(source.name, source.ref)
        path = "facts.pet_access" if field == "pet" else f"facts.{field}"
        field_sources[path] = FieldProvenance(source=borrowed_key, as_of=source.as_of)

    return PlaceResult(
        key=key,
        name=value.name,
        lat=value.lat,
        lng=value.lng,
        distance_m=value.distance_m,
        matched_kind=value.kind,
        classifications=[PlaceClassification(
            source=key,
            source_category=value.classification_category,
            kind=value.kind,
            mapping_version=mapping_version,
            as_of=value.source.as_of,
        )],
        facts=PlaceFacts(
            address=value.address,
            phone=value.phone,
            homepage=value.homepage,
            hours_text=value.hours_text,
            closed_days=value.closed_days,
            parking=value.parking,
            indoor=value.indoor,
            outdoor=value.outdoor,
            pet_access=PetAccessFacts(
                raw=value.pet,
                allowed=value.pet_axes.allowed,
                exclusive=value.pet_axes.exclusive,
                dog_ok=value.pet_axes.dog_ok,
                size_class=value.pet_axes.size_class,
                max_kg=value.pet_axes.max_kg,
            ),
        ),
        field_sources=field_sources,
    )
