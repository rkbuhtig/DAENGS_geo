"""의료 검색의 지도 surface — 정적 지도 preview·deeplink 조립.

`geo/search.py` 에서 분리했다. DB 반경 검색(`find_places` 류)과 지도 provider 는 다른
질문이다 — canonical Place resolver 가 필요한 것은 `find_authoritative_places` 뿐인데,
같은 파일에 있으면 검색 import closure 에 Kakao/Naver/Tmap provider 전체가 딸려 온다.
Place 검색 전용 진입점(`app/search_main.py`)은 이 모듈을 모른다.
"""

from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import SystemClock
from app.core.config import settings
from app.geo.contract import SearchMust, SearchPlan, SearchPrefer
from app.geo.ranking import preference_tags
from app.geo.schemas import MapOut, PlaceOut, SearchOut, SearchParams
from app.geo.search import find_places
from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.registry import static_map_provider


async def search_places(db: AsyncSession, p: SearchParams) -> SearchOut:
    plan = SearchPlan(
        must=SearchMust(
            lat=p.lat, lng=p.lng, radius_m=p.radius_m,
            judge_at=p.at or SystemClock().now(), kind=p.kind,
            open_now=p.open_now, limit=p.limit,
        ),
        prefer=SearchPrefer(tags=preference_tags(night=p.night, emergency=p.emergency)),
    )
    results = await find_places(db, plan)
    return SearchOut(params=p, results=results, map=build_map(p.lat, p.lng, p.radius_m, p.kind,
                                                                p.open_now, p.night, results,
                                                                emergency=p.emergency))


def build_map(lat: float, lng: float, radius_m: int, kind: str | None, open_now: bool, night: bool,
              results: list[PlaceOut], *, emergency: bool = False) -> MapOut:
    # 검색 결과만 넘기면 지도 화면이 다시 질의를 만들 때 선호 상태가 사라진다.
    filters = [
        name for name, on in (("open", open_now), ("night", night), ("emergency", emergency))
        if on
    ]
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
