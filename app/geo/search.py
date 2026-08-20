"""반경 검색 — 결정론. 병원/약국 공용, 나중에 산책 랜드마크도 이 함수를 쓴다."""

from datetime import UTC, datetime
from urllib.parse import urlencode

from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.geo.hours import is_open_at, today_ranges
from app.geo.models import Place
from app.geo.schemas import MapOut, PlaceOut, SearchOut, SearchParams
from app.geo.tagging import SPECIALTY_TAGS, dog_ok
from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.registry import static_map_provider


def _point(lat: float, lng: float):
    return cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)


async def find_places(
    db: AsyncSession, *, lat: float, lng: float, radius_m: int, kind: str | None,
    open_now: bool, night: bool, emergency: bool = False,
    specialty: list[str] | None = None, require_tags: list[str] | None = None,
    exclude_ids: list[int] | None = None, at: datetime | None = None, limit: int = 20,
    only_dog_ok: bool = True,
) -> list[PlaceOut]:
    at = at or datetime.now(UTC)
    origin = _point(lat, lng)
    dist = func.ST_Distance(Place.location, origin).label("distance_m")
    geom = cast(Place.location, Geometry)

    stmt = (
        select(Place, dist, func.ST_Y(geom).label("lat"), func.ST_X(geom).label("lng"))
        .where(Place.active.is_(True))
        .where(func.ST_DWithin(Place.location, origin, radius_m))
    )
    if kind:
        stmt = stmt.where(Place.kind == kind)
    if night:
        # 인허가 원천은 야간·24시 컬럼을 주지 않는다 (전부 false로 적재된다). 이름 태그가 유일한 재료다 -
        # 컬럼과 태그 중 하나라도 걸리면 남긴다. 이 셋이 다 비면 야간 필터는 결과 0곳이 된다.
        stmt = stmt.where(
            Place.is_night.is_(True) | Place.is_24h.is_(True)
            | Place.tags.overlap(["night", "24h", "emergency"])
        )
    if emergency:
        stmt = stmt.where(Place.tags.overlap(["emergency", "24h"]))
    if require_tags:
        stmt = stmt.where(Place.tags.contains(list(require_tags)))
    if exclude_ids:
        stmt = stmt.where(Place.id.notin_(list(exclude_ids)))
    # specialty는 필터가 아니라 부스트 — SQL로 안 거른다 (condition-schema.md)
    fetch = limit * 4 if open_now else limit * 2
    stmt = stmt.order_by(dist).limit(fetch)

    rows = (await db.execute(stmt)).all()
    out: list[PlaceOut] = []
    for place, distance_m, plat, plng in rows:
        tags = list(place.tags or [])
        if only_dog_ok and not dog_ok(tags):
            continue
        open_flag = is_open_at(place.hours, at, is_24h=place.is_24h)
        # **미상은 제외하지 않는다** (condition-schema.md). 확정 '영업종료'만 뺀다.
        # 인허가 원천에 영업시간이 없어 실데이터는 대부분 미상이다 - 여기서 빼면 결과가 통째로 사라진다.
        if open_now and open_flag is False:
            continue
        out.append(PlaceOut(
            id=place.id, kind=place.kind, name=place.name, lat=plat, lng=plng,
            distance_m=int(distance_m), address=place.address, phone=place.phone,
            is_night=place.is_night, is_24h=place.is_24h, open_now=open_flag,
            hours_today=today_ranges(place.hours, at), tags=tags,
            area_m2=float(place.area_m2) if place.area_m2 is not None else None,
            staff_count=place.staff_count,
            specialty_hit=sorted(set(tags) & set(specialty or []) & SPECIALTY_TAGS),
        ))
    if open_now:
        # 확정 영업중을 앞으로, 미상은 뒤로 - 빼지는 않는다. 거리순은 각 묶음 안에서 유지.
        out.sort(key=lambda p: (p.open_now is not True, p.distance_m))
    return out[:limit]


async def search_places(db: AsyncSession, p: SearchParams) -> SearchOut:
    results = await find_places(
        db, lat=p.lat, lng=p.lng, radius_m=p.radius_m, kind=p.kind,
        open_now=p.open_now, night=p.night, at=p.at, limit=p.limit,
    )
    return SearchOut(params=p, results=results, map=build_map(p.lat, p.lng, p.radius_m, p.kind,
                                                                p.open_now, p.night, results))


def build_map(lat: float, lng: float, radius_m: int, kind: str | None, open_now: bool, night: bool,
              results: list[PlaceOut]) -> MapOut:
    filters = [f for f, on in (("open", open_now), ("night", night)) if on]
    q: dict = {"lat": lat, "lng": lng, "radius": radius_m}
    if kind:
        q["type"] = kind
    if filters:
        q["filter"] = ",".join(filters)
    if results:
        q["ids"] = ",".join(str(r.id) for r in results[:10])
    qs = urlencode(q)
    markers = tuple(
        MapMarker(pos=LatLng(r.lat, r.lng), label=chr(65 + i), highlight=(i == 0))
        for i, r in enumerate(results[:10])
    )
    spec = StaticMapSpec(center=LatLng(lat, lng), markers=markers)
    return MapOut(
        preview_url=static_map_provider().static_map_url(spec),
        deeplink=f"{settings.app_scheme}://map?{qs}",
        web_url=f"{settings.web_map_base}?{qs}",
    )
