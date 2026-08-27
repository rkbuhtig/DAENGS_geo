"""네이버·카카오 어댑터 — **좌표 순서와 인증 헤더.**

**왜 필요한가**: 둘 다 지금까지 fake 경유로만 돌았다. 그런데 이 두 파일에서 틀리기 쉬운 건
로직이 아니라 **원천마다 뒤집히는 관례**다.

    네이버 정적지도 URL   center = "경도,위도"      (우리 LatLng 와 반대)
    카카오 로컬 응답      y = 위도, x = 경도        (이름이 좌표를 안 말해준다)

뒤집혀도 URL 도 JSON 도 멀쩡해 보이고, 지도에는 엉뚱한 데가 그려질 뿐이라 어느 단언도
안 깨진다. `journey/handoff` 의 tmap `goalx` 와 같은 종류의 함정이다.

HTTP 는 안 태운다 — `test_provider_truthfulness` 의 `_Capture` 관례대로 나가는 요청만 잡는다.
"""

import httpx
import pytest

from app.providers.base import LatLng, MapMarker, StaticMapSpec
from app.providers.kakao import KakaoProvider
from app.providers.naver import NaverProvider

CENTER = LatLng(37.4979, 127.0276)
SPEC = StaticMapSpec(CENTER, 15, 400, 300, (MapMarker(CENTER, "가", True),))


def test_naver_upstream_url_puts_longitude_first():
    """`center=경도,위도`. 뒤집으면 강남역 대신 바다 한복판이 그려진다."""
    url = NaverProvider("id", "key").upstream_static_url(SPEC)
    assert "center=127.0276%2C37.4979" in url or "center=127.0276,37.4979" in url


def test_naver_marker_pos_is_lng_then_lat():
    """마커도 경도가 먼저다. 구분자는 공백인데 `urlencode` 가 `+` 로 내보낸다."""
    url = NaverProvider("id", "key").upstream_static_url(SPEC)
    assert "pos:127.0276+37.4979" in url


def test_naver_client_url_is_our_proxy_with_lat_first():
    """클라이언트에 주는 건 우리 프록시다 — 키가 안 새고, 여기선 위도가 먼저다."""
    url = NaverProvider("id", "key").static_map_url(SPEC)
    assert url.startswith("/map/static?")
    assert "lat=37.4979" in url and "lng=127.0276" in url
    assert "ncp" not in url and "key" not in url


def test_naver_sends_both_apigw_headers():
    provider = NaverProvider("my-id", "my-secret")
    assert provider._headers == {
        "x-ncp-apigw-api-key-id": "my-id",
        "x-ncp-apigw-api-key": "my-secret",
    }


def test_kakao_static_map_is_none_not_a_broken_url():
    """미구현은 None 이다. 빈 문자열이면 클라이언트가 깨진 이미지를 그린다."""
    assert KakaoProvider("k").static_map_url(SPEC) is None


@pytest.mark.asyncio
async def test_kakao_geocode_reads_y_as_latitude():
    """카카오는 `y` 가 위도, `x` 가 경도다. 바꿔 읽으면 서울이 중국 근처가 된다."""
    class _Stub:
        async def get(self, url, params, headers):
            assert headers["Authorization"] == "KakaoAK my-rest-key"
            return httpx.Response(
                200, json={"documents": [{"y": "37.4979", "x": "127.0276"}]},
                request=httpx.Request("GET", url),
            )

    got = await KakaoProvider("my-rest-key", client=_Stub()).geocode("강남역")
    assert got == LatLng(lat=37.4979, lng=127.0276)


@pytest.mark.asyncio
async def test_kakao_geocode_returns_none_when_nothing_matches():
    """빈 결과를 0,0 으로 만들지 않는다 — 기니만 앞바다가 진짜 답인 척한다."""
    class _Stub:
        async def get(self, url, params, headers):
            return httpx.Response(200, json={"documents": []},
                                  request=httpx.Request("GET", url))

    assert await KakaoProvider("k", client=_Stub()).geocode("없는주소") is None
