"""테스트 공용 **장치와 팩토리**. 시나리오 데이터는 여기 두지 않는다.

경계: **만드는 방법은 공유, 무엇을 만들지는 각 테스트가 소유.**
공용 데이터셋을 여기 두면 누가 값을 하나 바꿀 때마다 남의 단언이 조용히 깨지고,
깨진 테스트를 읽어도 왜 그 데이터가 있는지 파일 안에서 안 보인다.

`PERSONAS`는 예외로 앱 코드(`app.profile.source`)에 산다. 그건 테스트 리소스가 아니라
판정 분기를 덮는 계약이고, `test_personas.py`가 그걸 지키는 게 존재 이유다.
"""

from app.providers.base import Facilities, Mode, RouteResult, WalkOption


def route(minutes: float = 20, *, option: WalkOption = "recommended", mode: Mode = "walk",
          source: str = "estimate", distance_m: int | None = None, **facilities) -> RouteResult:
    """경로 하나. 시설은 키워드로 그대로 — `route(10, stairs=1, underpass=1)`.

    거리를 안 주면 초 단위 시간을 그대로 쓴다 (판정 테스트는 대개 시간만 본다).
    """
    secs = int(minutes * 60)
    return RouteResult(mode=mode, distance_m=secs if distance_m is None else distance_m,
                       duration_s=secs, source=source, option=option,
                       facilities=Facilities(**facilities))
