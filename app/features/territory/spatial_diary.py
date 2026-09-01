"""봉인된 Walk Capsule을 조건별 Cellophane field와 Episode Pin으로 읽는다. #76·#77.

기간·강수·낮/밤으로 산책을 고르고 visit_rate 또는 walk_utilization을 계산한 뒤, Walk cohort는
건드리지 않고 EntrySelector를 안정 Pin overlay에만 적용한다. quality judgeability는 아직
만들지 않으며 지원하지 않는 요청을 무시한 채 빈 결과로 바꾸지 않는다.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.spatial_diary.context import (
    CONTEXT_POLICY_VERSION,
    DIARY_CALENDAR_TIMEZONE,
    FACET_VALUES,
    RAIN_THRESHOLD_MM,
    context_facets,
)
from app.features.spatial_diary.contract import (
    DriftAssessment,
    ObservationCapability,
    SpatialDiaryViewReceipt,
    SpatialDiaryViewSpec,
    TrailContextSnapshot,
    WalkSelector,
)
from app.features.spatial_diary.episode import (
    CLAIM_POLICY_VERSION,
    PinEntry,
    load_pin_entries,
    pin_entry_matches,
)
from app.features.spatial_diary.snapshot import ensure_repeatable_read_snapshot
from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import Cellophane, PaintSpec, paint_spec
from app.features.territory.spatial_stats import SpatialField, spatial_field
from app.features.walk.capsule import CAPSULE_PROFILE, CAPSULE_RADIUS_U

QUALITY_POLICY_VERSION = 1
QUALITY_POLICY_NAME = "diary_v1"
MAX_VIEW_RANGE_DAYS = 366
MAX_INDEX_ROWS = 2_000
MAX_SELECTED_CAPSULES = 400
MAX_RAW_CELL_ROWS = 100_000
MAX_RESULT_CELLS = 50_000
MAX_RESULT_PINS = 2_000

SUPPORTED_METRICS = frozenset({"visit_rate", "walk_utilization"})
_DIARY_ZONE = ZoneInfo(DIARY_CALENDAR_TIMEZONE)
_CURRENT_PAINT_SPEC = paint_spec(CAPSULE_RADIUS_U, CAPSULE_PROFILE)


class UnsupportedSpatialDiaryViewError(ValueError):
    pass


class MixedPaintGenerationError(ValueError):
    pass


class IncompleteCapsuleError(RuntimeError):
    pass


class SpatialDiaryViewTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class CapsuleIndex:
    """셀 payload를 읽기 전에 cohort를 고르는 작은 Capsule 색인 행."""

    session_id: str
    started_at: datetime
    paint_spec: PaintSpec
    context: TrailContextSnapshot
    capabilities: tuple[ObservationCapability, ...]
    drift_assessment: DriftAssessment


@dataclass(frozen=True)
class SpatialDiaryViewResult:
    spec: SpatialDiaryViewSpec
    field: SpatialField
    pins: tuple[PinEntry, ...]
    receipt: SpatialDiaryViewReceipt


def selector_fingerprint(spec: SpatialDiaryViewSpec) -> str:
    """숨은 v0 정책까지 포함한 재현 지문."""

    payload = {
        "spec": spec.model_dump(mode="json"),
        "context_policy_version": CONTEXT_POLICY_VERSION,
        "calendar_timezone": DIARY_CALENDAR_TIMEZONE,
        "rain_threshold_mm": RAIN_THRESHOLD_MM,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _validate_spec(spec: SpatialDiaryViewSpec) -> None:
    if spec.field_metric not in SUPPORTED_METRICS:
        raise UnsupportedSpatialDiaryViewError(
            f"SpatialDiaryView v0 field_metric은 {sorted(SUPPORTED_METRICS)}만 지원한다"
        )
    if (
        spec.quality_policy.policy_version != QUALITY_POLICY_VERSION
        or spec.quality_policy.name != QUALITY_POLICY_NAME
    ):
        raise UnsupportedSpatialDiaryViewError(
            f"SpatialDiaryView v0 quality policy는 {QUALITY_POLICY_NAME} v{QUALITY_POLICY_VERSION}이다"
        )
    since = spec.walk_selector.since
    until = spec.walk_selector.until
    if since is not None and until is not None:
        inclusive_days = (until - since).days + 1
        if inclusive_days > MAX_VIEW_RANGE_DAYS:
            raise SpatialDiaryViewTooLargeError(
                f"SpatialDiaryView v0 기간은 최대 {MAX_VIEW_RANGE_DAYS}일이다"
            )
    for facet in spec.walk_selector.context_facets:
        allowed = FACET_VALUES.get(facet.axis)
        if allowed is None:
            raise UnsupportedSpatialDiaryViewError(
                f"지원하지 않는 context facet axis: {facet.axis!r}"
            )
        if facet.policy_version != CONTEXT_POLICY_VERSION:
            raise UnsupportedSpatialDiaryViewError(
                f"context facet policy_version은 {CONTEXT_POLICY_VERSION}이어야 한다"
            )
        unknown = set(facet.values) - allowed
        if unknown:
            raise UnsupportedSpatialDiaryViewError(
                f"{facet.axis}의 지원하지 않는 값: {sorted(unknown)}"
            )


def _matches(selector: WalkSelector, capsule: CapsuleIndex) -> bool:
    local_day = capsule.started_at.astimezone(_DIARY_ZONE).date()
    if selector.since is not None and local_day < selector.since:
        return False
    if selector.until is not None and local_day > selector.until:
        return False
    derived = context_facets(capsule.context)
    return all(derived[facet.axis] in facet.values for facet in selector.context_facets)


def _context_is_known(snapshot: TrailContextSnapshot, selector: WalkSelector) -> bool:
    """선택에 사용한 축, 또는 무필터라면 모든 지원 축의 값이 있어야 known이다."""

    required_axes = {facet.axis for facet in selector.context_facets} or set(FACET_VALUES)
    derived = context_facets(snapshot)
    return all(derived[axis] != "unknown" for axis in required_axes)


def _index_from_row(row) -> CapsuleIndex:
    if (
        row.paint_version is None
        or row.context_version is None
        or row.started_at is None
        or row.drift_assessment is None
    ):
        raise IncompleteCapsuleError(
            f"sealed capsule {row.session_id!r} is missing a required view child"
        )
    context = TrailContextSnapshot(
        session_id=row.session_id,
        context_version=row.context_version,
        status=row.context_status,
        walked_at=row.walked_at,
        source_observed_at=row.source_observed_at,
        captured_at=row.captured_at,
        provider=row.provider,
        precipitation_mm=row.precipitation_mm,
        temperature_c=row.temperature_c,
        humidity_pct=row.humidity_pct,
        sun_elevation_deg=row.sun_elevation_deg,
        failure_reason=row.failure_reason,
    )
    stored_paint = PaintSpec(
        paint_version=row.paint_version,
        grid_version=row.grid_version,
        radius_u=float(row.radius_u),
        profile_name=row.profile_name,
        profile_fp=row.profile_fp,
        sample_step_m=float(row.sample_step_m),
    )
    if stored_paint.fingerprint != row.paint_fp:
        raise IncompleteCapsuleError(
            f"sealed capsule {row.session_id!r} has an invalid paint fingerprint"
        )
    return CapsuleIndex(
        session_id=row.session_id,
        started_at=row.started_at,
        paint_spec=stored_paint,
        context=context,
        capabilities=tuple(ObservationCapability(**item) for item in row.capabilities),
        drift_assessment=DriftAssessment(row.drift_assessment),
    )


async def _count_capsules(db: AsyncSession, dog_id: str) -> int:
    return int((await db.execute(text("""
        SELECT count(*)
        FROM walk_capsule_manifest
        WHERE dog_id = :dog_id
    """), {"dog_id": dog_id})).scalar_one())


async def _load_capsule_index(
    db: AsyncSession,
    selector: WalkSelector,
) -> list[CapsuleIndex]:
    date_predicates = []
    parameters: dict[str, object] = {
        "dog_id": selector.dog_id,
        "row_limit": MAX_INDEX_ROWS + 1,
    }
    if selector.since is not None:
        date_predicates.append(
            "(session.started_at AT TIME ZONE :calendar_timezone)::date >= :since"
        )
        parameters["since"] = selector.since
    if selector.until is not None:
        date_predicates.append(
            "(session.started_at AT TIME ZONE :calendar_timezone)::date <= :until"
        )
        parameters["until"] = selector.until
    if date_predicates:
        parameters["calendar_timezone"] = DIARY_CALENDAR_TIMEZONE
    date_clause = "".join(f" AND {predicate}" for predicate in date_predicates)

    rows = (await db.execute(text(f"""
        SELECT manifest.session_id, manifest.capabilities, session.started_at,
               sheet.paint_version, sheet.grid_version, sheet.radius_u,
               sheet.profile_name, sheet.profile_fp, sheet.sample_step_m, sheet.paint_fp,
               context.context_version, context.status AS context_status,
               context.walked_at, context.source_observed_at, context.captured_at,
               context.provider, context.precipitation_mm, context.temperature_c,
               context.humidity_pct, context.sun_elevation_deg, context.failure_reason,
               receipt.drift_assessment
        FROM walk_capsule_manifest manifest
        JOIN walk_session session ON session.id = manifest.session_id
        LEFT JOIN walk_cellophane_sheet sheet ON sheet.session_id = manifest.session_id
        LEFT JOIN walk_trail_context context ON context.session_id = manifest.session_id
        LEFT JOIN walk_measurement_receipt receipt ON receipt.session_id = manifest.session_id
        WHERE manifest.dog_id = :dog_id
        {date_clause}
        ORDER BY session.started_at, manifest.session_id
        LIMIT :row_limit
    """), parameters)).all()
    if len(rows) > MAX_INDEX_ROWS:
        raise SpatialDiaryViewTooLargeError(
            f"SpatialDiaryView v0 후보 Capsule index는 최대 {MAX_INDEX_ROWS}개다; "
            "기간을 좁혀야 한다"
        )
    return [_index_from_row(row) for row in rows]


async def _load_sheets(
    db: AsyncSession,
    selected: list[CapsuleIndex],
) -> list[Cellophane]:
    if not selected:
        return []
    statement = text("""
        SELECT session_id, q, r, occupancy_s, peak
        FROM walk_cellophane_cell
        WHERE session_id IN :session_ids
        ORDER BY session_id, q, r
        LIMIT :row_limit
    """).bindparams(bindparam("session_ids", expanding=True))
    rows = (await db.execute(
        statement,
        {
            "session_ids": [capsule.session_id for capsule in selected],
            "row_limit": MAX_RAW_CELL_ROWS + 1,
        },
    )).all()
    if len(rows) > MAX_RAW_CELL_ROWS:
        raise SpatialDiaryViewTooLargeError(
            f"SpatialDiaryView v0 원시 cell은 최대 {MAX_RAW_CELL_ROWS}개다"
        )
    cells: dict[str, list] = {capsule.session_id: [] for capsule in selected}
    for row in rows:
        cells[row.session_id].append(row)

    sheets = []
    for capsule in selected:
        spec = capsule.paint_spec
        sheet_cells = cells[capsule.session_id]
        sheets.append(Cellophane(
            walk_id=capsule.session_id,
            at=capsule.started_at,
            radius_u=spec.radius_u,
            profile=spec.profile_name,
            occupancy={(row.q, row.r): float(row.occupancy_s) for row in sheet_cells},
            peak={(row.q, row.r): float(row.peak) for row in sheet_cells},
            paint_version=spec.paint_version,
            grid_version=spec.grid_version,
            profile_fp=spec.profile_fp,
            sample_step_m=spec.sample_step_m,
            paint_fp=spec.fingerprint,
        ))
    return sheets


def _view_layer_spec(metric: str, paint: PaintSpec) -> LayerSpec:
    return LayerSpec(
        selector=Selector(),
        aggregation=Aggregation(metric=metric, min_peak=0.0),
        projection=Projection.from_paint_spec(paint),
    )


async def query_spatial_diary_view(
    db: AsyncSession,
    spec: SpatialDiaryViewSpec,
    *,
    view_as_of: datetime | None = None,
) -> SpatialDiaryViewResult:
    """Spec 하나를 Capsule cohort·공간 field·재현 영수증으로 조립한다."""

    _validate_spec(spec)
    await ensure_repeatable_read_snapshot(db)
    as_of = view_as_of or datetime.now(UTC)
    total_capsules = await _count_capsules(db, spec.walk_selector.dog_id)
    candidate_capsules = await _load_capsule_index(db, spec.walk_selector)
    selected = [
        capsule for capsule in candidate_capsules if _matches(spec.walk_selector, capsule)
    ]
    if len(selected) > MAX_SELECTED_CAPSULES:
        raise SpatialDiaryViewTooLargeError(
            f"SpatialDiaryView v0 선택 Capsule은 최대 {MAX_SELECTED_CAPSULES}개다; "
            "기간 또는 context filter를 좁혀야 한다"
        )
    generations = {capsule.paint_spec.fingerprint for capsule in selected}
    if len(generations) > 1:
        raise MixedPaintGenerationError(
            f"한 view에 paint 세대를 섞을 수 없다: {sorted(generations)}"
        )
    selected_paint = selected[0].paint_spec if selected else _CURRENT_PAINT_SPEC
    sheets = await _load_sheets(db, selected)
    field = spatial_field(sheets, _view_layer_spec(spec.field_metric, selected_paint))
    if len(field.values) > MAX_RESULT_CELLS:
        raise SpatialDiaryViewTooLargeError(
            f"SpatialDiaryView v0 결과 cell은 최대 {MAX_RESULT_CELLS}개다"
        )
    pin_entries = await load_pin_entries(
        db,
        [capsule.session_id for capsule in selected],
    )
    pins = tuple(
        entry
        for entry in pin_entries
        if pin_entry_matches(
            entry,
            spec.entry_selector.subject_roles,
            spec.entry_selector.meaning_codes,
        )
    )
    if len(pins) > MAX_RESULT_PINS:
        raise SpatialDiaryViewTooLargeError(
            f"SpatialDiaryView v0 결과 Pin은 최대 {MAX_RESULT_PINS}개다"
        )

    known = sum(
        _context_is_known(capsule.context, spec.walk_selector) for capsule in selected
    )
    receipt = SpatialDiaryViewReceipt(
        selector_fingerprint=selector_fingerprint(spec),
        view_as_of=as_of,
        total_capsules=total_capsules,
        selected_capsules=len(selected),
        contributing_capsules=field.contributing,
        context_known_count=known,
        context_unknown_count=len(selected) - known,
        pin_count=len(pins),
        paint_fp=selected_paint.fingerprint,
        field_metric=spec.field_metric,
        normalization=field.normalization,
        context_policy_version=CONTEXT_POLICY_VERSION,
        quality_policy_version=QUALITY_POLICY_VERSION,
        claim_policy_version=CLAIM_POLICY_VERSION,
    )
    return SpatialDiaryViewResult(spec=spec, field=field, pins=pins, receipt=receipt)
