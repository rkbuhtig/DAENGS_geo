"""`UsageDenied` → HTTP 번역. **네 코드가 세 상태로 갈리는 지점.**

**왜 필요한가**: `test_usage_gate.py` 가 403·429 를 HTTP 로 관통해 확인하지만, 그건 게이트가
그 코드를 낼 때의 경로다. 여기서 보는 것은 번역표 자체다 — 특히 아무도 안 밟던 두 가지:

    request_scope_missing → 503     서버가 스코프를 안 열고 provider 를 부른 **우리 잘못**이다.
                                    4xx 로 내보내면 클라이언트가 자기 요청을 고치려 든다.
    Retry-After                      429 에 언제 다시 오라는 말이 없으면 즉시 재시도가 돈다.

`retry_after_s` 를 실제로 채우는 곳은 `gate.py` 의 창 만료 하나뿐이라(`permit.window.seconds`),
그 값이 헤더까지 살아 나가는지는 이 파일이 유일하게 본다.
"""

import pytest

from app.usage.http import usage_http_exception
from app.usage.models import UsageDenied


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("policy_denied", 403),          # 정책이 금지 — 클라이언트가 고칠 수 없다
        ("request_limit", 429),          # 요청당 상한
        ("usage_limit", 429),            # 누적 상한
        ("request_scope_missing", 503),  # **우리 잘못.** 4xx 면 클라이언트가 자기를 의심한다
    ],
)
def test_each_denial_code_maps_to_its_status(code: str, status: int) -> None:
    exc = usage_http_exception(UsageDenied(code, "reason"))
    assert exc.status_code == status


def test_detail_carries_code_and_message_not_a_bare_string():
    """`detail` 이 문자열이면 클라이언트가 사유를 파싱해야 한다. 코드로 분기하게 둔다."""
    exc = usage_http_exception(UsageDenied("usage_limit", "하루 한도 초과"))
    assert exc.detail == {"code": "usage_limit", "message": "하루 한도 초과"}


def test_retry_after_header_appears_only_when_the_window_is_known():
    """창 만료 시각을 아는 거부만 헤더를 단다. 모르면서 다는 것이 더 나쁘다."""
    with_window = usage_http_exception(UsageDenied("usage_limit", "r", retry_after_s=3600))
    assert with_window.headers == {"Retry-After": "3600"}

    without = usage_http_exception(UsageDenied("policy_denied", "r"))
    assert without.headers is None


def test_unknown_code_degrades_to_503_not_500():
    """`DenialCode` 에 값이 늘어도 스택트레이스가 아니라 503 이 나간다."""
    exc = usage_http_exception(UsageDenied("brand_new_code", "r"))  # type: ignore[arg-type]
    assert exc.status_code == 503
