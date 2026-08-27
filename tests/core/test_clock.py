"""시각 원천. `FixedClock` 이 정말 고정인지 — 결정론 테스트의 결정론.

**왜 필요한가**: 여러 테스트가 `FixedClock` 을 심어 "같은 입력은 같은 답"을 단언한다.
그 전제가 깨지면 **그 테스트들이 조용히 무의미해진다** — 실패하는 게 아니라 우연히
통과한다. 전제를 여기서 한 번 고정한다 (결정 #67 PR 2 에서 `core.clock` 으로 옮겼다).
"""

from datetime import UTC, datetime

from app.core.clock import FixedClock, SystemClock

AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def test_fixed_clock_returns_the_same_instant_every_call():
    clock = FixedClock(AT)
    assert clock.now() == AT
    assert clock.now() == clock.now()


def test_system_clock_is_timezone_aware_utc():
    """naive datetime 이 나오면 KST 판정과 비교할 때 조용히 9시간 어긋난다."""
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0
