"""DB 저장 테스트가 공통으로 쓰는 결정론적 Capsule 조립 장치."""

from datetime import timedelta

from app.features.spatial_diary.contract import ContextStatus, TrailContextSnapshot
from app.features.walk.capsule import (
    CapsuleArtifacts,
    build_capsule_artifacts,
    trail_context_request,
)
from app.features.walk.facts import CanonicalWalkComputation


def capsule_for(computed: CanonicalWalkComputation) -> CapsuleArtifacts:
    request = trail_context_request(computed.facts, computed.trail)
    captured_at = computed.facts.ended_at + timedelta(seconds=1)
    context = TrailContextSnapshot(
        session_id=request.session_id,
        status=ContextStatus.UNKNOWN,
        walked_at=request.walked_at,
        captured_at=captured_at,
    )
    return build_capsule_artifacts(
        computed.facts,
        computed.trail,
        computed.receipt_input,
        context,
        sealed_at=captured_at + timedelta(seconds=1),
    )
