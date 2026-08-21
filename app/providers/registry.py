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


def route_provider_name(mode: Mode) -> str:
    """설정값 그대로. 'none' 은 **이 수단을 안 쓴다**는 뜻이지 추정하라는 뜻이 아니다."""
    return {"walk": settings.walk_route_provider,
            "car": settings.car_route_provider,
            "transit": settings.transit_route_provider}[mode]


@lru_cache
def route_provider(mode: Mode) -> MapProvider:
    return _build(route_provider_name(mode))


def route_capability_problems() -> list[str]:
    """설정한 제공사가 그 모드를 실제로 구현했나. 반환 = 사람이 읽는 문제 목록.

    `car_route_provider=kakao` 는 장애가 아니라 **평시에도 100% 추정**이었다 —
    KakaoProvider.route 가 자동차 미구현이라 언제나 None 을 준다. 설정 오류가 런타임
    강등과 같은 침묵 경로로 합류하면 구분할 방법이 없으니, 시작할 때 갈라둔다.
    """
    problems: list[str] = []
    for mode in ("walk", "car", "transit"):
        name = route_provider_name(mode)
        if name in ("none", "fake"):
            continue
        provider = route_provider(mode)
        if provider.name == "none":
            problems.append(f"{mode}: '{name}' 제공사 키가 없다 (DAENGS_*_KEY 확인)")
        elif mode not in provider.route_modes:
            supported = ", ".join(sorted(provider.route_modes)) or "없음"
            problems.append(f"{mode}: '{name}' 는 이 모드를 구현하지 않았다 (구현: {supported})")
    return problems
