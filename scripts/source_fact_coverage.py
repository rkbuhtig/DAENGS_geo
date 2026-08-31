"""현재 KTO 저장 레코드를 source-facts projector로 읽어 커버리지를 잰다.

DB를 읽기만 하며 API 호출이나 적재는 하지 않는다.

    uv run python scripts/source_fact_coverage.py
"""

import asyncio
import json
import sys
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.place.source_facts.kcisa import project_kcisa
from app.place.source_facts.kto import project_kto
from app.place.source_facts.states import (
    DetailAcquisitionState,
    FactState,
    acquisition_fact_state,
)


def _increment(counter: Counter[str], value) -> None:
    counter[str(value) if value is not None else "null"] += 1


def _facts(projection) -> tuple:
    return (
        projection.purpose,
        projection.pet_access,
        projection.restrictions,
        projection.amenities,
        projection.pet_fee,
        projection.operations,
        projection.issues,
    )


_FACT_SECTIONS = (
    "purpose",
    "pet_access",
    "restrictions",
    "amenities",
    "pet_fee",
    "operations",
    "issues",
)


def _fact_diff(left, right) -> list[str]:
    return [
        name
        for name, left_value, right_value in zip(
            _FACT_SECTIONS, _facts(left), _facts(right), strict=True
        )
        if left_value != right_value
    ]


def summarize_kto(rows: list[tuple[dict, dict | None, DetailAcquisitionState]]) -> dict:
    """DB I/O와 분리한 집계 함수. 행 하나가 실패해도 전체 측정을 숨기지 않는다."""

    counts: dict[str, Counter[str]] = {
        "projection_state": Counter(),
        "scope": Counter(),
        "scope_evidence_state": Counter(),
        "restriction_state": Counter(),
        "restriction_parse_state": Counter(),
        "predicate_code": Counter(),
        "issue_code": Counter(),
        "detail_acquisition_state": Counter(),
    }
    detail_rows = 0
    amenity_rows = 0
    taxonomy_rows = 0
    failures = 0

    for listing, detail, acquisition_state in rows:
        has_detail = bool(detail)
        detail_rows += int(has_detail)
        _increment(counts["detail_acquisition_state"], acquisition_state.value)
        try:
            projection = project_kto(
                listing or {},
                detail or None,
                detail_state=acquisition_fact_state(acquisition_state),
            )
        except (TypeError, ValueError):
            failures += 1
            continue

        _increment(counts["projection_state"], projection.state.value)
        _increment(counts["scope"], projection.pet_access.scope)
        _increment(
            counts["scope_evidence_state"],
            projection.evidence["pet_access.scope"].state.value,
        )
        _increment(counts["restriction_state"], projection.restrictions.state)
        _increment(counts["restriction_parse_state"], projection.restrictions.parse_state)
        counts["predicate_code"].update(
            predicate.code for predicate in projection.restrictions.predicates
        )
        counts["issue_code"].update(issue.code for issue in projection.issues)
        amenity_rows += int(
            any(
                (
                    projection.amenities.facilities,
                    projection.amenities.provided_products,
                    projection.amenities.purchasable_products,
                    projection.amenities.rentable_products,
                )
            )
        )
        taxonomy_rows += int(bool(projection.purpose.taxonomy_path))

    return {
        "source": "kto",
        "rows": len(rows),
        "detail_rows": detail_rows,
        "taxonomy_rows": taxonomy_rows,
        "amenity_rows": amenity_rows,
        "projection_failures": failures,
        **{name: dict(counter.most_common()) for name, counter in counts.items()},
    }


def compare_kto_shadow(rows: list[tuple[dict, dict | None, str, dict | None, dict | None]]) -> dict:
    """shadow와 현행 facility 봉투를 facts 저장 없이 같은 projector로 비교한다."""

    listing_equal = 0
    detail_equal = 0
    projection_equal = 0
    missing_facility = 0
    for listing, detail, detail_state, current_listing, current_detail in rows:
        if current_listing is None:
            missing_facility += 1
            continue
        listing_equal += int(listing == current_listing)
        detail_equal += int((detail or {}) == (current_detail or {}))

        shadow = project_kto(
            listing,
            detail,
            detail_state=acquisition_fact_state(DetailAcquisitionState(detail_state)),
        )
        current = project_kto(
            current_listing,
            current_detail,
            detail_state=(FactState.KNOWN if current_detail else FactState.UNKNOWN),
        )
        projection_equal += int(_facts(shadow) == _facts(current))

    matched = len(rows) - missing_facility
    return {
        "rows": len(rows),
        "missing_facility": missing_facility,
        "matched_facility": matched,
        "listing_raw_equal": listing_equal,
        "listing_raw_different": matched - listing_equal,
        "detail_raw_equal": detail_equal,
        "detail_raw_different": matched - detail_equal,
        "projection_facts_equal": projection_equal,
        "projection_facts_different": matched - projection_equal,
    }


def summarize_kcisa(rows: list[tuple[dict, int, str, dict | None]]) -> dict:
    """필터 전 KCISA distinct 원문과 제품 facility의 차이를 함께 잰다."""

    projection_states: Counter[str] = Counter()
    purposes: Counter[str] = Counter()
    allowed: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    failures = 0
    missing_facility = 0
    listing_equal = 0
    projection_equal = 0
    mismatch_samples: list[dict] = []

    for listing, occurrence_count, source_ref, current_listing in rows:
        try:
            shadow = project_kcisa(listing)
        except (TypeError, ValueError):
            failures += 1
            continue
        _increment(projection_states, shadow.state.value)
        _increment(purposes, shadow.purpose.primary)
        _increment(allowed, shadow.pet_access.allowed)
        issues.update(issue.code for issue in shadow.issues)

        if current_listing is None:
            missing_facility += 1
            continue
        listing_equal += int(listing == current_listing)
        try:
            current = project_kcisa(current_listing)
        except (TypeError, ValueError):
            continue
        different_sections = _fact_diff(shadow, current)
        projection_equal += int(not different_sections)
        if different_sections and len(mismatch_samples) < 20:
            mismatch_samples.append({
                "source_ref": source_ref,
                "name": listing.get("시설명"),
                "sections": different_sections,
            })

    matched = len(rows) - missing_facility
    return {
        "source": "kcisa",
        "distinct_records": len(rows),
        "physical_rows": sum(occurrence_count for _, occurrence_count, _, _ in rows),
        "product_refs": len({source_ref for _, _, source_ref, _ in rows}),
        "projection_failures": failures,
        "projection_state": dict(projection_states.most_common()),
        "purpose": dict(purposes.most_common()),
        "allowed": dict(allowed.most_common()),
        "issue_code": dict(issues.most_common()),
        "dual_read": {
            "missing_facility": missing_facility,
            "matched_facility": matched,
            "listing_raw_equal": listing_equal,
            "listing_raw_different": matched - listing_equal,
            "projection_facts_equal": projection_equal,
            "projection_facts_different": matched - projection_equal,
            "projection_mismatch_samples": mismatch_samples,
        },
    }


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as db:
            result = await db.execute(
                text("""
                SELECT sr.listing_raw, sr.detail_raw, sr.detail_state, f.raw, f.pet
                FROM facility_source_record sr
                LEFT JOIN facility f
                  ON f.source = sr.source AND f.source_ref = sr.source_ref
                WHERE sr.source = 'kto'
                ORDER BY sr.source_ref
            """)
            )
            rows = [tuple(row) for row in result]
            kcisa_result = await db.execute(
                text("""
                SELECT sr.listing_raw, sr.occurrence_count, sr.source_ref, f.raw
                FROM facility_source_record sr
                LEFT JOIN facility f
                  ON f.source = sr.source AND f.source_ref = sr.source_ref
                WHERE sr.source = 'kcisa'
                ORDER BY sr.record_ref
            """)
            )
            kcisa_rows = [tuple(row) for row in kcisa_result]
    finally:
        await engine.dispose()

    projection_rows = [
        (listing, detail, DetailAcquisitionState(detail_state))
        for listing, detail, detail_state, _, _ in rows
    ]
    output = summarize_kto(projection_rows)
    output["dual_read"] = compare_kto_shadow(rows)
    output["kcisa"] = summarize_kcisa(kcisa_rows)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
