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
from app.geo.polyline import encode as encode_polyline
from app.profile.contract import DogProfile
from app.providers.base import Facilities, LatLng, Mode, RouteResult, Spot, WalkOption
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


class SpotOut(BaseModel):
    kind: str
    lat: float
    lng: float
    offset_m: int
    text: str
    landmark: str = ""
    road: str = ""
    big_road: bool = False
    length_m: int = 0
    note: str | None = None      # daengs 고유 — 이 개한테 한마디
    warn: bool = False           # 강조 표시 여부


class Handoff(BaseModel):
    """실제 따라가기는 제공사 앱으로. 딥링크 3종 (앱 미설치 시 스토어/웹은 클라이언트가 처리)."""
    naver: str
    kakao: str
    tmap: str


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
    spots: list[SpotOut] = Field(default_factory=list)      # 반려견 관심 지점 (출발 전 한 장)
    polyline: str | None = None                             # encoded polyline (precision 5). 실측이면 기본 포함
    polyline_points: int = 0
    handoff: Handoff | None = None


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


# ---- spot 노트 (시설 × 프로필) --------------------------------------------
def spot_note(sp: Spot, profile: DogProfile | None) -> tuple[str | None, bool]:
    """(note, warn). 이 개한테 이 지점이 뭔지 한마디. 없으면 None."""
    p = profile
    if sp.kind == "crosswalk":
        bits = []
        if sp.big_road:
            bits.append("큰길 — 목줄 짧게, 신호 기다리기")
        if p and "reactive_to_dogs" in p.temperament:
            bits.append("건널목에 다른 개 있을 수 있음")
        if p and p.is_senior and sp.big_road:
            bits.append("신호 한 번에 못 건너면 중앙 대기")
        return (" · ".join(bits) or None, sp.big_road)
    if sp.kind == "stairs":
        if p and (p.is_senior or p.has_joint_issue):
            return ("계단 — 안고 이동 권장", True)
        if p and p.size_class == "small":
            return ("계단 — 소형견은 안고 이동", True)
        return ("계단", False)
    if sp.kind == "underpass":
        if p and p.size_class == "large":
            return (f"지하 통로 {sp.length_m}m — 대형견 스트레스, 짧게 통과", True)
        if p and "timid" in p.temperament:
            return (f"지하 통로 {sp.length_m}m — 소음·울림, 겁 많으면 주의", True)
        return (f"지하 통로 {sp.length_m}m", sp.length_m >= 100)
    if sp.kind == "overpass":
        return ("육교 — 계단 있을 가능성", bool(p and (p.is_senior or p.has_joint_issue)))
    if sp.kind == "elevator":
        return ("엘리베이터 — 케이지/안고 탑승", False)
    if sp.kind == "slope":
        return ("경사로", bool(p and p.has_joint_issue))
    if sp.kind == "origin_passage":
        return ("출발 지점 통로 (이미 서 있는 곳)", False)
    if sp.kind == "arrive":
        return ("도착 — 간판·층수 확인, 진료 전 전화 권장", False)
    return (None, False)


def spots_out(r: RouteResult, profile: DogProfile | None) -> list[SpotOut]:
    """같은 (종류, 도로)의 노트는 첫 번째만 풀로. 반복은 소음."""
    out = []
    seen: set[tuple[str, str]] = set()
    for sp in r.spots:
        note, warn = spot_note(sp, profile)
        key = (sp.kind, sp.road)
        if note and key in seen and sp.kind == "crosswalk":
            note = "큰길" if sp.big_road else None
        seen.add(key)
        out.append(SpotOut(kind=sp.kind, lat=sp.at.lat, lng=sp.at.lng, offset_m=sp.offset_m, text=sp.text,
                           landmark=sp.landmark, road=sp.road, big_road=sp.big_road, length_m=sp.length_m,
                           note=note, warn=warn))
    return out


def handoff_links(origin: LatLng, dest: LatLng, dest_name: str) -> Handoff:
    from urllib.parse import quote
    n = quote(dest_name)
    return Handoff(
        naver=f"nmap://route/walk?slat={origin.lat}&slng={origin.lng}&sname={quote('현재 위치')}"
              f"&dlat={dest.lat}&dlng={dest.lng}&dname={n}&appname=daengs",
        kakao=f"kakaomap://route?sp={origin.lat},{origin.lng}&ep={dest.lat},{dest.lng}&by=FOOT",
        tmap=f"tmap://route?goalx={dest.lng}&goaly={dest.lat}&goalname={n}",
    )


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
                       profile: DogProfile | None, temp_c: float | None = None,
                       dest_name: str = "", with_polyline: bool = True) -> Transport:
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
    wl.spots = spots_out(best, profile)
    wl.handoff = handoff_links(origin, dest, dest_name)
    if with_polyline and best.polyline and best.source != "estimate":
        wl.polyline = encode_polyline([(p.lat, p.lng) for p in best.polyline])
        wl.polyline_points = len(best.polyline)
    return Transport(
        as_of=datetime.now(UTC), straight_m=straight,
        walk=wl, car=_leg(car), transit=_leg(transit) if transit else None,
    )
