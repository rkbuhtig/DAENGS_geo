"""Context provider가 구현해야 하는 최소 port. 실행·재시도·timeout은 조립층 책임이다."""

from typing import Protocol

from app.context_plane.contract import ContextAtom, ContextCapabilityId, ContextRequest


class ContextProvider(Protocol):
    provider_id: str
    capabilities: frozenset[ContextCapabilityId]

    async def resolve(self, request: ContextRequest) -> tuple[ContextAtom, ...]: ...

