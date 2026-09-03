"""봉인된 Capsule을 필터 가능한 공간 일기 배경으로 읽는다. Decision: #76."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.features.spatial_diary.access import (
    SpatialDiaryPrincipal,
    get_spatial_diary_principal,
)
from app.features.spatial_diary.contract import (
    ContextFacetFilter,
    ContextStatus,
    EntrySelector,
    QualityPolicy,
    SpatialDiaryViewSpec,
    TrailContextSnapshot,
    WalkSelector,
)
from app.features.spatial_diary.snapshot import SpatialDiaryTransactionError
from app.features.territory import spatial_diary as spatial_diary_module
from app.features.territory.api import (
    query_view,
    view_out,
)
from app.features.territory.paint import BrushProfile, paint_spec
from app.features.territory.spatial_diary import (
    DIARY_CALENDAR_TIMEZONE,
    RAIN_THRESHOLD_MM,
    IncompleteCapsuleError,
    MixedPaintGenerationError,
    SpatialDiaryViewTooLargeError,
    UnsupportedSpatialDiaryViewError,
    context_facets,
    query_spatial_diary_view,
    selector_fingerprint,
)
from app.features.walk import store
from app.features.walk.capsule import (
    build_capsule_artifacts,
    trail_context_request,
)
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkSession
from tests.conftest import db_session, walk_fix

DOG_ID = "dog-spatial-diary"
SID_PREFIX = "test:diary:"
T0 = datetime(2026, 9, 1, 9, tzinfo=UTC)
PRINCIPAL = SpatialDiaryPrincipal(owner_id="owner-diary", dog_ids=frozenset({DOG_ID}))


def _spec(
    metric="visit_rate",
    *,
    facets=(),
    since: date | None = None,
    until: date | None = None,
    entry_selector: EntrySelector | None = None,
) -> SpatialDiaryViewSpec:
    return SpatialDiaryViewSpec(
        walk_selector=WalkSelector(
            dog_id=DOG_ID,
            since=since,
            until=until,
            context_facets=facets,
        ),
        entry_selector=entry_selector or EntrySelector(),
        field_metric=metric,
        quality_policy=QualityPolicy(policy_version=1, name="diary_v1"),
    )


def _context(
    session_id: str,
    walked_at: datetime,
    captured_at: datetime,
    *,
    precipitation_mm: float | None = None,
    sun_elevation_deg: float | None = None,
    status: ContextStatus = ContextStatus.CAPTURED,
) -> TrailContextSnapshot:
    if status is ContextStatus.UNKNOWN:
        return TrailContextSnapshot(
            session_id=session_id,
            status=status,
            walked_at=walked_at,
            captured_at=captured_at,
        )
    return TrailContextSnapshot(
        session_id=session_id,
        status=status,
        walked_at=walked_at,
        captured_at=captured_at,
        provider="fixture-weather",
        precipitation_mm=precipitation_mm,
        sun_elevation_deg=sun_elevation_deg,
    )


async def _seal_walk(
    db,
    name: str,
    started_at: datetime,
    *,
    precipitation_mm: float | None = None,
    sun_elevation_deg: float | None = None,
    status: ContextStatus = ContextStatus.CAPTURED,
) -> str:
    session_id = f"{SID_PREFIX}{name}"
    ended_at = started_at + timedelta(seconds=20)
    await store.upsert_session(
        db,
        WalkSession(id=session_id, dog_id=DOG_ID, started_at=started_at),
    )
    base = [walk_fix(second, second * 1.2) for second in (0, 5, 10, 15, 20)]
    fixes = [
        fix.model_copy(update={"at": started_at + timedelta(seconds=index * 5)})
        for index, fix in enumerate(base)
    ]
    await store.append_fixes(db, session_id, fixes)
    loaded = await store.load_fixes_ordered(db, session_id)
    computed = compute_facts(session_id, DOG_ID, started_at, ended_at, loaded)
    request = trail_context_request(computed.facts, computed.trail)
    captured_at = ended_at + timedelta(seconds=1)
    context = _context(
        session_id,
        request.walked_at,
        captured_at,
        precipitation_mm=precipitation_mm,
        sun_elevation_deg=sun_elevation_deg,
        status=status,
    )
    capsule = build_capsule_artifacts(
        computed.facts,
        computed.trail,
        computed.receipt_input,
        context,
        sealed_at=captured_at + timedelta(seconds=1),
    )
    await store.finalize(
        db,
        computed.facts,
        computed.trail.quality,
        computed.events,
        capsule=capsule,
    )
    return session_id


async def _cleanup(db):
    await db.rollback()
    await db.execute(
        text("DELETE FROM walk_session WHERE id LIKE :prefix"),
        {"prefix": f"{SID_PREFIX}%"},
    )
    await db.commit()


def test_context_facets_keep_missing_atoms_unknown_instead_of_inverting_them():
    captured_at = T0 + timedelta(hours=1)
    partial = _context(
        "walk-partial",
        T0,
        captured_at,
        precipitation_mm=RAIN_THRESHOLD_MM,
        status=ContextStatus.PARTIAL,
    )
    unknown = _context(
        "walk-unknown",
        T0,
        captured_at,
        status=ContextStatus.UNKNOWN,
    )

    assert context_facets(partial) == {"precipitation": "rain", "daylight": "unknown"}
    assert context_facets(unknown) == {
        "precipitation": "unknown",
        "daylight": "unknown",
    }


def test_context_facet_boundaries_and_selector_fingerprint_are_explicit():
    captured_at = T0 + timedelta(hours=1)
    dry_night = _context(
        "walk-dry",
        T0,
        captured_at,
        precipitation_mm=RAIN_THRESHOLD_MM - 0.01,
        sun_elevation_deg=-0.01,
    )
    day = _context(
        "walk-day",
        T0,
        captured_at,
        precipitation_mm=RAIN_THRESHOLD_MM,
        sun_elevation_deg=0,
    )
    spec = _spec()

    assert context_facets(dry_night) == {"precipitation": "dry", "daylight": "night"}
    assert context_facets(day) == {"precipitation": "rain", "daylight": "day"}
    assert selector_fingerprint(spec) == selector_fingerprint(spec)
    assert DIARY_CALENDAR_TIMEZONE == "Asia/Seoul"


async def test_view_filters_capsules_and_keeps_cohort_denominators_visible():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db, "rain-night", T0, precipitation_mm=1.2, sun_elevation_deg=-5)
            await _seal_walk(
                db,
                "dry-day",
                T0 + timedelta(days=1),
                precipitation_mm=0,
                sun_elevation_deg=10,
            )
            await _seal_walk(
                db,
                "unknown",
                T0 + timedelta(days=2),
                status=ContextStatus.UNKNOWN,
            )
            await db.commit()

            result = await query_spatial_diary_view(
                db,
                _spec(
                    facets=(
                        ContextFacetFilter(
                            axis="precipitation",
                            values=("rain",),
                            policy_version=1,
                        ),
                        ContextFacetFilter(
                            axis="daylight",
                            values=("night",),
                            policy_version=1,
                        ),
                    )
                ),
                view_as_of=T0 + timedelta(days=3),
            )

            assert result.field.metric == "visit_rate"
            assert result.field.values and set(result.field.values.values()) == {1.0}
            assert result.receipt.total_capsules == 3
            assert result.receipt.selected_capsules == 1
            assert result.receipt.contributing_capsules == 1
            assert (result.receipt.context_known_count, result.receipt.context_unknown_count) == (
                1,
                0,
            )
            assert result.receipt.pin_count == 0
        finally:
            await _cleanup(db)


async def test_unknown_is_an_explicit_filter_value_and_walk_utilization_is_normalized():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db, "known", T0, precipitation_mm=0, sun_elevation_deg=5)
            await _seal_walk(
                db,
                "partial-missing-precipitation",
                T0 + timedelta(days=1),
                sun_elevation_deg=5,
                status=ContextStatus.PARTIAL,
            )
            await db.commit()

            result = await query_spatial_diary_view(
                db,
                _spec(
                    "walk_utilization",
                    facets=(ContextFacetFilter(
                        axis="precipitation",
                        values=("unknown",),
                        policy_version=1,
                    ),),
                ),
            )

            assert result.receipt.selected_capsules == 1
            assert result.receipt.context_unknown_count == 1
            assert result.field.normalization == "equal_contributing_walks"
            assert math.fsum(result.field.values.values()) == pytest.approx(1.0)
        finally:
            await _cleanup(db)


async def test_view_query_uses_one_repeatable_read_snapshot_during_concurrent_delete(
    monkeypatch,
):
    async with db_session() as db:
        await _cleanup(db)
        try:
            session_id = await _seal_walk(
                db,
                "snapshot",
                T0,
                precipitation_mm=0,
                sun_elevation_deg=5,
            )
            await db.commit()
            original_load_sheets = spatial_diary_module._load_sheets

            async def delete_then_load(snapshot_db, selected):
                async with db_session() as deleting_db:
                    await deleting_db.execute(
                        text("DELETE FROM walk_session WHERE id = :session_id"),
                        {"session_id": session_id},
                    )
                    await deleting_db.commit()
                return await original_load_sheets(snapshot_db, selected)

            monkeypatch.setattr(spatial_diary_module, "_load_sheets", delete_then_load)

            result = await query_spatial_diary_view(db, _spec())

            assert result.receipt.selected_capsules == 1
            assert result.receipt.contributing_capsules == 1
            assert result.field.values
        finally:
            await db.rollback()
            await _cleanup(db)


async def test_view_query_requires_a_fresh_or_its_own_snapshot_transaction():
    async with db_session() as db:
        await db.execute(text("SELECT 1"))

        with pytest.raises(SpatialDiaryTransactionError, match="fresh session transaction"):
            await query_spatial_diary_view(db, _spec())

        await db.rollback()


async def test_view_query_rejects_unbounded_work(monkeypatch):
    async with db_session() as db:
        await _cleanup(db)
        try:
            with pytest.raises(SpatialDiaryViewTooLargeError, match="기간은 최대"):
                await query_spatial_diary_view(
                    db,
                    _spec(since=date(2025, 1, 1), until=date(2026, 1, 2)),
                )

            await _seal_walk(db, "bounded-one", T0, precipitation_mm=0, sun_elevation_deg=5)
            await _seal_walk(
                db,
                "bounded-two",
                T0 + timedelta(days=1),
                precipitation_mm=0,
                sun_elevation_deg=5,
            )
            await db.commit()

            monkeypatch.setattr(spatial_diary_module, "MAX_INDEX_ROWS", 1)
            with pytest.raises(SpatialDiaryViewTooLargeError, match="후보 Capsule index"):
                await query_spatial_diary_view(db, _spec())

            monkeypatch.setattr(spatial_diary_module, "MAX_INDEX_ROWS", 2_000)
            monkeypatch.setattr(spatial_diary_module, "MAX_SELECTED_CAPSULES", 1)
            with pytest.raises(SpatialDiaryViewTooLargeError, match="선택 Capsule"):
                await query_spatial_diary_view(db, _spec())

            monkeypatch.setattr(spatial_diary_module, "MAX_SELECTED_CAPSULES", 400)
            monkeypatch.setattr(spatial_diary_module, "MAX_RAW_CELL_ROWS", 1)
            with pytest.raises(SpatialDiaryViewTooLargeError, match="원시 cell"):
                await query_spatial_diary_view(db, _spec())

            monkeypatch.setattr(spatial_diary_module, "MAX_RAW_CELL_ROWS", 100_000)
            monkeypatch.setattr(spatial_diary_module, "MAX_RESULT_CELLS", 1)
            with pytest.raises(SpatialDiaryViewTooLargeError, match="결과 cell"):
                await query_spatial_diary_view(db, _spec())
        finally:
            await _cleanup(db)


async def test_date_filter_uses_the_declared_korean_calendar_day():
    async with db_session() as db:
        await _cleanup(db)
        try:
            # UTC 9월 1일이지만 KST로는 9월 2일이다.
            started_at = datetime(2026, 9, 1, 15, 30, tzinfo=UTC)
            await _seal_walk(db, "kst-next-day", started_at, precipitation_mm=0, sun_elevation_deg=-5)
            await db.commit()

            result = await query_spatial_diary_view(
                db,
                _spec(since=date(2026, 9, 2), until=date(2026, 9, 2)),
            )

            assert result.receipt.selected_capsules == 1
        finally:
            await _cleanup(db)


async def test_empty_cohort_is_an_empty_result_not_a_zero_percent_visit():
    async with db_session() as db:
        await _cleanup(db)
        try:
            result = await query_spatial_diary_view(db, _spec())
            response = view_out(result)

            assert result.field.values == {}
            assert result.field.denominator == 0
            assert result.receipt.total_capsules == 0
            assert result.receipt.selected_capsules == 0
            assert result.receipt.contributing_capsules == 0
            assert response.field.cells == ()
            assert response.projection.paint_fp == result.receipt.paint_fp
        finally:
            await _cleanup(db)


async def test_manifest_with_a_missing_required_child_fails_closed():
    async with db_session() as db:
        await _cleanup(db)
        try:
            session_id = await _seal_walk(
                db,
                "incomplete",
                T0,
                precipitation_mm=0,
                sun_elevation_deg=5,
            )
            await db.commit()
            await db.execute(
                text("DELETE FROM walk_trail_context WHERE session_id = :session_id"),
                {"session_id": session_id},
            )
            await db.commit()

            with pytest.raises(IncompleteCapsuleError, match="required view child"):
                await query_spatial_diary_view(db, _spec())
        finally:
            await _cleanup(db)


async def test_v0_rejects_unknown_metrics_and_mixed_paint_generations():
    async with db_session() as db:
        await _cleanup(db)
        try:
            first = await _seal_walk(db, "one", T0, precipitation_mm=0, sun_elevation_deg=5)
            await _seal_walk(db, "two", T0 + timedelta(days=1), precipitation_mm=0, sun_elevation_deg=5)
            await db.commit()

            with pytest.raises(UnsupportedSpatialDiaryViewError, match="field_metric"):
                await query_spatial_diary_view(db, _spec("total_time"))

            other = paint_spec(
                8.0,
                BrushProfile("fixture-other", (3.0, 8.0, 20.0), (1.0, 0.5, 0.1)),
            )
            await db.execute(text("""
                UPDATE walk_cellophane_sheet
                SET paint_version = :paint_version, grid_version = :grid_version,
                    radius_u = :radius_u, profile_name = :profile_name,
                    profile_fp = :profile_fp, sample_step_m = :sample_step_m,
                    paint_fp = :paint_fp
                WHERE session_id = :session_id
            """), {
                "session_id": first,
                "paint_version": other.paint_version,
                "grid_version": other.grid_version,
                "radius_u": other.radius_u,
                "profile_name": other.profile_name,
                "profile_fp": other.profile_fp,
                "sample_step_m": other.sample_step_m,
                "paint_fp": other.fingerprint,
            })
            await db.commit()

            with pytest.raises(MixedPaintGenerationError, match="paint 세대"):
                await query_spatial_diary_view(db, _spec())
        finally:
            await _cleanup(db)


async def test_http_surface_returns_sorted_cells_projection_and_receipt():
    async with db_session() as db:
        await _cleanup(db)
        try:
            await _seal_walk(db, "api", T0, precipitation_mm=0, sun_elevation_deg=5)
            await db.commit()

            response = await query_view(_spec(), db, PRINCIPAL)
            direct = view_out(await query_spatial_diary_view(db, _spec()))

            assert response.spec == _spec()
            assert response.projection.paint_fp == response.receipt.paint_fp
            assert response.field.cells == tuple(sorted(
                response.field.cells,
                key=lambda cell: (cell.q, cell.r),
            ))
            assert response.field.denominator == 1
            assert response.field.cells == direct.field.cells
        finally:
            await _cleanup(db)


async def test_http_surface_is_fail_closed_and_hides_unowned_dogs():
    with pytest.raises(HTTPException) as unavailable:
        get_spatial_diary_principal()
    assert unavailable.value.status_code == 503

    async with db_session() as db:
        outsider = SpatialDiaryPrincipal(
            owner_id="owner-outsider",
            dog_ids=frozenset({"another-dog"}),
        )

        with pytest.raises(HTTPException) as hidden:
            await query_view(_spec(), db, outsider)

        assert hidden.value.status_code == 404
