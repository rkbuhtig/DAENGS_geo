"""봉인된 Walk Capsule을 조건별 Cellophane field로 다시 읽는다. Decision: #76.

v0는 배경 cohort만 만든다. 기간·강수·낮/밤으로 산책을 고르고 visit_rate 또는
walk_utilization을 계산한다. Pin overlay와 quality 판정은 아직 만들지 않으며, 지원하지 않는
요청을 무시한 채 빈 결과로 바꾸지 않는다.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.spatial_diary.contract import (
    ContextStatus,
    EntrySelector,
    SpatialDiaryViewReceipt,
    SpatialDiaryViewSpec,
    TrailContextSnapshot,
    WalkSelector,
)
from app.features.territory.layers import Aggregation, LayerSpec, Projection, Selector
from app.features.territory.paint import Cellophane, PaintSpec, paint_spec
from app.features.territory.spatial_stats import SpatialField, spatial_field
from app.features.walk.capsule import CAPSULE_PROFILE, CAPSULE_RADIUS_U

CONTEXT_POLICY_VERSION = 1
QUALITY_POLICY_VERSION = 1
CLAIM_POLICY_VERSION = 1
QUALITY_POLICY_NAME = "diary_v1"
DIARY_CALENDAR_TIMEZONE = "Asia/Seoul"
RAIN_THRESHOLD_MM = 0.1

SUPPORTED_METRICS = frozenset({"visit_rate", "walk_utilization"})
FACET_VALUES = {
    "precipitation": frozenset({"rain", "dry", "unknown"}),
    "daylight": frozenset({"day", "night", "unknown"}),
}

_DIARY_ZONE = ZoneInfo(DIARY_CALENDAR_TIMEZONE)
_CURRENT_PAINT_SPEC = paint_spec(CAPSULE_RADIUS_U, CAPSULE_PROFILE)


class UnsupportedSpatialDiaryViewError(ValueError):
    pass


class MixedPaintGenerationError(ValueError):
    pass


class IncompleteCapsuleError(RuntimeError):
    pass


@dataclass(frozen=True)
class CapsuleIndex:
    """셀 payload를 읽기 전에 cohort를 고르는 작은 Capsule 색인 행."""

    session_id: str
    started_at: datetime
    paint_spec: PaintSpec
    context: TrailContextSnapshot


@dataclass(frozen=True)
class SpatialDiaryViewResult:
    spec: SpatialDiaryViewSpec
    field: SpatialField
    receipt: SpatialDiaryViewReceipt


def context_facets(snapshot: TrailContextSnapshot) -> dict[str, str]:
    """동결 원자에서 v1 필터 facet을 만든다. 없는 값은 반대 상태가 아니라 unknown이다."""

    observed = snapshot.status in {ContextStatus.CAPTURED, ContextStatus.PARTIAL}
    if not observed:
        return {"precipitation": "unknown", "daylight": "unknown"}

    precipitation = (
        "unknown"
        if snapshot.precipitation_mm is None
        else "rain"
        if snapshot.precipitation_mm >= RAIN_THRESHOLD_MM
        else "dry"
    )
    daylight = (
        "unknown"
        if snapshot.sun_elevation_deg is None
        else "day"
        if snapshot.sun_elevation_deg >= 0
        else "night"
    )
    return {"precipitation": precipitation, "daylight": daylight}


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
    if spec.entry_selector != EntrySelector():
        raise UnsupportedSpatialDiaryViewError("SpatialDiaryView v0는 Pin entry filter를 지원하지 않는다")
    if (
        spec.quality_policy.policy_version != QUALITY_POLICY_VERSION
        or spec.quality_policy.name != QUALITY_POLICY_NAME
    ):
        raise UnsupportedSpatialDiaryViewError(
            f"SpatialDiaryView v0 quality policy는 {QUALITY_POLICY_NAME} v{QUALITY_POLICY_VERSION}이다"
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


def _context_is_known(snapshot: TrailContextSnapshot) -> bool:
    return snapshot.status in {ContextStatus.CAPTURED, ContextStatus.PARTIAL}


def _index_from_row(row) -> CapsuleIndex:
    if row.paint_version is None or row.context_version is None or row.started_at is None:
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
    )


async def _load_capsule_index(db: AsyncSession, dog_id: str) -> list[CapsuleIndex]:
    rows = (await db.execute(text("""
        SELECT manifest.session_id, session.started_at,
               sheet.paint_version, sheet.grid_version, sheet.radius_u,
               sheet.profile_name, sheet.profile_fp, sheet.sample_step_m, sheet.paint_fp,
               context.context_version, context.status AS context_status,
               context.walked_at, context.source_observed_at, context.captured_at,
               context.provider, context.precipitation_mm, context.temperature_c,
               context.humidity_pct, context.sun_elevation_deg, context.failure_reason
        FROM walk_capsule_manifest manifest
        JOIN walk_session session ON session.id = manifest.session_id
        LEFT JOIN walk_cellophane_sheet sheet ON sheet.session_id = manifest.session_id
        LEFT JOIN walk_trail_context context ON context.session_id = manifest.session_id
        WHERE manifest.dog_id = :dog_id
        ORDER BY session.started_at, manifest.session_id
    """), {"dog_id": dog_id})).all()
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
    """).bindparams(bindparam("session_ids", expanding=True))
    rows = (await db.execute(
        statement,
        {"session_ids": [capsule.session_id for capsule in selected]},
    )).all()
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
    all_capsules = await _load_capsule_index(db, spec.walk_selector.dog_id)
    selected = [
        capsule for capsule in all_capsules if _matches(spec.walk_selector, capsule)
    ]
    generations = {capsule.paint_spec.fingerprint for capsule in selected}
    if len(generations) > 1:
        raise MixedPaintGenerationError(
            f"한 view에 paint 세대를 섞을 수 없다: {sorted(generations)}"
        )
    selected_paint = selected[0].paint_spec if selected else _CURRENT_PAINT_SPEC
    sheets = await _load_sheets(db, selected)
    field = spatial_field(sheets, _view_layer_spec(spec.field_metric, selected_paint))

    known = sum(_context_is_known(capsule.context) for capsule in selected)
    receipt = SpatialDiaryViewReceipt(
        selector_fingerprint=selector_fingerprint(spec),
        view_as_of=view_as_of or datetime.now(UTC),
        total_capsules=len(all_capsules),
        selected_capsules=len(selected),
        contributing_capsules=field.contributing,
        context_known_count=known,
        context_unknown_count=len(selected) - known,
        pin_count=0,
        paint_fp=selected_paint.fingerprint,
        field_metric=spec.field_metric,
        normalization=field.normalization,
        context_policy_version=CONTEXT_POLICY_VERSION,
        quality_policy_version=QUALITY_POLICY_VERSION,
        claim_policy_version=CLAIM_POLICY_VERSION,
    )
    return SpatialDiaryViewResult(spec=spec, field=field, receipt=receipt)
