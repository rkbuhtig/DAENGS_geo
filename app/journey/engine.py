"""journey 엔진 — 출발지→목적지의 이동 스냅샷. 공용 (병원행·약국행·산책 코스).

- measured=True: 제공사 실측(route_provider) + 캐시, 실패 시 휴리스틱 강등. False: 휴리스틱만(호출 0)
- companion=dog: 개 계수·옵션 비교(골목 vs 큰길)·advice·spots 노트·대중교통 제한
- companion=none: 제공사 원값, 도착 앵커만, advice 없음 — 지도앱 수준
"""

import asyncio
import time
from dataclasses import dataclass

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
from app.planning.plans import JourneyPlan
from app.providers.base import LatLng, Mode, RouteResult, RouteStatus, WalkOption
from app.providers.fake import FakeProvider, haversine_m
from app.providers.registry import route_provider, route_provider_name

_fake = FakeProvider()

# 경로 캐시 — (출발 ~11m 격자, 도착, 모드, 옵션). 도보는 길이 안 변하니 오래, 차량은 교통 반영 위해 짧게.
_TTL = {"walk": 6 * 3600, "car": 600, "transit": 1800}
_cache: dict[tuple, tuple[float, RouteResult]] = {}
_CACHE_MAX = 5000


def _ckey(mode: Mode, o: LatLng, d: LatLng, option: WalkOption) -> tuple:
    return (mode, round(o.lat, 4), round(o.lng, 4), round(d.lat, 4), round(d.lng, 4), option if mode == "walk" else "")


def cache_stats() -> dict:
    return {"size": len(_cache)}


def can_measure(mode: Mode) -> bool:
    """이 모드를 **진짜로** 실측할 수 있나. fake·none·미구현은 전부 아니다."""
    name = route_provider_name(mode)
    if name in ("none", "fake"):
        return False
    provider = route_provider(mode)
    return provider.name != "none" and mode in provider.route_modes


@dataclass(frozen=True)
class RouteOutcome:
    """경로 하나와 **그 숫자를 얼마나 믿을 수 있는지**. 강등은 조용히 일어나면 안 된다."""

    result: RouteResult | None
    status: RouteStatus
    reason: str | None = None


async def _route(mode: Mode, o: LatLng, d: LatLng, option: WalkOption,
                 measured: bool) -> RouteOutcome:
    """네 갈래뿐이다.

        설정이 none        → unavailable. 숫자를 만들지 않는다
        추정 요청(목록)     → estimate (preview)
        설정이 fake        → estimate. 실측을 요청받아도 measured 라고 하지 않는다
        실측 요청, 성공     → measured. **진짜 제공사만 이 값을 받는다**
        실측 요청, 실패     → estimate + 강등 이유. 왜 추정인지가 응답에 남는다
    """
    name = route_provider_name(mode)
    if name == "none":
        return RouteOutcome(None, "unavailable", "provider_disabled")

    if not measured:
        return RouteOutcome(await _fake.route(mode, o, d, option), "estimate", "preview")
    if name == "fake":
        # 개발용 대역. **실측을 요청받아도 measured 라고 하지 않는다** — 계산식을 제공사
        # 결과로 부르는 게 이 계약이 없애려는 거짓말이다. measured 는 진짜 제공사만 준다.
        return RouteOutcome(await _fake.route(mode, o, d, option), "estimate", "provider_is_fake")

    k = _ckey(mode, o, d, option)
    hit = _cache.get(k)
    if hit and time.monotonic() - hit[0] < _TTL[mode]:
        return RouteOutcome(hit[1], "measured")

    provider = route_provider(mode)
    if provider.name == "none":
        reason = "provider_unconfigured"          # 키 없음 — 시작 검증이 잡았어야 한다
    elif mode not in provider.route_modes:
        reason = "capability_missing"             # 그 모드를 구현 안 함 — 위와 같음
    else:
        reason = None
        try:
            r = await provider.route(mode, o, d, option)
        except (httpx.HTTPError, ValueError, KeyError):
            r = None
            reason = "provider_error"
        if r:
            if len(_cache) >= _CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            _cache[k] = (time.monotonic(), r)
            return RouteOutcome(r, "measured")
        reason = reason or "provider_no_route"
    # 강등해도 거리·시간은 준다 — 그건 모델이고, 라벨이 붙어 있으면 쓸모가 있다.
    # 시설은 안 준다 (FakeProvider 참조). 없는 계단을 경고하느니 아무 말도 안 하는 게 낫다.
    return RouteOutcome(await _fake.route(mode, o, d, option), "estimate", reason)


def _unavailable_leg(mode: Mode, outcome: RouteOutcome) -> Leg:
    """숫자를 만들지 않는 leg. 0 이 아니라 **없음**이다 — 클라이언트는 '경로 정보 없음'을 그려야 한다."""
    return Leg(status="unavailable", status_reason=outcome.reason, source=route_provider_name(mode))


def _leg(outcome: RouteOutcome, factor: float,
         advice: tuple[str, list[str]] | None = None) -> Leg:
    r = outcome.result
    assert r is not None
    # **실측이 아니면 시설은 없다.** fake 가 안 만들지만 여기서도 막는다 —
    # 시설은 advice(계단 경고·횡단 주의)를 먹이고, 그건 노령견 보호자가 읽는 문장이다.
    fac = r.facilities if outcome.status == "measured" else None
    return Leg(
        status=outcome.status, status_reason=outcome.reason,
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


async def snapshot(plan: JourneyPlan, dest: LatLng, *, dest_name: str = "",
                   with_polyline: bool = True,
                   arrive_note: str | None = None) -> Transport:
    origin = LatLng(plan.origin_lat, plan.origin_lng)
    companion: Companion = plan.companion  # type: ignore[assignment]
    avoid = list(plan.walk.avoid)
    profile = plan.profile
    straight = int(haversine_m(origin, dest))
    dog = companion == "dog"
    walk_option = plan.walk.option
    if not dog and walk_option == "no_stairs":
        walk_option = "recommended"       # 사람만 갈 땐 프로필 유래 기본값을 안 쓴다
    show_transit = "transit" in plan.mode_priority
    measured_mode = plan.mode_priority[0] if plan.measured and plan.mode_priority else None

    walk_measured = measured_mode == "walk"
    # 옵션 비교(골목 vs 큰길)는 **실측일 때만** 한다. 시설·큰길 비율을 모르는 채로 고르면
    # 선택은 사실상 무작위인데 "개 반응이 있어 골목으로 골랐다" 같은 이유가 응답에 남는다 —
    # 비교한 적 없는 비교를 설명하는 꼴이다.
    compare_options = walk_measured and dog and can_measure("walk")
    opts = (walk_options_to_try(walk_option, avoid, profile, plan.travel_is_night)
            if compare_options else [walk_option])
    walk_tasks = [asyncio.create_task(_route("walk", origin, dest, o, walk_measured)) for o in opts]
    car_task = asyncio.create_task(_route("car", origin, dest, walk_option, measured_mode == "car"))
    transit_task = (asyncio.create_task(_route("transit", origin, dest, walk_option,
                                               measured_mode == "transit"))
                    if show_transit else None)
    walk_outcomes = [await t for t in walk_tasks]
    car = await car_task
    transit = await transit_task if transit_task else None

    factor = dog_time_factor(profile) if dog else 1.0
    walks = [o for o in walk_outcomes if o.result is not None]
    if not walks:
        wl = _unavailable_leg("walk", walk_outcomes[0])
    else:
        results = [o.result for o in walks]
        if dog:
            best_r, choose_why = choose_walk(
                results, walk_option, avoid, profile, factor, plan.travel_is_night,
            )
            adv_lvl, adv_why = walk_advice(
                best_r, profile, plan.walk.max_walk_min, avoid, plan.temp_c, factor,
            )
            advice = (adv_lvl, choose_why + adv_why)
        else:
            best_r, advice = results[0], None
        best = next(o for o in walks if o.result is best_r)

        wl = _leg(best, factor, advice)
        # 옵션 비교는 실측일 때만 의미가 있다 — 추정에서는 옵션이 숫자를 안 바꾼다
        wl.alternatives = [
            Alt(option=str(r.option), label=OPTION_LABEL.get(str(r.option), str(r.option)),
                min=max(1, round(r.duration_s * factor / 60)), m=r.distance_m,
                facilities=r.facilities.__dict__ if r.facilities else {},
                delta_min=round((r.duration_s - best_r.duration_s) * factor / 60))
            for r in results if r is not best_r
        ] if best.status == "measured" else []
        wl.spots = spots_out(best_r, profile, companion, arrive_note)
        wl.handoff = handoff_links(origin, dest, dest_name, "walk")
        if with_polyline and best_r.polyline and best.status == "measured":
            wl.polyline = encode_polyline([(p.lat, p.lng) for p in best_r.polyline])
            wl.polyline_points = len(best_r.polyline)

    cl = _leg(car, 1.0) if car.result else _unavailable_leg("car", car)
    cl.handoff = handoff_links(origin, dest, dest_name, "car")
    tl = None
    if transit:
        tl = _leg(transit, 1.0) if transit.result else _unavailable_leg("transit", transit)
        tl.handoff = handoff_links(origin, dest, dest_name, "transit")

    return Transport(
        as_of=plan.resolved_at,
        companion=companion,
        straight_m=straight,
        mode_priority=list(plan.mode_priority),
        walk=wl,
        car=cl,
        transit=tl,
    )
