"""kind → 지도 아이콘 그룹.

**서버가 정하는 이유**: 원천이 늘 때마다 kind 가 늘어난다 (kcisa 13종 + kto 6종, 앞으로 더).
앱에 매핑을 두면 원천 추가마다 앱을 다시 배포해야 한다 — 지도 표면은 서버가 준 그룹만 보고
아이콘을 고른다. 모르는 kind 는 숨기지 않고 `etc` 로 그린다 (없는 것으로 취급하지 않는다).

그룹 수를 kind 수보다 훨씬 적게 잡는 건 지도의 제약이다. 마커 18종은 눈으로 구별이 안 되고,
`hotel` 1건·`restaurant` 14건처럼 전용 아이콘이 아까운 kind 도 있다.
"""

from typing import Literal

IconGroup = Literal[
    "medical",   # 병원·약국 — 존재 권위는 place(인허가)
    "supply",    # 용품·미용
    "food",      # 카페·음식점
    "stay",      # 펜션·호텔·숙박
    "culture",   # 박물관·미술관·문예회관
    "outdoor",   # 여행지·레저
    "care",      # 위탁관리
    "etc",       # 미분류 — 매핑에 없는 새 kind
]

_GROUPS: dict[str, IconGroup] = {
    "hospital": "medical",
    "pharmacy": "medical",
    "goods": "supply",
    "grooming": "supply",
    "cafe": "food",
    "restaurant": "food",
    "pension": "stay",
    "hotel": "stay",
    "stay": "stay",
    "museum": "culture",
    "gallery": "culture",
    "arts_center": "culture",
    "culture": "culture",
    "travel": "outdoor",
    "leisure": "outdoor",
    "boarding": "care",
}


def icon_group(kind: str) -> IconGroup:
    return _GROUPS.get(kind, "etc")
