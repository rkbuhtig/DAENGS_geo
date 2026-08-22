"""실제 provider를 Usage Gate 뒤에 가두는 어댑터."""

import time
from typing import Protocol

from app.providers.base import (
    LatLng,
    MapProvider,
    Mode,
    RouteResult,
    StaticMapSpec,
    WalkOption,
)
from app.usage.gate import UsageGate
from app.usage.models import MeasuredRouteIntent, StaticMapIntent

_ROUTE_TTL = {"walk": 6 * 3600, "car": 600, "transit": 1800}
_ROUTE_CACHE_MAX = 5000


class StaticMapFetcher(Protocol):
    async def fetch_static_png(self, spec: StaticMapSpec) -> bytes: ...


class MeteredStaticMapFetcher:
    def __init__(self, inner: StaticMapFetcher, gate: UsageGate):
        self._inner = inner
        self._gate = gate

    async def fetch_static_png(self, spec: StaticMapSpec) -> bytes:
        intent = StaticMapIntent(
            width=spec.width,
            height=spec.height,
            marker_count=len(spec.markers),
        )
        permit = await self._gate.check(intent)
        await self._gate.consume(intent, permit)
        return await self._inner.fetch_static_png(spec)


class MeteredRouteProvider:
    """인가를 캐시보다 먼저 확인하고, cache miss만 누적 사용량으로 소비한다."""

    def __init__(self, inner: MapProvider, gate: UsageGate):
        self._inner = inner
        self._gate = gate
        self.name = inner.name
        self.route_modes = inner.route_modes
        self._cache: dict[tuple, tuple[float, RouteResult]] = {}

    def static_map_url(self, spec: StaticMapSpec) -> str | None:
        return self._inner.static_map_url(spec)

    async def geocode(self, address: str) -> LatLng | None:
        return await self._inner.geocode(address)

    async def reverse_geocode(self, pos: LatLng) -> str | None:
        return await self._inner.reverse_geocode(pos)

    async def route(
        self,
        mode: Mode,
        origin: LatLng,
        dest: LatLng,
        option: WalkOption = "recommended",
    ) -> RouteResult | None:
        intent = MeasuredRouteIntent(mode=mode, option=option)
        permit = await self._gate.check(intent)

        key = self._cache_key(mode, origin, dest, option)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < _ROUTE_TTL[mode]:
            return hit[1]

        await self._gate.consume(intent, permit)
        result = await self._inner.route(mode, origin, dest, option)
        if result is not None:
            if len(self._cache) >= _ROUTE_CACHE_MAX:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic(), result)
        return result

    def cache_size(self) -> int:
        return len(self._cache)

    @staticmethod
    def _cache_key(mode: Mode, origin: LatLng, dest: LatLng, option: WalkOption) -> tuple:
        return (
            mode,
            round(origin.lat, 4),
            round(origin.lng, 4),
            round(dest.lat, 4),
            round(dest.lng, 4),
            option if mode == "walk" else "",
        )
