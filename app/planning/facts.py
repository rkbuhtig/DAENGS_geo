"""서버가 요청마다 조립하는 사실. **클라이언트가 못 건드린다.**

편집 상태(`EditableState`)와 갈라놓는 이유는 출처가 다르기 때문이다:

  EditableState   지도·챗봇에서 사용자가 정한 것. state 로 왕복한다
  RuntimeFacts    프로필·날씨·현재 시각. 매 요청 서버가 다시 뽑는다

이걸 한 상자에 담으면 클라이언트가 프로필과 기온을 실어 보낼 수 있게 되고(변조),
지난 턴의 날씨가 그대로 되돌아온다(노후화).

`Clock` 이 프로토콜인 이유: `datetime.now()` 를 각자 부르던 게 이 사달의 뿌리였다.
경로의 야간 판정은 서버 현재 시각을, 병원 영업 판정은 `target.at` 을 봤다 — 같은 요청인데
두 엔진이 다른 시각을 살았다. 시각은 resolver 가 한 번 정해서 계획에 실어 보낸다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.planning.semantics import UrgencySignal
from app.profile.contract import DogProfile, OwnerProfile


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class FixedClock:
    """테스트용. '같은 요청은 같은 시각을 본다'를 단언하려면 시간이 고정돼야 한다."""

    at: datetime

    def now(self) -> datetime:
        return self.at


@dataclass(frozen=True)
class RuntimeFacts:
    """이번 요청에 대해 **서버가 아는** 것.

    `urgency_signals` 에 규칙 파생 긴급도가 담긴다 — 편집 상태에 안 남기는 이유는
    한 번 걸린 오탐이 세션에 눌어붙으면 사용자가 내릴 방법이 없기 때문이다.
    사용자가 말한 긴급도는 `EditableState.urgency` 에 있고, 병합은 resolver 가 한다.
    """

    now: datetime
    profile: DogProfile | None = None
    owner: OwnerProfile | None = None
    temp_c: float | None = None                                  # 출발지·출발시각 기준 기온
    urgency_signals: tuple[UrgencySignal, ...] = field(default_factory=tuple)
