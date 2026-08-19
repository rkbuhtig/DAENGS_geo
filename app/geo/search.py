"""반경 검색 — 병원/약국 공용, 나중에 산책 랜드마크도 이 함수를 쓴다."""

from datetime import UTC, datetime
from urllib.parse import urlencode

from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.geo.hours import is_open_at, today_ranges
from app.geo.models import Place
from app.geo.schemas import MapOut, PlaceOut, SearchOut, SearchParams
from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.registry import static_map_provider


def _point(lat: float, lng: float):
    return cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)


async def search_places(db: AsyncSession, p: SearchParams) -> SearchOut:
    at = p.at or datetime.now(UTC)
    origin = _point(p.lat, p.lng)
    dist = func.ST_Distance(Place.location, origin).label("distance_m")

    geom = cast(Place.location, Geometry)
    stmt = (
        select(Place, dist, func.ST_Y(geom).label("lat"), func.ST_X(geom).label("lng"))
        .where(Place.active.is_(True))
        .where(func.ST_DWithin(Place.location, origin, p.radius_m))
    )
    if p.kind:
        stmt = stmt.where(Place.kind == p.kind)
    if p.night:
        stmt = stmt.where((Place.is_night.is_(True)) | (Place.is_24h.is_(True)))
    # open_now는 SQL로 못 거른다(hours가 JSON) → 넉넉히 가져와 파이썬에서 필터
    fetch = p.limit * 4 if p.open_now else p.limit
    stmt = stmt.order_by(dist).limit(fetch)

    rows = (await db.execute(stmt)).all()

    results: list[PlaceOut] = []
    for place, distance_m, lat, lng in rows:
        open_now = is_open_at(place.hours, at, is_24h=place.is_24h)
        if p.open_now and open_now is not True:
            continue
        results.append(
            PlaceOut(
                id=place.id, kind=place.kind, name=place.name,
                lat=lat, lng=lng, distance_m=int(distance_m),
                address=place.address, phone=place.phone,
                is_night=place.is_night, is_24h=place.is_24h,
                open_now=open_now, hours_today=today_ranges(place.hours, at),
            )
        )
        if len(results) >= p.limit:
            break

    return SearchOut(params=p, results=results, map=_build_map(p, results))


def _build_map(p: SearchParams, results: list[PlaceOut]) -> MapOut:
    filters = [f for f, on in (("open", p.open_now), ("night", p.night)) if on]
    q = {"lat": p.lat, "lng": p.lng, "radius": p.radius_m}
    if p.kind:
        q["type"] = p.kind
    if filters:
        q["filter"] = ",".join(filters)
    if results:
        q["ids"] = ",".join(str(r.id) for r in results[:10])
    qs = urlencode(q)

    markers = tuple(
        MapMarker(pos=LatLng(r.lat, r.lng), label=chr(65 + i), highlight=(i == 0))
        for i, r in enumerate(results[:10])
    )
    spec = StaticMapSpec(center=LatLng(p.lat, p.lng), markers=markers)
    return MapOut(
        preview_url=static_map_provider().static_map_url(spec),
        deeplink=f"{settings.app_scheme}://map?{qs}",
        web_url=f"{settings.web_map_base}?{qs}",
    )
