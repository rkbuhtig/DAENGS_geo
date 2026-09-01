"""산책 finalize 중 원좌표가 살아 있을 때 만드는 Walk Capsule 자식들. Decision: #75.

DB를 모르는 순수 조립층이다. 외부 문맥 호출만 Protocol 뒤에 두고, 실패를 값으로 바꾸는
함수도 여기 둔다. 저장과 raw purge의 원자성은 `walk.store.finalize`가 담당한다.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.features.spatial_diary.contract import (
    ContextStatus,
    MeasurementReceipt,
    ObservationCapability,
    TrailContextSnapshot,
    WalkCapsuleManifest,
)
from app.features.walk.facts import ComputedFacts
from app.features.walk.models import WalkFix
from app.features.walk.observation import MICRO_OBSERVATION_VERSION
from app.features.walk.paint import NARROW_STEP, Cellophane, paint_sheet

# 결정 #75의 첫 영구 저장 세대. 4u보다 약 4배 작은 payload이고 12u보다 경계 손실이 작았던
# 8u를 택한다. 이것은 drift 보정값이 아니며 바뀌면 옛 장을 다시 칠하지 않고 새 세대가 된다.
CAPSULE_RADIUS_U = 8.0
CAPSULE_PROFILE = NARROW_STEP


@dataclass(frozen=True)
class TrailContextRequest:
    session_id: str
    walked_at: datetime
    lat: float | None
    lng: float | None


class TrailContextProvider(Protocol):
    """과거 시각·대표 위치의 동적 환경 원자를 가져오는 선택적 외부 경계."""

    name: str

    async def capture(
        self,
        request: TrailContextRequest,
        captured_at: datetime,
    ) -> TrailContextSnapshot: ...


class UnknownTrailContextProvider:
    """제공자가 아직 조립되지 않은 기본값. unknown을 dry/clear로 위장하지 않는다."""

    name = "none"

    async def capture(
        self,
        request: TrailContextRequest,
        captured_at: datetime,
    ) -> TrailContextSnapshot:
        return TrailContextSnapshot(
            session_id=request.session_id,
            status=ContextStatus.UNKNOWN,
            walked_at=request.walked_at,
            captured_at=captured_at,
        )


@dataclass(frozen=True)
class CapsuleArtifacts:
    cellophane: Cellophane
    measurement_receipt: MeasurementReceipt
    trail_context: TrailContextSnapshot
    manifest: WalkCapsuleManifest

    def __post_init__(self) -> None:
        session_ids = {
            self.cellophane.walk_id,
            self.measurement_receipt.session_id,
            self.trail_context.session_id,
            self.manifest.session_id,
        }
        if len(session_ids) != 1:
            raise ValueError("all capsule artifacts must belong to one session")
        if self.manifest.sealed_at < self.trail_context.captured_at:
            raise ValueError("capsule cannot be sealed before context capture")


def trail_context_request(computed: ComputedFacts) -> TrailContextRequest:
    """산책 중간 시각과 그 시각에 가까운 수용 fix를 외부 문맥 조회 기준으로 쓴다."""

    facts = computed.facts
    walked_at = facts.started_at + (facts.ended_at - facts.started_at) / 2
    if not computed.accepted_fixes:
        return TrailContextRequest(facts.session_id, walked_at, None, None)
    point = min(
        computed.accepted_fixes,
        key=lambda fix: abs((fix.at - walked_at).total_seconds()),
    )
    return TrailContextRequest(facts.session_id, walked_at, point.lat, point.lng)


async def capture_trail_context(
    provider: TrailContextProvider,
    request: TrailContextRequest,
    captured_at: datetime,
) -> TrailContextSnapshot:
    """외부 실패·잘못된 귀속을 Capsule finalize 실패로 전파하지 않고 failed 값으로 만든다."""

    try:
        snapshot = await provider.capture(request, captured_at)
        if snapshot.session_id != request.session_id or snapshot.walked_at != request.walked_at:
            raise ValueError("provider returned context for a different walk")
        return snapshot
    except Exception as exc:  # noqa: BLE001 - 외부 adapter 실패를 frozen 상태로 바꾸는 경계
        provider_name = str(getattr(provider, "name", type(provider).__name__))[:64] or None
        return TrailContextSnapshot(
            session_id=request.session_id,
            status=ContextStatus.FAILED,
            walked_at=request.walked_at,
            captured_at=captured_at,
            provider=provider_name,
            failure_reason=f"provider_error:{type(exc).__name__}"[:256],
        )


def _percentile(ordered: list[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _accuracy_summary(fixes: list[WalkFix]) -> tuple[int, float | None, float | None]:
    values = sorted(float(fix.accuracy_m) for fix in fixes if fix.accuracy_m is not None)
    if not values:
        return 0, None, None
    return len(values), round(_percentile(values, 0.50), 2), round(_percentile(values, 0.90), 2)


def measurement_receipt(computed: ComputedFacts, received_fixes: list[WalkFix]) -> MeasurementReceipt:
    """FixQuality와 transient fix 열을 이름 붙은 원시 분자·분모로 동결한다."""

    facts = computed.facts
    quality = computed.quality
    reported_count, reported_p50, reported_p90 = _accuracy_summary(received_fixes)
    accepted_count, accepted_p50, accepted_p90 = _accuracy_summary(computed.accepted_fixes)
    return MeasurementReceipt(
        session_id=facts.session_id,
        evidence_origin=facts.evidence_origin,
        received_fix_count=quality.received,
        accepted_fix_count=quality.accepted,
        rejected_low_accuracy_count=quality.rejected_low_accuracy,
        rejected_out_of_order_count=quality.rejected_out_of_order,
        rejected_before_start_count=quality.rejected_before_start,
        rejected_after_end_count=quality.rejected_after_end,
        unknown_accuracy_count=quality.unknown_accuracy,
        jump_break_count=quality.jump_breaks,
        gap_break_count=quality.gap_breaks,
        explicit_break_count=quality.explicit_breaks,
        dropped_at_capacity_count=quality.dropped_at_capacity,
        mock_fix_count=quality.mock_fixes,
        session_wall_time_s=(facts.ended_at - facts.started_at).total_seconds(),
        canonical_segment_time_s=math.fsum(segment.dt for segment in computed.segments),
        gap_elapsed_s=math.fsum(gap.dt for gap in computed.gaps),
        reported_accuracy_count=reported_count,
        reported_accuracy_p50_m=reported_p50,
        reported_accuracy_p90_m=reported_p90,
        accepted_accuracy_count=accepted_count,
        accepted_accuracy_p50_m=accepted_p50,
        accepted_accuracy_p90_m=accepted_p90,
    )


def build_capsule_artifacts(
    computed: ComputedFacts,
    received_fixes: list[WalkFix],
    context: TrailContextSnapshot,
    sealed_at: datetime,
) -> CapsuleArtifacts:
    """Macro·receipt·context가 준비된 뒤 마지막에 manifest를 만든다."""

    facts = computed.facts
    sheet = paint_sheet(
        facts.session_id,
        facts.started_at,
        computed.segments,
        CAPSULE_RADIUS_U,
        CAPSULE_PROFILE,
    )
    receipt = measurement_receipt(computed, received_fixes)
    capabilities = (
        ObservationCapability(name="low_motion", generation=MICRO_OBSERVATION_VERSION),
        ObservationCapability(name="gap", generation=MICRO_OBSERVATION_VERSION),
    )
    manifest = WalkCapsuleManifest(
        session_id=facts.session_id,
        dog_id=facts.dog_id,
        walk_record_version=facts.record_version,
        walk_calculation_version=facts.calculation_version,
        capabilities=capabilities,
        sealed_at=sealed_at.astimezone(UTC),
    )
    return CapsuleArtifacts(sheet, receipt, context, manifest)


def utc_now() -> datetime:
    """API 기본 시계."""

    return datetime.now(UTC)
