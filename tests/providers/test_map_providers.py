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


class _Recorder:
    """나가는 요청만 잡는다. 응답은 테스트가 정한다 — HTTP 는 안 태운다."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.params: dict = {}
        self.headers: dict = {}

    async def get(self, url, params, headers):
        self.params = dict(params)
        self.headers = dict(headers)
        return httpx.Response(200, json=self._payload, request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_naver_geocode_actually_sends_both_apigw_headers():
    """**필드가 아니라 나간 요청을 본다.** `_headers` 만 확인하면 호출에서 헤더를 빼도
    통과한다 — 실제로 그랬다. 인증이 빠지면 401 인데 우리 쪽 로그엔 '경로 없음' 으로 보인다."""
    rec = _Recorder({"addresses": [{"y": "37.4979", "x": "127.0276"}]})
    await NaverProvider("my-id", "my-secret", client=rec).geocode("강남역")

    assert rec.headers["x-ncp-apigw-api-key-id"] == "my-id"
    assert rec.headers["x-ncp-apigw-api-key"] == "my-secret"


@pytest.mark.asyncio
async def test_naver_geocode_reads_y_as_latitude():
    """네이버도 `y` 가 위도다. kakao 와 키 이름은 같은데 이 파일에서만 두 번 나온다."""
    rec = _Recorder({"addresses": [{"y": "37.4979", "x": "127.0276"}]})
    got = await NaverProvider("i", "s", client=rec).geocode("강남역")
    assert got == LatLng(lat=37.4979, lng=127.0276)


@pytest.mark.asyncio
async def test_naver_geocode_returns_none_when_nothing_matches():
    rec = _Recorder({"addresses": []})
    assert await NaverProvider("i", "s", client=rec).geocode("없는주소") is None


@pytest.mark.asyncio
async def test_naver_reverse_geocode_sends_coords_as_lng_comma_lat():
    """`coords` 는 경도가 먼저다. 뒤집으면 남한 밖 좌표가 되어 빈 결과가 온다."""
    rec = _Recorder({"results": [{"region": {"area1": {"name": "서울특별시"}}}]})
    await NaverProvider("i", "s", client=rec).reverse_geocode(LatLng(37.4979, 127.0276))

    assert rec.params["coords"] == "127.0276,37.4979"
    assert rec.headers["x-ncp-apigw-api-key-id"] == "i"


@pytest.mark.asyncio
async def test_naver_reverse_geocode_joins_region_names_in_order():
    rec = _Recorder({"results": [{"region": {
        "area1": {"name": "서울특별시"}, "area2": {"name": "강남구"},
        "area3": {"name": "역삼동"}, "area4": {"name": ""},
    }}]})
    got = await NaverProvider("i", "s", client=rec).reverse_geocode(LatLng(37.4979, 127.0276))
    assert got == "서울특별시 강남구 역삼동"


@pytest.mark.asyncio
async def test_kakao_reverse_geocode_sends_x_as_longitude():
    """카카오는 `x` 가 경도, `y` 가 위도다 — geocode 응답과 같은 관례가 요청에도 적용된다."""
    rec = _Recorder({"documents": [{"road_address": {"address_name": "테헤란로 1"}}]})
    await KakaoProvider("my-rest-key", client=rec).reverse_geocode(LatLng(37.4979, 127.0276))

    assert rec.params["x"] == 127.0276
    assert rec.params["y"] == 37.4979
    assert rec.headers["Authorization"] == "KakaoAK my-rest-key"


@pytest.mark.asyncio
async def test_kakao_reverse_geocode_falls_back_to_jibun_when_no_road_address():
    """도로명이 없는 곳이 있다. 그때 `None` 을 주면 화면에 주소가 통째로 빈다."""
    rec = _Recorder({"documents": [{"road_address": None, "address": {"address_name": "역삼동 1"}}]})
    got = await KakaoProvider("k", client=rec).reverse_geocode(LatLng(37.4979, 127.0276))
    assert got == "역삼동 1"


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
