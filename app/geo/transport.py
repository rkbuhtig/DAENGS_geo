"""교통 스냅샷. docs/explorations/hospital-search/transport-snapshot.md

- 상위 N개만 실측(route_provider), 나머지 휴리스틱(FakeProvider 계산). source로 구분.
- advice(ok/caution/avoid)는 우리 규칙: 시간·장애물 + 프로필. 제공사엔 없는 개념.
"""

import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.core.config import settings
from app.profile.contract import DogProfile
from app.providers.base import Facilities, LatLng, Mode, RouteResult, WalkOption
from app.providers.fake import FakeProvider, haversine_m
from app.providers.registry import route_provider

_fake = FakeProvider()


class Leg(BaseModel):
    min: int
    m: int
    source: str
    option: str | None = None
    facilities: dict[str, int] | None = None
    taxi_fare: int | None = None
    fare: int | None = None
    advice: str | None = None       # ok | caution | avoid
    why: list[str] = Field(default_factory=list)


class Transport(BaseModel):
    as_of: datetime
    straight_m: int
    walk: Leg | None = None
    car: Leg | None = None
    transit: Leg | None = None


# ---- advice 규칙 --------------------------------------------------------
def walk_advice(r: RouteResult, profile: DogProfile | None, max_min: int | None,
                avoid: list[str], temp_c: float | None = None) -> tuple[str, list[str]]:
    why: list[str] = []
    level = 0  # 0 ok, 1 caution, 2 avoid
    minutes = r.duration_s / 60
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
            level = max(level, 1); why.append("지하도 — 대형견 스트레스")
        if profile.is_brachy and temp_c is not None and temp_c >= 28:
            level = 2; why.append(f"단두종 + {temp_c:.0f}℃")

    for a in avoid:
        n = getattr(fac, a, 0)
        if n:
            level = max(level, 1); why.append(f"{a} {n}회 (피하기 요청)")
    if fac.crosswalk >= 6:
        level = max(level, 1); why.append(f"횡단보도 {fac.crosswalk}회")

    return ("ok", "caution", "avoid")[level], why


def _leg(r: RouteResult, advice: tuple[str, list[str]] | None = None) -> Leg:
    return Leg(
        min=max(1, round(r.duration_s / 60)), m=r.distance_m, source=r.source, option=r.option,
        facilities=(r.facilities.__dict__ if r.facilities else None),
        taxi_fare=r.taxi_fare, fare=r.fare,
        advice=advice[0] if advice else None, why=advice[1] if advice else [],
    )


async def _route(mode: Mode, o: LatLng, d: LatLng, option: WalkOption, measured: bool) -> RouteResult:
    if measured:
        r = await route_provider(mode).route(mode, o, d, option)
        if r:
            return r
    return await _fake.route(mode, o, d, option)  # type: ignore[return-value]


async def snapshot_for(origin: LatLng, dest: LatLng, *, rank: int, mode: Mode | None,
                       walk_option: WalkOption, walk_max: int | None, avoid: list[str],
                       profile: DogProfile | None, temp_c: float | None = None) -> Transport:
    measured = rank < settings.route_top_n
    straight = int(haversine_m(origin, dest))
    show_transit = profile is None or profile.size_class == "small"

    tasks: dict[str, asyncio.Task] = {
        "walk": asyncio.create_task(_route("walk", origin, dest, walk_option, measured and mode in (None, "walk"))),
        "car": asyncio.create_task(_route("car", origin, dest, walk_option, measured and mode == "car")),
    }
    if show_transit:
        tasks["transit"] = asyncio.create_task(_route("transit", origin, dest, walk_option, measured and mode == "transit"))
    done = {k: await t for k, t in tasks.items()}

    w = done["walk"]
    return Transport(
        as_of=datetime.now(UTC), straight_m=straight,
        walk=_leg(w, walk_advice(w, profile, walk_max, avoid, temp_c)),
        car=_leg(done["car"]),
        transit=_leg(done["transit"]) if "transit" in done else None,
    )
