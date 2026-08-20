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
WalkFacility = Literal["underpass", "overpass", "stairs"]


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
    """**도보로 갈 때만** 의미 있는 하위 설정.

    preferred_mode 가 car 로 바뀌어도 **지우지 않는다.** Transport 는 언제나 walk/car/transit 를
    다 반환하므로 도보 대안에는 계속 적용되고, 사용자가 도보로 돌아오면 설정이 살아 있어야 한다.
    """

    option: WalkOption = "recommended"
    avoid: list[WalkFacility] = Field(default_factory=list)
    max_walk_min: int | None = None     # **개가 걸어도 되는 시간.** journey.max_total_min 과 다르다


class JourneyPrefs(BaseModel):
    """어떻게 갈까 — **판정**. 결과를 빼지 않는다 (hard_limit 예외).

    **수단과 수단별 설정은 계층이 다르다.**
      preferred_mode  어느 leg 를 앞에 놓을지의 *선호*. Transport 는 늘 셋 다 반환한다
      max_total_min   목적지까지 전체 이동시간. **수단 무관** — 차든 도보든 같은 잣대
      walk{}          도보로 갈 때만 의미 있는 것. 도보 옵션이 차량 판정에 적용되면 안 된다

    car{} · transit{} 슬롯은 아직 없다. 유료도로 회피·환승 최소를 넣으려면 그걸 실제로
    반영하는 경로 제공사가 먼저 있어야 한다 — 설정만 받고 무시하면 사용자에게 거짓말이 된다
    (health_flags 의 heart·obesity 가 그렇게 죽어 있다).
    """

    preferred_mode: Mode | None = None
    max_total_min: int | None = None    # 전체 이동시간 상한. 기본은 advice=avoid 표시만
    hard_limit: bool = False            # True면 상한 초과를 결과에서 제외 — 경계를 넘는 유일한 스위치

    walk: WalkPrefs = Field(default_factory=WalkPrefs)


class SearchState(BaseModel):
    lat: float
    lng: float
    target: TargetPrefs = Field(default_factory=TargetPrefs)
    journey: JourneyPrefs = Field(default_factory=JourneyPrefs)
    sort: Sort = "distance"         # 표시 정책 — 어느 쪽도 아님
    history: list[dict] = Field(default_factory=list)

    def snapshot(self) -> dict:
        return self.model_dump(exclude={"history"})
