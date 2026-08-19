"""설정 → 제공사 인스턴스. 정적지도·지오코딩·모드별 경로를 각각 다른 제공사로 꽂을 수 있다."""

from functools import lru_cache

from app.core.config import settings
from app.providers.base import MapProvider, Mode, NullProvider
from app.providers.fake import FakeProvider
from app.providers.kakao import KakaoProvider
from app.providers.naver import NaverProvider
from app.providers.tmap import TmapProvider


def _build(name: str) -> MapProvider:
    if name == "fake":
        return FakeProvider()
    if name == "kakao" and settings.kakao_rest_key:
        return KakaoProvider(settings.kakao_rest_key)
    if name == "naver" and settings.naver_ncp_key_id and settings.naver_ncp_key:
        return NaverProvider(settings.naver_ncp_key_id, settings.naver_ncp_key)
    if name == "tmap" and settings.tmap_app_key:
        return TmapProvider(settings.tmap_app_key)
    return NullProvider()


@lru_cache
def static_map_provider() -> MapProvider:
    return _build(settings.static_map_provider or settings.map_provider)


@lru_cache
def geocode_provider() -> MapProvider:
    return _build(settings.geocode_provider or settings.map_provider)


@lru_cache
def route_provider(mode: Mode) -> MapProvider:
    name = {"walk": settings.walk_route_provider,
            "car": settings.car_route_provider,
            "transit": settings.transit_route_provider}[mode]
    return _build(name)
