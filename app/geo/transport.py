"""교통 스냅샷. docs/explorations/hospital-search/transport-snapshot.md

- 상위 N개만 실측(route_provider), 나머지 휴리스틱(FakeProvider 계산). source로 구분.
- advice(ok/caution/avoid)는 우리 규칙: 시간·장애물 + 프로필. 제공사엔 없는 개념.
"""

import asyncio
import time
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.profile.contract import DogProfile
from app.providers.base import Facilities, LatLng, Mode, RouteResult, WalkOption
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


class Alt(BaseModel):
    option: str
    min: int
    m: int
    facilities: dict[str, int]
    delta_min: int                  # 선택된 것 대비


class Leg(BaseModel):
    min: int                        # 개 기준 보정 시간 (프로필 계수 적용)
    provider_min: int | None = None # 제공사 원값 (성인 기준)
    m: int
    source: str
    option: str | None = None
    facilities: dict[str, int] | None = None
    taxi_fare: int | None = None
    fare: int | None = None
    advice: str | None = None       # ok | caution | avoid
    why: list[str] = Field(default_factory=list)
    alternatives: list[Alt] = Field(default_factory=list)   # 다른 도보 옵션과의 트레이드오프


class Transport(BaseModel):
    as_of: datetime
    straight_m: int
    walk: Leg | None = None
    car: Leg | None = None
    transit: Leg | None = None


# ---- 개 기준 보정 --------------------------------------------------------
def dog_time_factor(profile: DogProfile | None) -> float:
    """제공사 도보 시간은 성인 4.4km/h(TMAP 실측). 개 데리고는 느리다."""
    if not profile:
        return 1.2                     # 기본: 냄새 맡기·배변
    f = 1.2
    if profile.is_senior: f += 0.3
    if profile.has_joint_issue: f += 0.2
    if profile.is_brachy: f += 0.2
    if profile.size_class == "small": f += 0.1
    if profile.activity_level == "high": f -= 0.1
    return round(min(f, 2.0), 2)


def walk_options_to_try(prefer: WalkOption, avoid: list[str], profile: DogProfile | None) -> list[WalkOption]:
    """실측 시 몇 개 옵션을 받아 비교할지. TMAP은 옵션 하나에 한 경로라 트레이드오프는 우리가 만든다."""
    opts: list[WalkOption] = [prefer]
    if avoid or (profile and (profile.is_senior or profile.has_joint_issue)):
        for o in ("no_stairs", "recommended"):
            if o not in opts: opts.append(o)
    return opts


# ---- advice 규칙 --------------------------------------------------------
def walk_advice(r: RouteResult, profile: DogProfile | None, max_min: int | None,
                avoid: list[str], temp_c: float | None = None, factor: float = 1.0) -> tuple[str, list[str]]:
    why: list[str] = []
    level = 0  # 0 ok, 1 caution, 2 avoid
    minutes = r.duration_s * factor / 60
    fac = r.facilities or Facilities()

    if max_min is not None and minutes > max_min:
        level = 2; why.append(f"{int(minutes)}분 > 제한 {max_min}분")

    if profile:
        cap = 45.0
        if profile.is_senior: cap = 20.0
        if profile.has_joint_issue: cap = min(cap, 15.0)
        if profile.is_brachy: cap = min(cap, 20.0)
        if profile.size_class == "small" and profile.weight_kg < 4: cap = min(cap, 20.0)
        if minutes > cap * 1.5:
            level = 2; why.append(f"{int(minutes)}분 — {profile.name}에겐 과함(권장 ≤{int(cap)}분)")
        elif minutes > cap:
            level = max(level, 1); why.append(f"{int(minutes)}분 — 권장 {int(cap)}분 초과")
        if fac.stairs and (profile.is_senior or profile.has_joint_issue):
            level = 2; why.append(f"계단 {fac.stairs}회 — 노령·관절")
        if fac.underpass and profile.size_class == "large":
            level = max(level, 1); why.append(f"지하 통로 {fac.underpass}곳({fac.underpass_m}m) — 대형견 스트레스")
        if profile.is_brachy and temp_c is not None and temp_c >= 28:
            level = 2; why.append(f"단두종 + {temp_c:.0f}℃")

    for a in avoid:
        n = getattr(fac, a, 0)
        if n:
            level = max(level, 1)
            why.append({"stairs": "계단", "underpass": "지하 통로", "overpass": "육교"}.get(a, a) + f" {n} (피하기 요청)")
    if fac.crosswalk >= 6:
        level = max(level, 1); why.append(f"횡단보도 {fac.crosswalk}회")

    return ("ok", "caution", "avoid")[level], why


def _leg(r: RouteResult, advice: tuple[str, list[str]] | None = None, factor: float = 1.0) -> Leg:
    return Leg(
        min=max(1, round(r.duration_s * factor / 60)),
        provider_min=(max(1, round(r.duration_s / 60)) if factor != 1.0 else None),
        m=r.distance_m, source=r.source, option=r.option,
        facilities=(r.facilities.__dict__ if r.facilities else None),
        taxi_fare=r.taxi_fare, fare=r.fare,
        advice=advice[0] if advice else None, why=advice[1] if advice else [],
    )


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


async def snapshot_for(origin: LatLng, dest: LatLng, *, rank: int, mode: Mode | None,
                       walk_option: WalkOption, walk_max: int | None, avoid: list[str],
                       profile: DogProfile | None, temp_c: float | None = None) -> Transport:
    measured = rank < settings.route_top_n
    straight = int(haversine_m(origin, dest))
    show_transit = profile is None or profile.size_class == "small"

    walk_measured = measured and mode in (None, "walk")
    opts = walk_options_to_try(walk_option, avoid, profile) if walk_measured else [walk_option]
    walk_tasks = [asyncio.create_task(_route("walk", origin, dest, o, walk_measured)) for o in opts]
    car_task = asyncio.create_task(_route("car", origin, dest, walk_option, measured and mode == "car"))
    transit_task = (asyncio.create_task(_route("transit", origin, dest, walk_option, measured and mode == "transit"))
                    if show_transit else None)

    walks = [await t for t in walk_tasks]
    car = await car_task
    transit = await transit_task if transit_task else None

    # 옵션 비교: 시설 페널티 + 시간. 선호 옵션은 동점이면 우선
    factor = dog_time_factor(profile)
    def score(r: RouteResult) -> tuple[float, int]:
        pen = r.facilities.penalty(tuple(avoid)) if r.facilities else 0
        return (pen + r.duration_s * factor / 60 / 5, 0 if r.option == walk_option else 1)
    best = min(walks, key=score)
    alts = [Alt(option=str(r.option), min=max(1, round(r.duration_s * factor / 60)), m=r.distance_m,
                facilities=r.facilities.__dict__ if r.facilities else {},
                delta_min=round((r.duration_s - best.duration_s) * factor / 60))
            for r in walks if r is not best]

    wl = _leg(best, walk_advice(best, profile, walk_max, avoid, temp_c, factor), factor)
    wl.alternatives = alts
    return Transport(
        as_of=datetime.now(UTC), straight_m=straight,
        walk=wl, car=_leg(car), transit=_leg(transit) if transit else None,
    )
