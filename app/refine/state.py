"""검색 상태 — 대화·UI가 편집하는 것. docs/explorations/hospital-search/refine-loop.md, condition-schema.md

무상태 서버: 클라이언트가 state를 되돌려준다. history는 undo용 스택 (직전 상태들).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.providers.base import Mode, WalkOption

Sort = Literal["distance", "duration", "open_first"]


class WalkPrefs(BaseModel):
    option: WalkOption = "recommended"
    max_min: int | None = None
    avoid: list[Literal["underpass", "overpass", "stairs"]] = Field(default_factory=list)


class SearchState(BaseModel):
    # 위치
    lat: float
    lng: float
    radius_m: int = 2000
    # 시간
    open_now: bool = False
    night: bool = False
    emergency: bool = False
    at: datetime | None = None
    # 종류
    specialty: list[str] = Field(default_factory=list)   # ortho, eye, dental, derma, cardio, rehab
    require_tags: list[str] = Field(default_factory=list)  # 24h, center, secondary ...
    # 이동
    mode: Mode | None = None
    walk: WalkPrefs = Field(default_factory=WalkPrefs)
    # 세션 편집
    exclude_ids: list[int] = Field(default_factory=list)
    pin_ids: list[int] = Field(default_factory=list)
    sort: Sort = "distance"
    limit: int = 20
    # undo
    history: list[dict] = Field(default_factory=list, exclude=False)

    def snapshot(self) -> dict:
        return self.model_dump(exclude={"history"})
