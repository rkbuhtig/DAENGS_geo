from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["hospital", "pharmacy"]


class SearchParams(BaseModel):
    """챗봇 parse()와 메뉴 UI가 공통으로 채우는 검색 파라미터. docs/03."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: int = Field(2000, ge=100, le=20000)
    kind: Kind | None = None            # None = 둘 다
    open_now: bool = False
    night: bool = False
    limit: int = Field(20, ge=1, le=100)
    at: datetime | None = None          # 판정 기준 시각. None = 서버 now


class PlaceOut(BaseModel):
    id: int
    kind: Kind
    name: str
    lat: float
    lng: float
    distance_m: int
    address: str | None
    phone: str | None
    is_night: bool
    is_24h: bool
    open_now: bool | None               # None = 영업시간 미상
    hours_today: list[tuple[str, str]] | None
    tags: list[str] = Field(default_factory=list)
    area_m2: float | None = None        # 인허가 면적 — 표시만
    staff_count: int | None = None      # 인허가 종사자수 — 표시만
    prefer_hit: list[str] = Field(default_factory=list)  # 선호 조건과 태그 교집합 — 부스트 근거


class MapOut(BaseModel):
    preview_url: str | None
    deeplink: str
    web_url: str


class SearchOut(BaseModel):
    params: SearchParams
    results: list[PlaceOut]
    map: MapOut
