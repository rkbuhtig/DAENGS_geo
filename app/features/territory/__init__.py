"""영역 — 산책 사실을 지도 위의 **장면**으로 바꾼다. walk 사실의 소비자다.

`features/walk/` 이 `Segment`·`WalkFacts` 를 생산하고 여기가 그것을 `geo.cells` 의 육각
격자에 얹는다. `features/scene/` 과 같은 자리다 — 생산자는 판정도 서술도 하지 않고
(결정 #51), 소비자가 규칙과 버전을 달고 만든다.

    paint.py    움직이는 점이 붓이 되어 칠한다 — Cellophane · stack
    region.py   사용자가 그린 면 안의 체류 — walk/encounter.py 의 면 버전
    layers.py   어떤 산책을 골라 어떤 장을 겹칠지 — 위 둘의 질의층

`geo/` 에 있었다. 셋 다 `features.walk.facts.Segment` 를 소비하는데 도메인 패키지에
앉아 있어서 `geo → features` 역방향이었고, 그 두 줄이 `discovery → journey → geo →
features → discovery` 4-패키지 순환을 닫는 마지막 고리였다 (결정 #67).

`geo/` 에는 산책을 모르는 공간 원시(`cells.py` 의 육각 격자 수학)만 남는다.
"""
