"""결정론 가짜 제공사. 키 없이 끝까지 돌리기 위한 것.

경로 = 직선 × 우회계수 ÷ 속도. 시설은 거리·좌표에서 규칙으로 흉내낸다 (테스트 가능하게 결정론).
"""

import math

from app.providers.base import Facilities, LatLng, Mode, RouteResult, StaticMapSpec, WalkOption

DETOUR = {"walk": 1.3, "car": 1.4, "transit": 1.5}
SPEED_MPS = {"walk": 1.0, "car": 5.5, "transit": 4.0}   # 도보 3.6km/h(횡단 대기 포함), 차 도심 20km/h


def haversine_m(a: LatLng, b: LatLng) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class FakeProvider:
    name = "fake"

    def static_map_url(self, spec: StaticMapSpec) -> str | None:
        return None

    async def geocode(self, address: str) -> LatLng | None:
        return None

    async def reverse_geocode(self, pos: LatLng) -> str | None:
        return None

    async def route(self, mode: Mode, origin: LatLng, dest: LatLng,
                    option: WalkOption = "recommended") -> RouteResult | None:
        straight = haversine_m(origin, dest)
        dist = straight * DETOUR[mode]
        dur = dist / SPEED_MPS[mode]
        fac = None
        taxi = None
        fare = None
        if mode == "walk":
            # 규칙: 400m마다 횡단보도 1, 1km 넘으면 지하도 1, 1.5km 넘으면 계단 1 (no_stairs면 0, 대신 +8% 거리)
            crosswalk = max(1, int(dist // 400))
            underpass = 1 if dist > 1000 else 0
            stairs = 1 if dist > 1500 else 0
            if option == "no_stairs" and stairs:
                stairs = 0
                dist *= 1.08
                dur = dist / SPEED_MPS[mode]
            ratio = 0.7 if option == "main_road" else 0.4
            if option == "main_road":
                dist *= 1.05; dur = dist / SPEED_MPS[mode]
            fac = Facilities(crosswalk=crosswalk, stairs=stairs, underpass=underpass, underpass_m=80 * underpass,
                             big_road_m=int(dist * ratio), total_m=int(dist), big_road_ratio=ratio,
                             big_crossings=max(0, crosswalk - 1) if ratio > 0.5 else 1 if crosswalk else 0)
        elif mode == "car":
            taxi = 4800 + max(0, int((dist - 1600) / 131)) * 100   # 서울 기본요금 근사
        elif mode == "transit":
            fare = 1500
        return RouteResult(
            mode=mode, distance_m=int(dist), duration_s=int(dur), source="estimate",
            polyline=(origin, dest), facilities=fac, taxi_fare=taxi, fare=fare,
            option=option if mode == "walk" else None,
        )
