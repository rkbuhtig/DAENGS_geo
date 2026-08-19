"""설정 → 제공사 인스턴스. 정적 지도와 지오코딩을 다른 제공사로 꽂을 수 있다."""

from functools import lru_cache

from app.core.config import settings
from app.providers.base import MapProvider, NullProvider
from app.providers.kakao import KakaoProvider
from app.providers.naver import NaverProvider


def _build(name: str) -> MapProvider:
    if name == "kakao" and settings.kakao_rest_key:
        return KakaoProvider(settings.kakao_rest_key)
    if name == "naver" and settings.naver_ncp_key_id and settings.naver_ncp_key:
        return NaverProvider(settings.naver_ncp_key_id, settings.naver_ncp_key)
    return NullProvider()


@lru_cache
def static_map_provider() -> MapProvider:
    return _build(settings.static_map_provider or settings.map_provider)


@lru_cache
def geocode_provider() -> MapProvider:
    return _build(settings.geocode_provider or settings.map_provider)
