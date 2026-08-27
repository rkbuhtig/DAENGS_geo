"""심은 자료의 계약. `scripts/spikes/territory_paint/latent_dwell_year.py`.

**정답지가 자기 자신을 헷갈리게 만들지 않는지**를 본다. 합성 자료의 값어치는 "무엇이 참인지
우리가 안다" 는 것뿐이라, 그 앎이 흐려지면 실험 전체가 못 쓰게 된다.

    대조군에 A·D 가 없다        문턱의 출처가 오염되면 안 된다
    자리끼리 안 겹친다          겹치면 검출기가 뭘 찾았는지 우리도 못 가린다
    심은 것이 실제로 터진다     지나가기만 하고 안 멈추면 없는 것과 같다

여기서 붓·격자·검출은 안 본다 — 그건 M3 다.
"""

import math

import pytest

from scripts.spikes.territory_paint.latent_dwell_year import (
    SPOT_KINDS,
    Spot,
    lognormal_dwell,
    plant_spots,
    traversal_counts,
    walk_fixes,
)

EARTH_R = 6_371_000.0
LAT, LNG = 37.4979, 127.0276


def _metres(a, b) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot(math.radians(b[1] - a[1]) * EARTH_R * math.cos(lat),
                      math.radians(b[0] - a[0]) * EARTH_R)


def _node(x_m: float, y_m: float = 0.0):
    return (LAT + math.degrees(y_m / EARTH_R),
            LNG + math.degrees(x_m / (EARTH_R * math.cos(math.radians(LAT)))))


HOME = _node(0.0)


def _straight_route(length_m: float = 600.0, step: float = 20.0) -> list:
    """집에서 동쪽으로 뻗었다 돌아오는 왕복. 실제 생성기와 같은 모양이다."""
    out = [_node(i * step) for i in range(int(length_m / step) + 1)]
    return out + out[-2::-1]


def _graph_with_junctions(route: list, every: int = 6) -> tuple[dict, set]:
    """경로 위 몇 점을 차수 3 짜리 교차로로 만든 최소 그래프."""
    graph: dict = {}
    nodes = list(dict.fromkeys(route))
    for index, node in enumerate(nodes):
        neighbours = set()
        if index:
            neighbours.add(nodes[index - 1])
        if index + 1 < len(nodes):
            neighbours.add(nodes[index + 1])
        if index and index % every == 0:            # 곁가지 하나 — 차수 3
            spur = _node(index * 20.0, 30.0)
            neighbours.add(spur)
            graph.setdefault(spur, {node})
        graph[node] = neighbours
    return graph, set(graph)


ROUTE = _straight_route()
GRAPH, COMPONENT = _graph_with_junctions(ROUTE)
ROUTES = [ROUTE] * 20


def _plant(with_repeated: bool, seed: int = 3) -> list[Spot]:
    import random
    return plant_spots(ROUTES, GRAPH, COMPONENT, HOME, random.Random(seed),
                       with_repeated=with_repeated)


# ---- 대조군 ------------------------------------------------------------------------------


def test_the_control_group_has_no_repeated_dwell_planted():
    """**문턱의 출처**다. 여기 A·D 가 섞이면 거짓 양성의 바닥이 오염된다."""
    kinds = {s.kind for s in _plant(with_repeated=False)}
    assert kinds == {"B"}, f"대조군에 A·D 가 섞였다: {kinds}"


def test_the_control_group_still_has_structural_stops():
    """B 는 두 쪽 다 심는다 — 대조군에도 있어야 "A 를 찾았다" 가 "B 를 찾았다" 와 갈린다."""
    assert [s for s in _plant(with_repeated=False) if s.kind == "B"]


def test_the_planted_group_has_both():
    kinds = {s.kind for s in _plant(with_repeated=True)}
    assert {"A", "D"} <= kinds and "B" in kinds


# ---- 자리가 서로 안 겹친다 ---------------------------------------------------------------


def test_planted_spots_do_not_land_on_top_of_each_other():
    """**실제로 났던 문제의 회귀 테스트.**

    처음엔 B 를 심을 때 A·D 와의 거리를 안 봤다. 그래서 A1 과 B2 가 한 자리에 떨어졌고
    읽기 값이 소수점까지 같았다(둘 다 대비 22.29x · 갔을때체류 286.7). 그러면 검출기가
    무엇을 찾았는지 **우리도 못 가린다** — 정답지가 자기 자신을 헷갈리게 만든 셈이다.
    """
    spots = _plant(with_repeated=True)
    for i, one in enumerate(spots):
        for other in spots[i + 1:]:
            assert _metres(one.at, other.at) > 50.0, (
                f"{one.spot_id}({one.kind}) 와 {other.spot_id}({other.kind}) 가 "
                f"{_metres(one.at, other.at):.0f}m 로 붙었다")


def test_repeated_spots_avoid_the_doorstep():
    """집 앞은 모든 산책이 지난다 — 거기 심으면 "반복 체류" 와 "늘 지나는 길" 이 안 갈린다."""
    for spot in _plant(with_repeated=True):
        if spot.kind in ("A", "D"):
            assert _metres(spot.at, HOME) > 150.0


# ---- 심은 것이 실제로 터진다 --------------------------------------------------------------


def test_a_planted_spot_actually_fires_and_records_its_truth():
    """지나가기만 하고 안 멈추면 없는 것과 같다.

    처음에 긴 휴식 자리가 60 회 중 **5 회만 지나가서 한 번도 안 터졌다**(0/5). 자리를
    무작위 경로에서 골라서였고, 그래서 통행 빈도로 고르게 바꿨다 — **희소성은 `chance` 가
    만들어야지 경로 추첨이 만들면 안 된다.**
    """
    import random
    rng = random.Random(11)
    spot = Spot("A0", "A", tuple(_node(300.0)), **SPOT_KINDS["A"])
    for _ in range(20):
        walk_fixes(ROUTE, [spot], rng, None)

    assert spot.planned == 20, f"20 회 다 지나야 한다: {spot.planned}"
    assert 10 <= spot.stopped <= 20, f"확률 0.75 인데 {spot.stopped} 회 멈췄다"
    assert len(spot.dwells) == spot.stopped
    assert min(spot.dwells) > 0


def test_a_stop_makes_the_walk_longer_in_time_not_in_space():
    """멈춤은 fix 를 늘리지 좌표를 늘리지 않는다 — 그게 체류의 관측 형태다."""
    import random
    plain = walk_fixes(ROUTE, [], random.Random(5), None)
    spot = Spot("A0", "A", tuple(_node(300.0)), chance=1.0, dwell_median=120.0,
                spread=0.01)
    held = walk_fixes(ROUTE, [spot], random.Random(5), None)
    assert len(held) > len(plain) + 100, "멈춤이 fix 를 안 늘렸다"

    span = lambda fx: max(_metres((f[0], f[1]), HOME) for f in fx)
    assert span(held) == pytest.approx(span(plain), rel=0.25)


def test_dwell_is_lognormal_so_long_stops_are_rare_not_absent():
    """짧은 멈춤이 흔하고 긴 멈춤이 드물게 섞인다 — 평균만 맞추면 그 꼬리가 사라진다."""
    import random
    rng = random.Random(7)
    draws = sorted(lognormal_dwell(rng, 45.0, 0.45) for _ in range(400))
    median = draws[len(draws) // 2]
    assert 38.0 < median < 53.0
    assert draws[-1] > median * 2.5, "긴 꼬리가 없다"
    assert draws[0] >= 3.0, "0 초 멈춤이 나오면 안 된다"


# ---- 통행 빈도 ------------------------------------------------------------------------------


def test_traversal_counts_see_every_route():
    counts = traversal_counts(ROUTES)
    assert counts[tuple(HOME)] == len(ROUTES)
    assert max(counts.values()) == len(ROUTES)
