"""화면이 쓸 질의 조합 — 저녁 산책 직전 장면 하나를 숫자로 만든다.

갈래는 [experience-scenario](../../../docs/explorations/walk/experience-scenario.md).
장면의 다섯 비트 중 3·4·5 번이 여기서 나온다.

    3. 조건을 바꾸면 지도가 바뀐다          조건별 Layer
    4. 영역을 탭하면 방문률·조건 대비·추세   RegionStats
    5. 추천 카드 셋                         Card

## 왜 `app/geo` 가 아닌가

`region_visit_rate` 같은 순수 공간 연산은 geo 것이다. 그런데 **"익숙함이란 무엇인가" 는
공간 진실이 아니라 제품 가설**이다. 지금은

    익숙함  = 지금 조건에서 방문률이 가장 높다
    덜 감   = 최근 30 일이 그 앞 30 일보다 낮다 (익숙한 곳과 겹쳐도 된다)
    미개척  = 후보 중 방문률이 바닥이다

로 두지만 나중에 recency·체류·계절 안정성으로 바뀔 수 있다. geo 가 이 정의를 소유하면
가설을 바꿀 때 공간 연산까지 흔들린다. 화살표는 #67 그대로 — 응용이 도메인을 내려다본다.

## 결정론

`now` 를 **인자로 받는다.** 페르소나 자료는 합성 1 년치라 "최근 30 일" 의 기준점이 없으면
같은 입력이 매번 다른 답을 낸다. 장면의 완료 조건이 "deterministic JSON 하나" 라서
시계를 읽는 곳이 하나도 없어야 한다.

## 비율은 분자·분모와 함께 낸다

조건을 겹치면(저녁 ∩ 최근 30 일) 분모가 금방 한 자리로 떨어진다. `5/7` 과 `17/24` 는
화면에서 같은 71% 지만 믿을 값이 아니다. 그래서 `VisitRate` 를 그대로 들고 다니고
화면까지 넘긴다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.features.territory.layers import (
    Aggregation,
    LayerSpec,
    Projection,
    Selector,
    VisitRate,
    derive_tags,
    region_visit_rate,
)
from app.features.territory.paint import Cellophane
from app.features.territory.region import Region

EXPERIENCE_VERSION = 1
RECENT_DAYS = 30

# 추세라고 부르기 위한 최소 표본. **근거 있는 문턱이 아니라 화면용 잠정값이다** — 실사용
# 데이터가 0 이라 정할 근거가 없다(#57 이 보관 일수를 안 정한 것과 같은 이유). 그래서 숨기지
# 않고 JSON 에 실어, 화면이 "추세" 대신 "표본 부족" 을 말할 수 있게 한다.
TREND_MIN_WALKS = 5

# 이 아래면 "안 가봤다" 로 본다. 역시 잠정값이고 JSON 에 실어 보낸다.
UNEXPLORED_CUT = 0.05

# 화면의 조건 칩. 이 순서가 화면 순서다.
CHIPS: tuple[tuple[str, str], ...] = (
    ("all", "전체"),
    ("recent", "최근 30일"),
    ("morning", "아침"),
    ("evening", "저녁"),
    ("spring", "봄"),
    ("summer", "여름"),
    ("autumn", "가을"),
    ("winter", "겨울"),
)
_SEASONS = ("spring", "summer", "autumn", "winter")


def chip_selector(chip: str, today: date) -> Selector:
    """칩 이름 하나 → `Selector`. 화면과 질의가 같은 사전을 쓰게 하려고 여기 둔다."""
    if chip == "all":
        return Selector.of()
    if chip == "recent":
        # `until` 을 빼먹으면 **미래까지 삼킨다.** `now` 가 자료 끝보다 뒤일 때는 티가 안 나다가
        # 자료 한가운데를 "지금" 으로 잡는 순간 최근 30 일이 261 회가 됐다. 창은 창이어야 한다.
        return Selector.of(since=today - timedelta(days=RECENT_DAYS), until=today)
    if chip in ("morning", "evening"):
        return Selector.of(time_band=chip)
    if chip in _SEASONS:
        return Selector.of(season=chip)
    raise ValueError(f"모르는 칩: {chip}")


@dataclass(frozen=True)
class NamedRegion:
    """후보 영역 하나. 이름은 **사람이 붙인다** — 자동 분할은 이번 범위 밖이다."""

    region: Region
    name: str


@dataclass(frozen=True)
class Trend:
    """최근 30 일 방문률 − 그 앞 30 일 방문률.

    두 창의 분자·분모를 다 들고 다닌다. 추세는 **차이보다 표본이 먼저** 읽혀야 하는 값이라서다 —
    `1/2 → 2/2` 도 +0.5 고 `40/80 → 80/80` 도 +0.5 지만 둘은 같은 얘기가 아니다.
    """

    recent: VisitRate
    previous: VisitRate

    @property
    def delta(self) -> float | None:
        """두 창 중 한쪽이라도 산책이 없으면 **추세가 없다.** 0 이 아니다.

        `VisitRate.rate` 가 `0/0` 에서 `None` 을 주는 것과 같은 이유다 — "안 갔다" 와
        "잴 수 없다" 를 같은 값으로 접으면 화면이 "변화 없음" 이라고 단정하게 된다.
        """
        if self.recent.rate is None or self.previous.rate is None:
            return None
        return self.recent.rate - self.previous.rate

    @property
    def trustworthy(self) -> bool:
        return (self.recent.selected >= TREND_MIN_WALKS
                and self.previous.selected >= TREND_MIN_WALKS)


@dataclass(frozen=True)
class RegionStats:
    """영역 하나를 탭했을 때 나오는 것 전부 (장면 4 번)."""

    region_id: str
    region_version: int
    name: str
    by_chip: dict[str, VisitRate]
    trend: Trend


@dataclass(frozen=True)
class Card:
    """추천 카드 하나 (장면 5 번).

    `why` 는 **문장이 아니라 숫자**다. 문장은 화면이 템플릿으로 만들고, 나중에는 응답
    에이전트가 만든다 (#53 — 판단은 근거를 가진 쪽, 실행은 데이터를 가진 쪽).
    """

    kind: str                      # familiar | neglected | unexplored
    region_id: str
    name: str
    why: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Experience:
    """장면 하나. 이것이 그대로 JSON 이 된다."""

    now: datetime
    context: dict[str, str]
    spec_label: str
    regions: list[RegionStats]
    cards: list[Card]
    walks_total: int
    thresholds: dict[str, float]
    version: int = EXPERIENCE_VERSION


def _spec(selector: Selector, projection: Projection, min_peak: float) -> LayerSpec:
    return LayerSpec(selector=selector,
                     aggregation=Aggregation(metric="walks", min_peak=min_peak),
                     projection=projection)


def region_stats(sheets: list[Cellophane], named: NamedRegion, now: datetime,
                 projection: Projection, *, min_peak: float = 0.0) -> RegionStats:
    """영역 하나의 조건별 방문률과 추세 (장면 4 번)."""
    today = now.date()
    by_chip = {
        chip: region_visit_rate(
            sheets, _spec(chip_selector(chip, today), projection, min_peak), named.region)
        for chip, _label in CHIPS
    }
    recent_start = today - timedelta(days=RECENT_DAYS)
    previous = Selector.of(since=recent_start - timedelta(days=RECENT_DAYS),
                           until=recent_start - timedelta(days=1))
    return RegionStats(
        region_id=named.region.id,
        region_version=named.region.version,
        name=named.name,
        by_chip=by_chip,
        trend=Trend(
            recent=by_chip["recent"],
            previous=region_visit_rate(
                sheets, _spec(previous, projection, min_peak), named.region),
        ),
    )


def pick_cards(stats: list[RegionStats], context_chip: str) -> list[Card]:
    """추천 카드 셋 (장면 5 번). **후보 영역이 고정이라 같은 표의 정렬 세 가지다.**

    추천 "엔진" 이 아니다. 이번에 검증하는 것은 순위 알고리즘이 아니라 **익숙함 / 덜 감 /
    미개척이라는 제품 프레이밍이 값어치가 있는가** 이므로, 규칙은 읽으면 바로 보이는 편이 낫다.

    미개척이 특히 그렇다. `활동 반경 − 방문 support` 를 쓰면 건물 한복판과 하천 수면이
    미개척이 되고, 그걸 고치려고 라우팅 그래프를 만들면 바로 샌다. 후보를 사람이 고른 영역
    넷으로 묶어 두는 것이 이번 스켈레톤의 **의도한 가짜**다.

    ## 익숙한 곳이 덜 간 곳이기도 할 수 있다

    처음엔 한 영역이 카드 둘에 못 나오게 막았다. "익숙한 곳" 이자 "덜 간 곳" 이면 화면이
    자기모순으로 읽힐 것 같아서였다. **페르소나 D 를 넣어 보고 틀린 규칙인 걸 알았다.**

        골목 안쪽   저녁 방문률 54% (최다)   추세 −0.54 (최대 낙폭)

    "제일 자주 가던 곳인데 요즘 부쩍 뜸하다" 는 자기모순이 아니라 **그 화면에서 제일 할 말이
    많은 사실**이다. 규칙이 그걸 지우고 있었다. 그래서 겹침을 허용하고, 겹쳤다는 사실을
    `same_as_familiar` 로 실어 보낸다 — 카드 두 장으로 그릴지 한 문장으로 합칠지는 화면이
    정한다.

    미개척은 다르다. 거긴 겹치면 진짜 모순이다 — 자주 가는 곳이 동시에 안 가본 곳일 수 없다.
    """
    if not stats:
        return []

    cards: list[Card] = []
    taken: set[str] = set()
    explored = [s for s in stats
                if s.by_chip["all"].rate is not None
                and s.by_chip["all"].rate > UNEXPLORED_CUT]

    # `rate` 가 None 인 칩(그 조건의 산책이 0 회)은 후보에서 뺀다 — 0 으로 치면 "저녁에
    # 한 번도 안 갔다" 와 "저녁 산책 자체가 없었다" 가 같은 값이 된다
    in_context = [s for s in explored if s.by_chip[context_chip].rate is not None]
    familiar = max(in_context,
                   key=lambda s: (s.by_chip[context_chip].rate, s.by_chip["all"].rate, s.region_id),
                   default=None)
    if familiar is not None:
        seen = familiar.by_chip[context_chip]
        taken.add(familiar.region_id)
        cards.append(Card(kind="familiar", region_id=familiar.region_id, name=familiar.name,
                          why={"chip": context_chip, "rate": seen.rate,
                               "visited": seen.visited, "selected": seen.selected}))

    dropped = [s for s in explored if s.trend.delta is not None and s.trend.delta < 0]
    neglected = min(dropped, key=lambda s: (s.trend.delta, s.region_id), default=None)
    if neglected is not None:
        taken.add(neglected.region_id)
        cards.append(Card(kind="neglected", region_id=neglected.region_id, name=neglected.name,
                          why={"delta": neglected.trend.delta,
                               "recent": [neglected.trend.recent.visited,
                                          neglected.trend.recent.selected],
                               "previous": [neglected.trend.previous.visited,
                                            neglected.trend.previous.selected],
                               "trustworthy": neglected.trend.trustworthy,
                               "same_as_familiar": familiar is not None
                               and neglected.region_id == familiar.region_id}))

    # `rate is not None` 이 없으면 **산책이 하나도 없을 때 전부 미개척**이 된다. 기록이 0 인
    # 사람에게 "여긴 안 가보셨네요" 라고 말하는 셈이라, 근거가 없는 게 아니라 근거가
    # 반대다 — 안 간 게 아니라 우리가 모르는 것이다. 처음엔 `selected > 0` 으로 직접 막았는데,
    # `rate` 가 `0/0` 에서 None 을 주게 되면서(그 편이 옳다) 같은 뜻이 됐다.
    never = [s for s in stats
             if s.region_id not in taken
             and s.by_chip["all"].rate is not None
             and s.by_chip["all"].rate <= UNEXPLORED_CUT]
    unexplored = min(never, key=lambda s: (s.by_chip["all"].rate, s.region_id), default=None)
    if unexplored is not None:
        seen = unexplored.by_chip["all"]
        cards.append(Card(kind="unexplored", region_id=unexplored.region_id,
                          name=unexplored.name,
                          why={"rate": seen.rate, "visited": seen.visited,
                               "selected": seen.selected, "cut": UNEXPLORED_CUT}))
    return cards


def build(sheets: list[Cellophane], regions: list[NamedRegion], now: datetime,
          projection: Projection, *, context_chip: str = "evening",
          min_peak: float = 0.0) -> Experience:
    """장면 하나를 통째로. 화면은 이 결과만 읽는다."""
    stats = [region_stats(sheets, named, now, projection, min_peak=min_peak)
             for named in regions]
    tags = derive_tags(now)
    return Experience(
        now=now,
        context={"chip": context_chip,
                 "season": tags["season"], "time_band": tags["time_band"]},
        spec_label=_spec(chip_selector(context_chip, now.date()), projection, min_peak).label,
        regions=stats,
        cards=pick_cards(stats, context_chip),
        walks_total=len(sheets),
        thresholds={"trend_min_walks": TREND_MIN_WALKS, "unexplored_cut": UNEXPLORED_CUT,
                    "recent_days": RECENT_DAYS, "min_peak": min_peak},
    )
