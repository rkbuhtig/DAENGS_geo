"""검색 상태 — 대화·UI가 편집하는 것.

**두 정책은 다르다. 그래서 타입도 나눈다.**

  target (어디를 갈까)  = 필터.  조건에 안 맞으면 결과 집합에서 사라진다.        → geo.search.find_places
  journey (어떻게 갈까) = 판정.  결과를 빼지 않는다. 경로 계산 방식과 advice만 바꾼다. → journey.engine.snapshot (POST /journey)

이 경계를 넘는 유일한 예외는 `journey.hard_limit` 하나뿐이고, 그건 사용자가 명시적으로 켤 때만 동작한다.
journey 값을 find_places에 넘기거나, target 값으로 경로를 바꾸지 말 것.

무상태 서버: 클라이언트가 state를 되돌려준다. history는 undo용 스택.
docs/explorations/hospital-search/refine-loop.md, condition-schema.md
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.providers.base import Mode, WalkOption

Sort = Literal["distance", "duration", "open_first"]
Facility = Literal["underpass", "overpass", "stairs"]


class TargetPrefs(BaseModel):
    """어디를 갈까 — **필터**. 결과 집합을 바꾼다."""

    radius_m: int = 2000
    open_now: bool = False
    night: bool = False
    emergency: bool = False
    at: datetime | None = None                              # 판정 기준 시각
    specialty: list[str] = Field(default_factory=list)      # ortho, eye, dental, derma, cardio, rehab — 부스트용
    require_tags: list[str] = Field(default_factory=list)   # 24h, center, secondary ... — 필수
    exclude_ids: list[int] = Field(default_factory=list)
    pin_ids: list[int] = Field(default_factory=list)
    limit: int = 20


class WalkPrefs(BaseModel):
    option: WalkOption = "recommended"
    avoid: list[Facility] = Field(default_factory=list)


class JourneyPrefs(BaseModel):
    """어떻게 갈까 — **판정**. 결과를 빼지 않는다 (hard_limit 예외)."""

    mode: Mode | None = None
    walk: WalkPrefs = Field(default_factory=WalkPrefs)
    max_min: int | None = None      # 소요시간 상한. 기본은 advice=avoid 표시만
    hard_limit: bool = False        # True면 상한 초과를 결과에서 제외 — 정책 경계를 넘는 유일한 스위치


class SearchState(BaseModel):
    lat: float
    lng: float
    target: TargetPrefs = Field(default_factory=TargetPrefs)
    journey: JourneyPrefs = Field(default_factory=JourneyPrefs)
    sort: Sort = "distance"         # 표시 정책 — 어느 쪽도 아님
    history: list[dict] = Field(default_factory=list)

    def snapshot(self) -> dict:
        return self.model_dump(exclude={"history"})
