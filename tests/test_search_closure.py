"""Place 검색 진입점의 약속 집행 — **PostGIS 만 있으면 뜬다** (`app/search_main.py`).

부팅 성공만 검사하면 안 되는 이유: provider 설정은 전부 기본값이 있어서, Kakao/Naver/
Tmap 코드가 closure 에 동승해도 서버는 멀쩡히 뜬다. 경계 침범이 조용히 초록불을 받는
바로 그 상태다. 그래서 경계는 **import closure** 로 재고, 부팅·검증 경로는 스모크로만
확인한다. `test_import_direction.py` 가 층 방향을 지키는 것과 같은 계열의 기계적 집행이다.
"""

import json
import subprocess
import sys

from fastapi.testclient import TestClient

from app.core.db import get_session

# 검색 진입점이 몰라야 하는 것들. 지도/route provider, 외부 호출 미터링, walk/journey
# 표면, 프로필 저장소(결정 #73), 그리고 전체 개발 서버의 현관문(main) 자체.
BANNED_PREFIXES = (
    "app.providers",
    "app.usage",
    "app.features",
    "app.journey",
    "app.discovery",
    "app.profile",
    "app.main",
)

_PROBE = """
import json, sys
import app.search_main
print(json.dumps(sorted(m for m in sys.modules if m.startswith("app."))))
"""


def test_search_entrypoint_import_closure_stays_inside_the_boundary():
    """같은 프로세스에서 재면 다른 테스트가 이미 로드한 모듈이 섞인다 — 새 인터프리터로 잰다."""
    probe = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True,
    )
    loaded = json.loads(probe.stdout)
    banned = [
        m for m in loaded
        if any(m == p or m.startswith(p + ".") for p in BANNED_PREFIXES)
    ]
    assert not banned, (
        f"검색 진입점 closure 에 경계 밖 모듈이 딸려 온다: {banned}. "
        "새 import 가 provider/profile/표면 쪽으로 이어졌는지 보라 — "
        "geo/search.py(순수 DB)와 geo/search_surface.py(지도 surface)의 분리가 그 경계다."
    )


async def _no_db():
    yield None


def test_search_app_serves_health_and_validation_without_db_or_provider_keys():
    """DB 없이도 뜨고, 검증 경로가 동작하고, place 밖의 표면은 노출하지 않는다."""
    from app.search_main import app as search_app

    search_app.dependency_overrides[get_session] = _no_db
    try:
        with TestClient(search_app) as client:
            assert client.get("/health").json() == {"ok": True}
            rejected = client.post("/v2/places/search", json={
                "lat": 37.5, "lng": 127.0, "kinds": ["cafe"], "conditions": {},
            })
            assert rejected.status_code == 422
    finally:
        search_app.dependency_overrides.pop(get_session, None)

    exposed = set(search_app.openapi()["paths"])
    assert exposed == {"/health", "/health/ready", "/v2/places/search"}, (
        f"검색 서버의 표면이 계약과 다르다: {sorted(exposed)}"
    )
