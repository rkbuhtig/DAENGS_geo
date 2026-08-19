"""지도 제공사 어댑터 — docs/07-map-provider.md.

백엔드가 제공사를 만지는 곳은 정적 지도 URL 조립과 지오코딩뿐이다. 그래서 딱 3메서드.
타일·렌더링·길찾기는 클라이언트/제공사 앱 몫이므로 여기 없다.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


@dataclass(frozen=True)
class MapMarker:
    pos: LatLng
    label: str = ""          # 한 글자 권장 (A, B, C ...)
    highlight: bool = False


@dataclass(frozen=True)
class StaticMapSpec:
    center: LatLng
    zoom: int = 16
    width: int = 600
    height: int = 300
    markers: tuple[MapMarker, ...] = field(default_factory=tuple)


class MapProvider(Protocol):
    name: str

    def static_map_url(self, spec: StaticMapSpec) -> str | None:
        """정적 지도 이미지 URL. 제공사가 URL 방식 미지원이면 None."""

    async def geocode(self, address: str) -> LatLng | None: ...

    async def reverse_geocode(self, pos: LatLng) -> str | None: ...


class NullProvider:
    """제공사 미설정 시. 지도 없이도 검색 API는 동작해야 한다."""

    name = "none"

    def static_map_url(self, spec: StaticMapSpec) -> str | None:
        return None

    async def geocode(self, address: str) -> LatLng | None:
        return None

    async def reverse_geocode(self, pos: LatLng) -> str | None:
        return None
