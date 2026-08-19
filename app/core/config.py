from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DAENGS_", extra="ignore")

    database_url: str = "postgresql+asyncpg://daengs:daengs@localhost:5432/daengs"

    # 지도 제공사 — docs/07-map-provider.md. 정적 지도와 지오코딩을 따로 고를 수 있다.
    map_provider: Literal["kakao", "naver", "none"] = "none"
    static_map_provider: Literal["kakao", "naver", "none"] | None = None  # None → map_provider 따름
    geocode_provider: Literal["kakao", "naver", "none"] | None = None

    kakao_rest_key: str = ""
    naver_ncp_key_id: str = ""
    naver_ncp_key: str = ""

    # 검색 기본값
    default_radius_m: int = Field(2000, ge=100, le=20000)
    max_radius_m: int = 10000
    default_limit: int = 20

    # 딥링크
    app_scheme: str = "daengs"
    web_map_base: str = "https://daengs.example/map"


settings = Settings()
