"""원좌표 purge 전 Capsule 자식 조립의 순수 계약. Decisions: #74, #75."""

import math
from datetime import UTC, datetime, timedelta

from app.features.spatial_diary.contract import (
    ContextStatus,
    TrailContextSnapshot,
)
from app.features.walk.capsule import (
    CAPSULE_PROFILE,
    CAPSULE_RADIUS_U,
    TrailContextRequest,
    build_capsule_artifacts,
    capture_trail_context,
    measurement_receipt,
    trail_context_request,
)
from app.features.walk.facts import compute_facts
from tests.conftest import WALK_T0, walk_fix


class BrokenContextProvider:
    name = "broken-weather"

    async def capture(self, request, captured_at):
        raise TimeoutError("fixture timeout")


class WrongWalkContextProvider:
    name = "wrong-walk"

    async def capture(self, request, captured_at):
        return TrailContextSnapshot(
            session_id="another-walk",
            status=ContextStatus.CAPTURED,
            walked_at=request.walked_at,
            captured_at=captured_at,
            provider=self.name,
            temperature_c=18,
        )


def _computed():
    fixes = [
        walk_fix(0, 0, accuracy=10),
        walk_fix(5, 7, accuracy=80),
        walk_fix(10, 14, accuracy=None),
        walk_fix(15, 21, accuracy=20),
    ]
    return fixes, compute_facts(
        "walk-capsule-1",
        "dog-1",
        WALK_T0,
        WALK_T0 + timedelta(seconds=20),
        fixes,
    )


def test_receipt_preserves_raw_denominators_and_both_accuracy_distributions():
    _, computed = _computed()
    receipt = measurement_receipt(
        computed.facts, computed.trail, computed.receipt_input
    )

    assert (receipt.received_fix_count, receipt.accepted_fix_count) == (4, 3)
    assert receipt.rejected_low_accuracy_count == 1
    assert receipt.unknown_accuracy_count == 1
    assert receipt.session_wall_time_s == 20
    assert receipt.canonical_segment_time_s == 5
    assert receipt.reported_accuracy_count == 3
    assert (receipt.reported_accuracy_p50_m, receipt.reported_accuracy_p90_m) == (20, 68)
    assert receipt.accepted_accuracy_count == 2
    assert (receipt.accepted_accuracy_p50_m, receipt.accepted_accuracy_p90_m) == (15, 19)


def test_capsule_builds_the_adopted_macro_generation_and_seals_capabilities():
    _, computed = _computed()
    request = trail_context_request(computed.facts, computed.trail)
    captured_at = computed.facts.ended_at + timedelta(seconds=1)
    context = TrailContextSnapshot(
        session_id=request.session_id,
        status=ContextStatus.UNKNOWN,
        walked_at=request.walked_at,
        captured_at=captured_at,
    )
    capsule = build_capsule_artifacts(
        computed.facts,
        computed.trail,
        computed.receipt_input,
        context,
        sealed_at=captured_at + timedelta(seconds=1),
    )

    assert capsule.cellophane.radius_u == CAPSULE_RADIUS_U
    assert capsule.cellophane.profile == CAPSULE_PROFILE.name
    assert math.fsum(capsule.cellophane.occupancy.values()) == 5
    assert {item.name for item in capsule.manifest.capabilities} == {"low_motion", "gap"}
    assert capsule.manifest.session_id == computed.facts.session_id


def test_context_request_uses_walk_midpoint_and_nearest_accepted_fix():
    _, computed = _computed()
    request = trail_context_request(computed.facts, computed.trail)

    assert request.walked_at == WALK_T0 + timedelta(seconds=10)
    nearest = walk_fix(10, 14, accuracy=None)
    assert (request.lat, request.lng) == (nearest.lat, nearest.lng)


async def test_context_provider_failure_becomes_a_failed_snapshot_not_an_exception():
    request = TrailContextRequest("walk-1", WALK_T0, 37.5, 127.0)
    captured_at = datetime(2026, 9, 1, 12, tzinfo=UTC)
    snapshot = await capture_trail_context(BrokenContextProvider(), request, captured_at)

    assert snapshot.status is ContextStatus.FAILED
    assert snapshot.provider == "broken-weather"
    assert snapshot.failure_reason == "provider_error:TimeoutError"


async def test_context_for_a_different_walk_is_failed_closed():
    request = TrailContextRequest("walk-1", WALK_T0, 37.5, 127.0)
    snapshot = await capture_trail_context(
        WrongWalkContextProvider(),
        request,
        datetime(2026, 9, 1, 12, tzinfo=UTC),
    )

    assert snapshot.status is ContextStatus.FAILED
    assert snapshot.failure_reason == "provider_error:ValueError"
