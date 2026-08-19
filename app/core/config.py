from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DAENGS_", extra="ignore")

    database_url: str = "postgresql+asyncpg://daengs:daengs@localhost:5432/daengs"

    # 지도 제공사 — docs/07-map-provider.md. 정적 지도와 지오코딩을 따로 고를 수 있다.
    map_provider: Literal["kakao", "naver", "fake", "none"] = "none"
    static_map_provider: Literal["kakao", "naver", "fake", "none"] | None = None  # None → map_provider 따름
    geocode_provider: Literal["kakao", "naver", "fake", "none"] | None = None

    # 경로 — 모드별 제공사. 도보 장애물은 TMAP만 줌 (docs/research/2026-08-19-route-apis.md)
    walk_route_provider: Literal["tmap", "fake", "none"] = "fake"
    car_route_provider: Literal["kakao", "naver", "fake", "none"] = "fake"
    transit_route_provider: Literal["kakao", "fake", "none"] = "fake"
    route_top_n: int = 5              # 실측 호출은 상위 N개만, 나머지 휴리스틱

    # LLM — utterance 있을 때만 호출. fake = 규칙 기반
    llm_provider: Literal["fake", "openai"] = "fake"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # 커뮤니티 근거 (네이버 검색 API). fake = 시드 스니펫
    community_provider: Literal["fake", "naver", "none"] = "fake"
    naver_search_client_id: str = ""
    naver_search_client_secret: str = ""

    kakao_rest_key: str = ""
    tmap_app_key: str = ""
    naver_ncp_key_id: str = ""
    naver_ncp_key: str = ""

    # 검색 기본값
    default_radius_m: int = Field(2000, ge=100, le=20000)
    max_radius_m: int = 10000
    default_limit: int = 20

    dev_console: bool = True          # /dev 검증 콘솔. 운영에선 False

    # 딥링크
    app_scheme: str = "daengs"
    web_map_base: str = "https://daengs.example/map"


settings = Settings()
