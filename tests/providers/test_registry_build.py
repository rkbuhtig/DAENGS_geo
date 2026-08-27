"""설정 → 제공사 선택. **키가 없으면 조용히 `null` 로 떨어진다.**

**왜 필요한가**: `build_raw_provider()` 는 키가 없을 때 예외를 던지지 않고 `NullProvider` 를 준다.
그 선택은 의도적이다(시작 검증이 `route_capability_problems` 로 따로 잡는다) — 대신
**이 조용한 강등이 정확히 언제 일어나는지**가 계약이 된다. 이름은 맞는데 키만 빠진
경우가 실제 사고 형태다: 설정 파일엔 `naver` 라고 쓰여 있고 로그도 안 나는데 지도가 안 뜬다.

`route_provider` 쪽 조립(게이트 래핑)은 `test_usage_gate` 가 본다. 여기는 그 앞단인
**선택**만 본다 — 결정 #67 PR 1 이 둘을 갈라놓은 그 경계다.
"""

import pytest

from app.core.config import settings
from app.providers.fake import FakeProvider
from app.providers.kakao import KakaoProvider
from app.providers.naver import NaverProvider
from app.providers.registry import build_raw_provider
from app.providers.tmap import TmapProvider


def test_fake_needs_no_key():
    assert isinstance(build_raw_provider("fake"), FakeProvider)


@pytest.mark.parametrize(
    ("name", "keys", "expected"),
    [
        ("kakao", {"kakao_rest_key": "k"}, KakaoProvider),
        ("naver", {"naver_ncp_key_id": "i", "naver_ncp_key": "s"}, NaverProvider),
        ("tmap", {"tmap_app_key": "t"}, TmapProvider),
    ],
)
def test_named_provider_needs_its_key(monkeypatch, name, keys, expected):
    for field, value in keys.items():
        monkeypatch.setattr(settings, field, value)
    assert isinstance(build_raw_provider(name), expected)


@pytest.mark.parametrize(
    ("name", "keys"),
    [
        ("kakao", {"kakao_rest_key": ""}),
        ("naver", {"naver_ncp_key_id": "i", "naver_ncp_key": ""}),   # **반쪽 키도 실패다**
        ("naver", {"naver_ncp_key_id": "", "naver_ncp_key": "s"}),
        ("tmap", {"tmap_app_key": ""}),
    ],
)
def test_missing_key_degrades_to_null_silently(monkeypatch, name, keys):
    for field, value in keys.items():
        monkeypatch.setattr(settings, field, value)
    assert build_raw_provider(name).name == "none"


def test_unknown_name_is_null_not_an_exception():
    """오타 난 제공사 이름도 부팅을 막지 않는다 — 시작 검증이 사람이 읽는 말로 알린다."""
    assert build_raw_provider("gogle").name == "none"
