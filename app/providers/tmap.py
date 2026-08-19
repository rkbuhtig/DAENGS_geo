"""TMAP 보행자 경로 (SK오픈API). research/2026-08-19-route-apis.md

searchOption: 0 추천 · 4 추천+대로우선 · 10 최단 · 30 최단거리+계단제외
facilityType(구간): 12 육교 · 14 지하보도 · 15 횡단보도 · 18 지하철지하보도
turnType(포인트): 125 육교 · 126 지하보도 · 127 계단 · 128 경사로 · 129 계단+경사로 · 211~217 횡단보도 · 218 엘리베이터
totalDistance/totalTime은 첫 Feature properties에만.

미검증 — 키 받고 실호출로 확인할 것.
"""

import httpx

from app.providers.base import Facilities, LatLng, Mode, RouteResult, StaticMapSpec, WalkOption

URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
OPTION = {"recommended": 0, "main_road": 4, "shortest": 10, "no_stairs": 30}


class TmapProvider:
    name = "tmap"

    def __init__(self, app_key: str, client: httpx.AsyncClient | None = None):
        self._headers = {"appKey": app_key, "Content-Type": "application/json"}
        self._client = client or httpx.AsyncClient(timeout=8.0)

    def static_map_url(self, spec: StaticMapSpec) -> str | None:
        return None

    async def geocode(self, address: str) -> LatLng | None:
        return None

    async def reverse_geocode(self, pos: LatLng) -> str | None:
        return None

    async def route(self, mode: Mode, origin: LatLng, dest: LatLng,
                    option: WalkOption = "recommended") -> RouteResult | None:
        if mode != "walk":
            return None
        body = {
            "startX": origin.lng, "startY": origin.lat,
            "endX": dest.lng, "endY": dest.lat,
            "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
            "startName": "출발", "endName": "도착",
            "searchOption": OPTION[option],
        }
        r = await self._client.post(URL, json=body, headers=self._headers, params={"version": 1})
        r.raise_for_status()
        return parse_tmap(r.json(), option)


def parse_tmap(data: dict, option: WalkOption) -> RouteResult:
    feats = data.get("features") or []
    total_d = total_t = 0
    cross = stairs = under = over = elev = slope = 0
    pts: list[LatLng] = []
    for f in feats:
        p = f.get("properties", {})
        g = f.get("geometry", {})
        if "totalDistance" in p:
            total_d, total_t = int(p["totalDistance"]), int(p["totalTime"])
        tt = p.get("turnType")
        if tt in (211, 212, 213, 214, 215, 216, 217):
            cross += 1
        elif tt == 125:
            over += 1
        elif tt == 126:
            under += 1
        elif tt in (127, 129):
            stairs += 1
        elif tt == 128:
            slope += 1
        elif tt == 218:
            elev += 1
        if g.get("type") == "LineString":
            for x, y in g.get("coordinates", []):
                pts.append(LatLng(lat=y, lng=x))
    return RouteResult(
        mode="walk", distance_m=total_d, duration_s=total_t, source="tmap",
        polyline=tuple(pts),
        facilities=Facilities(crosswalk=cross, stairs=stairs, underpass=under,
                              overpass=over, elevator=elev, slope=slope),
        option=option,
    )
