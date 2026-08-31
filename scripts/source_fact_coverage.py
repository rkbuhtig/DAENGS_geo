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
from app.place.source_facts.kto import project_kto
from app.place.source_facts.states import FactState


def _increment(counter: Counter[str], value) -> None:
    counter[str(value) if value is not None else "null"] += 1


def summarize_kto(rows: list[tuple[dict, dict]]) -> dict:
    """DB I/O와 분리한 집계 함수. 행 하나가 실패해도 전체 측정을 숨기지 않는다."""

    counts: dict[str, Counter[str]] = {
        "projection_state": Counter(),
        "scope": Counter(),
        "scope_evidence_state": Counter(),
        "restriction_state": Counter(),
        "restriction_parse_state": Counter(),
        "predicate_code": Counter(),
        "issue_code": Counter(),
    }
    detail_rows = 0
    amenity_rows = 0
    taxonomy_rows = 0
    failures = 0

    for listing, detail in rows:
        has_detail = bool(detail)
        detail_rows += int(has_detail)
        try:
            projection = project_kto(
                listing or {},
                detail or None,
                # 현행 DB의 {}는 미호출·실패·no-data가 합쳐져 있다.
                detail_state=FactState.KNOWN if has_detail else FactState.UNKNOWN,
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
        "detail_absence_state": "unknown",
        "taxonomy_rows": taxonomy_rows,
        "amenity_rows": amenity_rows,
        "projection_failures": failures,
        **{name: dict(counter.most_common()) for name, counter in counts.items()},
    }


async def main() -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as db:
            result = await db.execute(
                text("""
                SELECT COALESCE(raw, '{}'::jsonb), COALESCE(pet, '{}'::jsonb)
                FROM facility
                WHERE source = 'kto'
                ORDER BY source_ref
            """)
            )
            rows = [(row[0], row[1]) for row in result]
    finally:
        await engine.dispose()

    print(json.dumps(summarize_kto(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
