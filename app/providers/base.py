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
    """도보 경로 위 시설 집계.

    실측(2026-08-19, 강남역→논현): 횡단보도는 포인트 turnType 211~217, 지하보도/육교는 LineString facilityType
    14/18/12 '구간'으로 온다 (연속 구간 = 통로 하나로 합쳐 센다). 계단/경사로/엘리베이터는 포인트 127/129/128/218.
    """

    crosswalk: int = 0
    stairs: int = 0
    underpass: int = 0        # 통로 수 (연속 구간 병합, 출발 통로 제외)
    underpass_m: int = 0      # 지하 구간 총 길이 (출발 통로 제외)
    origin_passage_m: int = 0 # 출발 직후 짧은 지하 통로(역 출구 등). 장애물로 안 센다
    overpass: int = 0
    elevator: int = 0
    slope: int = 0

    def penalty(self, avoid: tuple[str, ...] = ()) -> int:
        """비교용 점수. 낮을수록 좋다. avoid에 든 시설은 가중."""
        w = {"stairs": 3, "underpass": 1, "overpass": 2, "crosswalk": 0.3}
        for a in avoid:
            if a in w: w[a] *= 4
        return int(self.stairs * w["stairs"] + self.underpass * w["underpass"]
                   + self.overpass * w["overpass"] + self.crosswalk * w["crosswalk"])


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
