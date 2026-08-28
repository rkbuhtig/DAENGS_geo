"""장소 이름 → 유형 태그. **분류 정책의 두 번째 자리.**

[결정 #72](../../docs/decisions/2026-08-27-place-tag-catalog.md)가 정한 사전을 코드로
고정한다. `source_catalog.py`(원천 category → kind)·`restriction_map.py`(원문 → 술어)와
같은 지위이고, 셋 다 **사람의 분류 판단을 한 파일에 모아 리뷰 가능하게** 두는 것이 목적이다.

## `restrictions` 와 갈리는 두 가지

**하나. 부재의 뜻이 다르다.** 원문 제약은 원천이 "제한 없음"을 말해줘서 3상태가 됐지만,
이름은 시설의 **부분집합만** 말한다. `type:beach` 가 없는 곳은 "해변이 아닌 곳"이 아니라
**"이름이 해변을 말하지 않은 곳"** 이다. 그래서 태그는 양성 신호만 갖고, 소비자는
`NOT` 필터를 만들지 않는다 (#72 §2).

**둘. 근거 등급이 하나뿐이다.** 판독표는 원천이 문장으로 적어 놓은 것을 옮겼지만
여기는 이름에서 **추론한다** — #70 §3 등급표에서 가장 약한 칸(`name_rule`)이다.

## kind 제약이 규칙의 일부인 이유

유형어가 이름에 있다고 그 유형인 것이 아니다. 실측(2026-08-28):

    번동숲속카페 · 숲속애견랜드 · 멍숲   kind=cafe    숲이 아니라 카페다
    ○○공원약국                          kind=pharmacy 공원이 아니다

그래서 모든 규칙이 자기가 붙을 수 있는 `kind` 를 함께 적는다. 이름만 보는 규칙은
없다.

## 겹침 — 하나를 고르지 않고 둘 다 준다

`○○근린공원 반려견놀이터` 는 공원이면서 놀이터다. 실측상 두 종류가 있다:

    삼막애견공원 · 울산애견공원        놀이터 자체다 (공원은 이름의 일부)
    일산호수공원 반려견놀이터          공원 안의 놀이터다

둘을 규칙으로 가르려면 "어느 쪽이 진짜냐"를 판정해야 하는데 이름만으로는 못 한다.
**태그는 배타 분류가 아니므로 가를 이유도 없다** — 둘 다 붙이고, 사용자가 `놀이터`
facet 을 누르면 43곳이 다 나온다. `kind` 처럼 하나를 골라야 하는 축이었다면 달랐다.

## 이 파일이 하지 않는 것

`cafe`·`shopping` 의 유형 분해는 여기 없다. `travel` 에 재료가 몰려 있고(측정 §6),
`cafe` 는 이름이 고유명이라 유형어가 안 나온다(반복성 8%). `cafe` 가 받는 것은
`role:dog_primary` 뿐이다.
"""

import re
from enum import StrEnum
from typing import NamedTuple

# 규칙·어휘가 바뀌면 올리고 그 변경에서 전체를 재파생한다. `restriction_map` 과 같은 규율.
TAG_RULES_VERSION = "place-tags/1"


class Evidence(StrEnum):
    """이 태그가 어디서 나왔나. 지금은 하나뿐이지만 등급을 응답에 남긴다 (#70 §3).

    이름 규칙은 가장 약한 근거다 — 원천이 말한 것이 아니라 우리가 읽은 것이다.
    """

    NAME_RULE = "name_rule"


class Rule(NamedTuple):
    """이름 규칙 하나. `kinds` 가 비면 어느 kind 에도 안 붙는다 — 실수를 막는 기본값."""

    code: str
    pattern: re.Pattern[str]
    kinds: frozenset[str]
    label: str
    # 이 태그가 참일 때 함께 참인 것. 별도 규칙으로 쓰면 같은 판단이 두 곳에 산다.
    implies: tuple[str, ...] = ()


_TRAVEL = frozenset({"travel"})
# 반려견 전용 시설은 `travel` 밖에도 있다 — 애견카페·펜션이 같은 이름 규칙을 탄다.
_DOG_FIRST = frozenset({"travel", "cafe", "leisure", "pension", "stay", "hotel"})


def _r(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


# ---------------------------------------------------------------- 유형 사전
# 결정 #72 §3 의 16개. 행 수는 2026-08-27 스냅샷의 `kind=travel` 기준이다.
_RULES: tuple[Rule, ...] = (
    # 반려견 전용을 먼저 둔다 — `애견공원` 이 `type:park` 보다 이 규칙에 먼저 걸려야
    # 하는 것은 아니지만(둘 다 붙는다), 읽는 사람에게 이게 주 규칙임을 보인다.
    Rule(
        "type:dog_park",
        _r(r"(반려견|애견|강아지|반려동물)\s*(놀이터|운동장|파크|공원|테마파크)"),
        _DOG_FIRST,
        "반려견 놀이터",
        implies=("role:dog_primary", "activity:run"),
    ),
    Rule("type:beach", _r(r"해수욕장|해변|해안"), _TRAVEL, "해변",
         implies=("environment:natural", "activity:water")),
    Rule("type:valley", _r(r"계곡|폭포"), _TRAVEL, "계곡",
         implies=("environment:natural", "activity:water")),
    Rule("type:lake", _r(r"호수|저수지"), _TRAVEL, "호수",
         implies=("environment:natural", "activity:water")),
    Rule("type:wetland", _r(r"습지|생태공원"), _TRAVEL, "습지",
         implies=("environment:natural",)),
    Rule("type:forest", _r(r"휴양림|자연휴양|수목림|숲길|숲속"), _TRAVEL, "숲",
         implies=("environment:natural",)),
    Rule("type:arboretum", _r(r"수목원|식물원|정원|허브원"), _TRAVEL, "수목원",
         implies=("environment:natural",)),
    Rule("type:ranch", _r(r"목장|농원|농장|과수원"), _TRAVEL, "목장",
         implies=("environment:natural",)),
    Rule("type:lighthouse", _r(r"등대|포구|항구"), _TRAVEL, "포구·등대",
         implies=("environment:natural",)),
    Rule("type:mountain", _r(r"산$|봉$|고개$|오름"), _TRAVEL, "산·오름",
         implies=("environment:natural",)),
    Rule("type:flower_field", _r(r"갈대밭|꽃밭|꽃길|튤립|연꽃|메밀"), _TRAVEL, "꽃밭",
         implies=("environment:natural",)),
    Rule("type:viewpoint", _r(r"전망대|출렁다리|스카이워크"), _TRAVEL, "전망대"),
    Rule("type:amusement", _r(r"유원지|랜드$|월드$|테마파크|워터파크"), _TRAVEL, "테마파크"),
    Rule("type:temple", _r(r"사찰|사$|암자|향교"), _TRAVEL, "사찰",
         implies=("environment:urban",)),
    Rule("type:tourist_zone", _r(r"관광지|관광단지|관광농원"), _TRAVEL, "관광지"),
    Rule("type:square", _r(r"광장"), _TRAVEL, "광장", implies=("environment:urban",)),
    Rule("type:cable_car", _r(r"케이블카|모노레일|곤돌라"), _TRAVEL, "케이블카"),
    Rule("type:rest_area", _r(r"휴게소"), _TRAVEL, "휴게소"),
    Rule("type:fort", _r(r"산성|서원|고분|읍성|성곽"), _TRAVEL, "유적",
         implies=("environment:urban",)),
    Rule("type:village", _r(r"마을|한옥촌|민속촌"), _TRAVEL, "마을",
         implies=("environment:urban",)),
    Rule("type:street", _r(r"거리$|길$|골목|로데오"), _TRAVEL, "거리",
         implies=("environment:urban",)),
    # 공원은 **마지막**이다. 위 규칙 어디에도 안 걸린 `○○공원` 이 여기 온다는 뜻이
    # 아니라(태그는 배타가 아니다), 가장 넓은 규칙이라 읽는 순서를 그렇게 둔다.
    Rule("type:park", _r(r"공원"), _TRAVEL, "공원", implies=("environment:urban",)),
)

# 함의 태그의 라벨. 규칙이 직접 만들지 않고 `implies` 로만 붙는다.
_IMPLIED_LABELS = {
    "role:dog_primary": "개가 주인공",
    "activity:run": "뛰는 곳",
    "activity:water": "물놀이",
    "environment:natural": "자연",
    "environment:urban": "도심",
}

KNOWN_CODES = frozenset(
    {rule.code for rule in _RULES} | set(_IMPLIED_LABELS)
)

LABELS: dict[str, str] = {
    **{rule.code: rule.label for rule in _RULES},
    **_IMPLIED_LABELS,
}


class Tag(NamedTuple):
    code: str
    label: str
    evidence: Evidence = Evidence.NAME_RULE


def tags_for(name: str, kind: str) -> tuple[Tag, ...]:
    """이름과 kind 에서 붙는 태그 전부. 순서는 사전 순서를 따른다.

    **하나를 고르지 않는다.** `일산호수공원 반려견놀이터` 는 `type:dog_park` 과
    `type:park` 을 둘 다 받는다 — 태그는 배타 분류가 아니고, 사용자가 어느 facet 을
    눌러도 그 장소가 나와야 한다.

    매칭이 없으면 빈 튜플이다. **그것은 "유형이 없다" 가 아니라 "이름이 말하지
    않았다" 는 뜻이며**, 소비자는 그 부재를 배제 근거로 쓰지 않는다 (#72 §2).
    """
    codes: list[str] = []
    for rule in _RULES:
        if kind not in rule.kinds or not rule.pattern.search(name):
            continue
        codes.append(rule.code)
        codes.extend(rule.implies)

    seen: set[str] = set()
    ordered: list[Tag] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        ordered.append(Tag(code, LABELS[code]))
    return tuple(ordered)


def rules_for_kind(kind: str) -> tuple[Rule, ...]:
    """이 kind 에 적용되는 규칙. 커버리지 측정과 리뷰가 쓴다."""
    return tuple(rule for rule in _RULES if kind in rule.kinds)
