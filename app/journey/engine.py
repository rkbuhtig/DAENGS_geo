"""journey 엔진 — 출발지→목적지의 이동 스냅샷. 공용 (병원행·약국행·산책 코스).

- measured=True: 제공사 실측(route_provider) + 캐시, 실패 시 휴리스틱 강등. False: 휴리스틱만(호출 0)
- companion=dog: 개 계수·옵션 비교(골목 vs 큰길)·advice·spots 노트·대중교통 제한
- companion=none: 제공사 원값, 도착 앵커만, advice 없음 — 지도앱 수준
"""

import asyncio
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

from app.geo.polyline import encode as encode_polyline
from app.journey.advice import (
    OPTION_LABEL,
    choose_walk,
    dog_time_factor,
    walk_advice,
    walk_options_to_try,
)
from app.journey.handoff import handoff_links
from app.journey.models import Alt, Companion, Leg, RoadMix, Transport
from app.journey.spots import spots_out
from app.profile.contract import DogProfile
from app.providers.base import LatLng, Mode, RouteResult, WalkOption
from app.providers.fake import FakeProvider, haversine_m
from app.providers.registry import route_provider

_fake = FakeProvider()

# 경로 캐시 — (출발 ~11m 격자, 도착, 모드, 옵션). 도보는 길이 안 변하니 오래, 차량은 교통 반영 위해 짧게.
_TTL = {"walk": 6 * 3600, "car": 600, "transit": 1800}
_cache: dict[tuple, tuple[float, RouteResult]] = {}
_CACHE_MAX = 5000


def _ckey(mode: Mode, o: LatLng, d: LatLng, option: WalkOption) -> tuple:
    return (mode, round(o.lat, 4), round(o.lng, 4), round(d.lat, 4), round(d.lng, 4), option if mode == "walk" else "")


def cache_stats() -> dict:
    return {"size": len(_cache)}


async def _route(mode: Mode, o: LatLng, d: LatLng, option: WalkOption, measured: bool) -> RouteResult:
    if measured:
        k = _ckey(mode, o, d, option)
        hit = _cache.get(k)
        if hit and time.monotonic() - hit[0] < _TTL[mode]:
            return hit[1]
        try:
            r = await route_provider(mode).route(mode, o, d, option)
        except (httpx.HTTPError, ValueError, KeyError):   # 제공사 장애/이상 응답 → 휴리스틱으로 강등
            r = None
        if r:
            if len(_cache) >= _CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            _cache[k] = (time.monotonic(), r)
            return r
    return await _fake.route(mode, o, d, option)  # type: ignore[return-value]


def is_night(at: datetime | None = None) -> bool:
    t = (at or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Seoul"))
    return t.hour >= 20 or t.hour < 6


def _leg(r: RouteResult, factor: float, advice: tuple[str, list[str]] | None = None) -> Leg:
    fac = r.facilities
    return Leg(
        min=max(1, round(r.duration_s * factor / 60)),
        provider_min=(max(1, round(r.duration_s / 60)) if factor != 1.0 else None),
        m=r.distance_m, source=r.source, option=r.option,
        option_label=OPTION_LABEL.get(r.option or "", None) if r.option else None,
        facilities=(fac.__dict__ if fac else None),
        road_mix=RoadMix(big_road_m=fac.big_road_m, total_m=fac.total_m, big_ratio=fac.big_road_ratio,
                         big_crossings=fac.big_crossings) if fac else None,
        taxi_fare=r.taxi_fare, fare=r.fare,
        advice=advice[0] if advice else None, why=advice[1] if advice else [],
    )


async def snapshot(origin: LatLng, dest: LatLng, *, companion: Companion = "dog",
                   measured: bool = True, mode: Mode | None = None,
                   walk_option: WalkOption = "recommended", walk_max: int | None = None,  # 도보 상한
                   avoid: list[str] | None = None, profile: DogProfile | None = None,
                   temp_c: float | None = None, at: datetime | None = None,
                   dest_name: str = "", with_polyline: bool = True,
                   arrive_note: str | None = None) -> Transport:
    avoid = avoid or []
    straight = int(haversine_m(origin, dest))
    dog = companion == "dog"
    if not dog and walk_option == "no_stairs":
        walk_option = "recommended"        # 사람만 갈 땐 프로필 유래 기본값을 안 쓴다
    night = is_night(at)
    show_transit = (not dog) or profile is None or profile.size_class == "small"

    walk_measured = measured and mode in (None, "walk")
    opts = walk_options_to_try(walk_option, avoid, profile, night) if (walk_measured and dog) else [walk_option]
    walk_tasks = [asyncio.create_task(_route("walk", origin, dest, o, walk_measured)) for o in opts]
    car_task = asyncio.create_task(_route("car", origin, dest, walk_option, measured and mode == "car"))
    transit_task = (asyncio.create_task(_route("transit", origin, dest, walk_option, measured and mode == "transit"))
                    if show_transit else None)
    walks = [await t for t in walk_tasks]
    car = await car_task
    transit = await transit_task if transit_task else None

    factor = dog_time_factor(profile) if dog else 1.0
    if dog:
        best, choose_why = choose_walk(walks, walk_option, avoid, profile, factor, night)
        adv_lvl, adv_why = walk_advice(best, profile, walk_max, avoid, temp_c, factor)
        advice = (adv_lvl, choose_why + adv_why)
    else:
        best, advice = walks[0], None

    wl = _leg(best, factor, advice)
    wl.alternatives = [
        Alt(option=str(r.option), label=OPTION_LABEL.get(str(r.option), str(r.option)),
            min=max(1, round(r.duration_s * factor / 60)), m=r.distance_m,
            facilities=r.facilities.__dict__ if r.facilities else {},
            delta_min=round((r.duration_s - best.duration_s) * factor / 60))
        for r in walks if r is not best
    ]
    wl.spots = spots_out(best, profile, companion, arrive_note)
    wl.handoff = handoff_links(origin, dest, dest_name, "walk")
    if with_polyline and best.polyline and best.source != "estimate":
        wl.polyline = encode_polyline([(p.lat, p.lng) for p in best.polyline])
        wl.polyline_points = len(best.polyline)

    cl = _leg(car, 1.0)
    cl.handoff = handoff_links(origin, dest, dest_name, "car")
    tl = None
    if transit:
        tl = _leg(transit, 1.0)
        tl.handoff = handoff_links(origin, dest, dest_name, "transit")

    return Transport(as_of=datetime.now(UTC), companion=companion, straight_m=straight, walk=wl, car=cl, transit=tl)
