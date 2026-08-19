"""TMAP 보행자 경로 (SK오픈API). research/2026-08-19-route-apis.md

searchOption: 0 추천 · 4 추천+대로우선 · 10 최단 · 30 최단거리+계단제외
facilityType(구간): 12 육교 · 14 지하보도 · 15 횡단보도 · 18 지하철지하보도 · (17: 문서 없음, 일반 인도로 취급)
turnType(포인트): 125 육교 · 126 지하보도 · 127 계단 · 128 경사로 · 129 계단+경사로 · 211~217 횡단보도 · 218 엘리베이터
totalDistance/totalTime은 첫 Feature properties에만.

실측(2026-08-19): 지하보도는 turnType 126이 아니라 LineString facilityType 14 구간으로 왔음. 도보 속도 ~4.4km/h(낙관적).
계단제외(30)는 거리·시간이 늘고 지하보도 구간이 많아진다 — 옵션 간 트레이드오프를 응답에 실을 것.
"""

import httpx

from app.providers.base import Facilities, LatLng, Mode, RouteResult, StaticMapSpec, WalkOption

URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
OPTION = {"recommended": 0, "main_road": 4, "shortest": 10, "no_stairs": 30}
ORIGIN_PASSAGE_WITHIN_M = 150   # 이 안에서 시작하고
ORIGIN_PASSAGE_MAX_M = 120      # 이보다 짧은 지하 구간은 출발 통로(역 출구 등)로 본다


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
    cross = stairs = elev = slope = 0
    pts: list[LatLng] = []
    # 구간(LineString) 시설은 연속 run으로 병합해서 센다
    runs: list[tuple[str, int, int]] = []   # (kind, meters, start_offset_m)
    prev_kind: str | None = None
    walked = 0
    for f in feats:
        p = f.get("properties", {})
        g = f.get("geometry", {})
        if "totalDistance" in p:
            total_d, total_t = int(p["totalDistance"]), int(p["totalTime"])
        if g.get("type") == "Point":
            tt = p.get("turnType")
            if tt in (211, 212, 213, 214, 215, 216, 217):
                cross += 1
            elif tt in (127, 129):
                stairs += 1
            elif tt == 128:
                slope += 1
            elif tt == 218:
                elev += 1
            # 포인트는 run을 끊지 않는다 (지하 통로 안의 좌회전 등)
        elif g.get("type") == "LineString":
            for x, y in g.get("coordinates", []):
                pts.append(LatLng(lat=y, lng=x))
            ft = str(p.get("facilityType", ""))
            kind = {"14": "underpass", "18": "underpass", "12": "overpass"}.get(ft)
            m = int(p.get("distance") or 0)
            if kind and kind == prev_kind:
                k, acc, off = runs[-1]
                runs[-1] = (k, acc + m, off)
            elif kind:
                runs.append((kind, m, walked))
            prev_kind = kind
            walked += m

    def is_origin_passage(k: str, m: int, off: int) -> bool:
        # 출발 직후 짧은 지하 구간(역 출구 통로)은 장애물이 아니다 — 사용자는 이미 거기 서 있다
        return k == "underpass" and off <= ORIGIN_PASSAGE_WITHIN_M and m < ORIGIN_PASSAGE_MAX_M

    origin_m = sum(m for k, m, off in runs if is_origin_passage(k, m, off))
    under = [m for k, m, off in runs if k == "underpass" and not is_origin_passage(k, m, off)]
    over = [m for k, m, _ in runs if k == "overpass"]
    return RouteResult(
        mode="walk", distance_m=total_d, duration_s=total_t, source="tmap",
        polyline=tuple(pts),
        facilities=Facilities(crosswalk=cross, stairs=stairs, underpass=len(under), underpass_m=sum(under),
                              origin_passage_m=origin_m, overpass=len(over), elevator=elev, slope=slope),
        option=option,
    )
