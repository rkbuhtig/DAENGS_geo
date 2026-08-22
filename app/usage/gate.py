"""모든 실제 외부 호출이 통과하는 단일 허용·요청 한도·사용량 Gate."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.usage.ledger import UsageLedger
from app.usage.models import MeteredOperation, UsageDenied, UsageIntent, UsagePermit
from app.usage.policy import UsagePolicy


@dataclass
class _RequestUsage:
    units: dict[MeteredOperation, int] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_request_usage: ContextVar[_RequestUsage | None] = ContextVar("request_usage", default=None)


@asynccontextmanager
async def usage_request_scope() -> AsyncIterator[None]:
    """HTTP 요청 하나의 사용량을 묶는다. 비HTTP 호출도 같은 경계를 쓰려면 명시적으로 연다."""
    token = _request_usage.set(_RequestUsage())
    try:
        yield
    finally:
        _request_usage.reset(token)


class UsageGate:
    def __init__(self, policy: UsagePolicy, ledger: UsageLedger):
        self._policy = policy
        self._ledger = ledger

    async def check(self, intent: UsageIntent) -> UsagePermit:
        """허용 여부와 요청 단위 한도를 먼저 고정한다. 캐시 hit도 이 검사는 통과한다."""
        permit = await self._policy.decide(intent)
        if not permit.allowed:
            raise UsageDenied("policy_denied", permit.reason)

        limit = permit.max_units_per_request
        if limit is None:
            return permit
        scope = _request_usage.get()
        if scope is None:
            raise UsageDenied(
                "request_scope_missing",
                "metered usage requires an explicit request scope",
            )
        async with scope.lock:
            used = scope.units.get(intent.operation, 0)
            if used + intent.units > limit:
                raise UsageDenied(
                    "request_limit",
                    f"{intent.operation.value} request limit exceeded",
                )
            scope.units[intent.operation] = used + intent.units
        return permit

    async def consume(self, intent: UsageIntent, permit: UsagePermit) -> None:
        """캐시 miss에서 실제 provider 호출 직전에 예약한다. 실패해도 환불하지 않는다."""
        if permit.window is None:
            return
        if not await self._ledger.reserve(permit.window, intent.units):
            raise UsageDenied(
                "usage_limit",
                f"{intent.operation.value} usage limit exceeded",
                retry_after_s=permit.window.seconds,
            )
