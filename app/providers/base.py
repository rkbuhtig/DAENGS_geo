"""지도 제공사 어댑터 — docs/explorations/map-provider/, transport-snapshot.md

백엔드가 제공사를 만지는 곳: 정적 지도 URL · 지오코딩 · 경로. 그래서 4메서드.
타일·렌더링·턴바이턴 안내는 클라이언트/제공사 앱 몫이므로 여기 없다.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Mode = Literal["walk", "car", "transit"]
WalkOption = Literal["recommended", "main_road", "shortest", "no_stairs"]


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


@dataclass(frozen=True)
class MapMarker:
    pos: LatLng
    label: str = ""
    highlight: bool = False


@dataclass(frozen=True)
class StaticMapSpec:
    center: LatLng
    zoom: int = 16
    width: int = 600
    height: int = 300
    markers: tuple[MapMarker, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Facilities:
    """도보 경로 위 시설 집계. TMAP facilityType/turnType에서 센다."""

    crosswalk: int = 0
    stairs: int = 0
    underpass: int = 0
    overpass: int = 0
    elevator: int = 0
    slope: int = 0


@dataclass(frozen=True)
class RouteResult:
    mode: Mode
    distance_m: int
    duration_s: int
    source: str                              # "estimate" | "tmap" | "naver" | ...
    polyline: tuple[LatLng, ...] = ()
    facilities: Facilities | None = None      # walk만
    taxi_fare: int | None = None              # car만
    fare: int | None = None                   # transit만
    option: WalkOption | None = None


class MapProvider(Protocol):
    name: str

    def static_map_url(self, spec: StaticMapSpec) -> str | None: ...
    async def geocode(self, address: str) -> LatLng | None: ...
    async def reverse_geocode(self, pos: LatLng) -> str | None: ...
    async def route(self, mode: Mode, origin: LatLng, dest: LatLng,
                    option: WalkOption = "recommended") -> RouteResult | None: ...


class NullProvider:
    """제공사 미설정. 지도·경로 없이도 검색은 동작해야 한다."""

    name = "none"

    def static_map_url(self, spec: StaticMapSpec) -> str | None:
        return None

    async def geocode(self, address: str) -> LatLng | None:
        return None

    async def reverse_geocode(self, pos: LatLng) -> str | None:
        return None

    async def route(self, mode: Mode, origin: LatLng, dest: LatLng,
                    option: WalkOption = "recommended") -> RouteResult | None:
        return None
