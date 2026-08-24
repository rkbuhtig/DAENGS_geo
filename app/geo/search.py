"""반경 검색 — 결정론. 병원/약국 공용, 나중에 산책 랜드마크도 이 함수를 쓴다."""

from urllib.parse import urlencode

from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.geo.facility_hours import attach_facility_hours
from app.geo.hours import is_open_at, today_ranges
from app.geo.models import Place
from app.geo.schemas import MapOut, PlaceOut, SearchOut, SearchParams
from app.geo.tagging import dog_ok
from app.planning.facts import SystemClock
from app.planning.plans import SearchMust, SearchPlan, SearchPrefer
from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.registry import static_map_provider


def _prefer_tags(specialty: list[str] | None, *, night: bool, emergency: bool) -> set[str]:
    """**순위만** 바꾸는 태그들. 결과 집합은 안 건드린다.

    특화(specialty)와 야간·응급이 한 자리에 있는 건 셋 다 같은 재료 — 간판 이름 —
    이기 때문이다. 신뢰도가 같으니 권한도 같아야 한다.
    """
    prefer = set(specialty or [])
    if night:
        prefer |= {"night", "24h", "emergency"}
    if emergency:
        prefer |= {"emergency", "24h"}
    return prefer


def _point(lat: float, lng: float):
    return cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)


async def find_places(
    db: AsyncSession,
    plan: SearchPlan,
    *,
    only_dog_ok: bool = True,
) -> list[PlaceOut]:
    must = plan.must
    origin = _point(must.lat, must.lng)
    dist = func.ST_Distance(Place.location, origin).label("distance_m")
    geom = cast(Place.location, Geometry)

    stmt = (
        select(Place, dist, func.ST_Y(geom).label("lat"), func.ST_X(geom).label("lng"))
        .where(Place.active.is_(True))
        .where(func.ST_DWithin(Place.location, origin, must.radius_m))
    )
    if must.kind:
        stmt = stmt.where(Place.kind == must.kind)
    # **야간·응급은 거르지 않는다.** 인허가 원천엔 진료 능력이 없어서 이 태그들은 간판 이름
    # 정규식이 전부다 (geo/tagging.py). 실측 2026-08-20, 활성 병원 5,457곳 중
    # night 1곳 · emergency 2곳 · ortho 2곳 — WHERE 로 쓰면 반경 안 결과가 통째로 사라진다.
    # '미상은 제외하지 않는다'(open_now)와 같은 판단이다: 모르는 걸 없는 것으로 취급하지 않는다.
    # 진짜 요구('24시만 보여줘')는 require_tags 로 온다 — 그건 사용자가 명시했으니 거른다.
    if must.require_tags:
        stmt = stmt.where(Place.tags.contains(list(must.require_tags)))
    if must.exclude_ids:
        stmt = stmt.where(Place.id.notin_(list(must.exclude_ids)))
    prefer = set(plan.prefer.tags)
    fetch = must.limit * 4 if must.open_now else must.limit * 2
    # prefer 를 SQL 정렬로 앞당기지 않는다. 태그 우선 + [:limit] 절단은 사실상 필터가 된다 —
    # 실측(강남역 5km): 태그 10곳이 전부 들어오면 근접 병원 10곳이 집합에서 밀려난다.
    # '빼지 않는다'는 약속은 집합 단위로 지켜야 한다. 희귀 태그가 fetch 창 밖인 문제
    # (예은, top-12 밖)는 기본 모음/추천 모음 분리에서 두 번째 조회로 푼다 (backlog).
    stmt = stmt.order_by(dist).limit(fetch)

    rows = (await db.execute(stmt)).all()
    out: list[PlaceOut] = []
    for place, distance_m, plat, plng in rows:
        tags = list(place.tags or [])
        if only_dog_ok and not dog_ok(tags):
            continue
        open_flag = is_open_at(place.hours, must.judge_at, is_24h=place.is_24h)
        # **미상은 제외하지 않는다** (condition-schema.md). 확정 '영업종료'만 뺀다.
        # 인허가 원천에 영업시간이 없어 실데이터는 대부분 미상이다 - 여기서 빼면 결과가 통째로 사라진다.
        if must.open_now and open_flag is False:
            continue
        out.append(PlaceOut(
            id=place.id, kind=place.kind, name=place.name, lat=plat, lng=plng,
            distance_m=int(distance_m), address=place.address, phone=place.phone,
            is_night=place.is_night, is_24h=place.is_24h, open_now=open_flag,
            hours_today=today_ranges(place.hours, must.judge_at), tags=tags,
            area_m2=float(place.area_m2) if place.area_m2 is not None else None,
            staff_count=place.staff_count,
            prefer_hit=sorted(set(tags) & prefer),
        ))
    if must.open_now:
        # 확정 영업중을 앞으로, 미상은 뒤로 - 빼지는 않는다. 거리순은 각 묶음 안에서 유지.
        out.sort(key=lambda p: (p.open_now is not True, p.distance_m))
    out = out[:must.limit]
    # 표시 보강만 - 존재·정렬·open_now 판정엔 관여하지 않는다 (facility_hours.py).
    await attach_facility_hours(db, out)
    return out


async def search_places(db: AsyncSession, p: SearchParams) -> SearchOut:
    plan = SearchPlan(
        must=SearchMust(
            lat=p.lat, lng=p.lng, radius_m=p.radius_m,
            judge_at=p.at or SystemClock().now(), kind=p.kind,
            open_now=p.open_now, limit=p.limit,
        ),
        prefer=SearchPrefer(tags=tuple(sorted(_prefer_tags(None, night=p.night, emergency=False)))),
    )
    results = await find_places(db, plan)
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
