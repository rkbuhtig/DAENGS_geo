"""딥링크 3종. **제공사마다 좌표 순서와 수단 이름이 다르다.**

**왜 필요한가**: 결정 #22 는 "실제 따라가기는 제공사 앱이 잘한다"고 넘겼다. 그래서 이
함수가 틀리면 우리 화면은 멀쩡한데 **사용자가 엉뚱한 곳으로 안내받는다** — 서버 응답도
지도 표시도 정상이라 아무 데서도 안 걸린다.

특히 tmap 은 `goalx` 가 경도, `goaly` 가 위도다. 나머지 둘은 위도가 먼저다. 이 뒤집힘은
서울에서 실행하면 동해 한복판으로 간다 — 그런데 링크 문자열만 보면 멀쩡해 보인다.
"""

from urllib.parse import parse_qs, urlparse

from app.journey.handoff import handoff_links
from app.providers.base import LatLng

ORIGIN = LatLng(37.4979, 127.0276)   # 강남역
DEST = LatLng(37.5145, 127.0316)     # 북쪽 1.8km


def test_tmap_takes_lng_first_and_the_others_take_lat_first():
    """제공사별 좌표 순서. 뒤집히면 서울에서 동해로 간다."""
    links = handoff_links(ORIGIN, DEST, "대치동물병원")

    naver = parse_qs(urlparse(links.naver).query)
    assert naver["dlat"] == ["37.5145"] and naver["dlng"] == ["127.0316"]

    kakao = parse_qs(urlparse(links.kakao).query)
    assert kakao["ep"] == ["37.5145,127.0316"]        # lat,lng
    assert kakao["sp"] == ["37.4979,127.0276"]

    tmap = parse_qs(urlparse(links.tmap).query)
    assert tmap["goalx"] == ["127.0316"]              # **경도가 x**
    assert tmap["goaly"] == ["37.5145"]


def test_each_provider_spells_the_same_mode_differently():
    for mode, naver, kakao in [
        ("walk", "walk", "FOOT"),
        ("car", "car", "CAR"),
        ("transit", "public", "PUBLICTRANSIT"),
    ]:
        links = handoff_links(ORIGIN, DEST, "x", mode=mode)
        assert links.naver.startswith(f"nmap://route/{naver}?")
        assert parse_qs(urlparse(links.kakao).query)["by"] == [kakao]


def test_unknown_mode_falls_back_to_walk_not_to_a_broken_link():
    links = handoff_links(ORIGIN, DEST, "x", mode="teleport")
    assert links.naver.startswith("nmap://route/walk?")
    assert parse_qs(urlparse(links.kakao).query)["by"] == ["FOOT"]


def test_korean_name_is_percent_encoded():
    """인코딩 안 하면 이름에 & 나 공백이 들어간 상호에서 링크가 잘린다."""
    links = handoff_links(ORIGIN, DEST, "24시 강남 동물병원")
    assert "24%EC%8B%9C%20%EA%B0%95%EB%82%A8" in links.naver
    assert parse_qs(urlparse(links.tmap).query)["goalname"] == ["24시 강남 동물병원"]


def test_empty_name_gets_a_default_not_an_empty_parameter():
    links = handoff_links(ORIGIN, DEST, "")
    assert parse_qs(urlparse(links.tmap).query)["goalname"] == ["도착"]
