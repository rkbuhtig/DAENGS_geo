"""실제 도로망 위에 **잠재 미시 행동**을 심은 1 년치 — 대조군 포함 (M2).

    uv run python -m scripts.spikes.territory_paint.latent_dwell_year \\
        --cache osm.json --json latent.json

갈래는 [repeated-dwell-area](../../../docs/explorations/walk/repeated-dwell-area.md).

## 심는 것은 좌표와 행동이지 **답이 아니다**

이전 실험이 여기서 한 번 미끄러졌다. "도곡공원에 편향을 심고 도곡공원이라는 답을 받기" 는
발견이 아니라 순환이다 — 영역 이름을 우리가 정해 놓고 그 이름을 돌려받았으니까.

여기서는 **좌표에 행동만 심는다.**

    심는 것    이 좌표에서 재방문 확률 p 로 체류 시간 D 를 쓴다
    안 심는 것 그 결과로 field 가 어떤 모양이 될지, 어느 영역으로 묶일지

field 모양은 **우리도 모른다.** 붓·격자·지터·경로 반복이 함께 만들고, 검출기가 그걸 다시
영역으로 묶어 내는지가 M3 의 질문이다.

## 멈춤을 네 종류로 심는다 — **이름은 관측 가능한 것만**

    A  반복 체류    특정 좌표. 지날 때 확률 p 로 멈추고 체류가 길다
    B  구조적 정지  교차로. 지날 때 확률 q 로 짧게 (신호 대기 같은 것)
    C  우발 정지    매번 다른 자리. 드물고 중간 길이
    D  긴 휴식      아주 가끔, 아주 김. 자리는 고정

"냄새" 도 "신호등" 도 아니다. **B 를 구조적이라 부르는 것은 위치가 교차로라서**지 원인을
안다는 뜻이 아니다 — 원인은 M4 에서 지도 맥락이 설명한다.

## 대조군이 문턱의 출처다

    planted   A · B · C · D 를 다 심는다
    null      **A 와 D 를 안 심는다.** B · C 만

검출기가 null 에서 찾아내는 것이 **거짓 양성의 바닥**이고, 문턱은 그 위로 정해진다.
[회수 실험](../../../docs/research/2026-08-26-cellophane-recovery.md)이 ε 를 패턴 안 심은
A 페르소나에서 얻은 것과 같은 방법이다. 눈으로 "이 정도면 뚜렷하다" 를 판정하지 않는다.

**B 는 두 쪽에 다 심는다.** 구조적 정지는 어차피 반복 체류로 잡히므로, 대조군에도 있어야
"A 를 찾았다" 가 "B 를 찾았다" 와 구별된다.

## 정답지는 `truth_only` 아래에만 둔다

검출기는 이 키를 보면 안 된다. `persona_year` 가 같은 규율을 쓴다.
"""

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from app.features.territory.paint import paint_sheet
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from scripts.spikes.territory_paint.real_route import (
    build_graph,
    fetch,
    largest_component,
    metres,
    walks_from_home,
)

YEAR = 2026
WALK_SPEED_MPS = 1.2
FIX_HZ = 1.0
JITTER_M = 8.0

# 멈춤 종류별 성질. **관측 가능한 값만** — 원인은 안 적는다.
SPOT_KINDS = {
    #            지날 때 멈출 확률   체류 중앙(초)   체류 흩어짐
    "A": {"chance": 0.75, "dwell_median": 45.0, "spread": 0.45},
    "B": {"chance": 0.35, "dwell_median": 22.0, "spread": 0.30},
    "D": {"chance": 0.12, "dwell_median": 260.0, "spread": 0.35},
}
CASUAL_CHANCE = 0.30          # C — 산책마다 이 확률로 아무 데서나 한 번
CASUAL_DWELL = (18.0, 0.5)

# 멈춤으로 치는 거리. 경로 점이 이 안에 들어오면 그 자리에서 멈춘다.
TRIGGER_M = 12.0


@dataclass
class Spot:
    """심은 자리 하나. **정답지다** — 검출기에 안 보인다."""

    spot_id: str
    kind: str
    at: tuple[float, float]
    chance: float
    dwell_median: float
    spread: float
    planned: int = 0          # 이 자리를 지난 산책 수
    stopped: int = 0          # 그중 실제로 멈춘 수
    dwells: list = field(default_factory=list)


def lognormal_dwell(rng: random.Random, median: float, spread: float) -> float:
    """체류 시간. 로그정규 — 짧은 멈춤이 흔하고 긴 멈춤이 드물게 섞인다."""
    return max(3.0, median * math.exp(rng.gauss(0.0, spread)))


def densify(path: list) -> list:
    """경로를 1 초 간격 점으로. 1.2m/s 로 걷는다."""
    step = WALK_SPEED_MPS / FIX_HZ
    out = [path[0]]
    for a, b in pairwise(path):
        span = metres(a, b)
        pieces = max(1, int(span / step))
        for i in range(1, pieces + 1):
            frac = i / pieces
            out.append((a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac))
    return out


def junctions(graph: dict, component: set) -> list:
    """차수 3 이상인 노드 — 구조적 정지를 심을 자리."""
    return [n for n in component if len(graph.get(n, ())) >= 3]


def traversal_counts(routes: list) -> dict:
    """노드마다 몇 번의 산책이 지났나. 자리를 **통행 빈도로** 고르려고 센다."""
    counts: dict = {}
    for route in routes:
        for node in set(map(tuple, route)):
            counts[node] = counts.get(node, 0) + 1
    return counts


def plant_spots(routes: list, graph: dict, component: set, home, rng: random.Random,
                *, with_repeated: bool) -> list[Spot]:
    """자리를 고른다. **행동만 심고 결과 모양은 안 심는다.**

    **통행 빈도로 고른다.** 처음엔 무작위 경로의 40~80% 지점에서 골랐는데, 긴 휴식 자리가
    60 회 중 **5 회만 지나가서 한 번도 안 터졌다**(0/5). 자리가 드물게 지나는 가지에
    떨어지면 심어도 없는 것과 같다 — 희소성은 `chance` 가 만들어야지 경로 추첨이 만들면
    안 된다.

    집 근처(150m 안)는 뺀다. 모든 산책이 지나므로 거기 심으면 "반복 체류" 와 "늘 지나는
    길" 이 애초에 안 갈린다.
    """
    counts = traversal_counts(routes)
    walked = set(counts)
    busy = sorted(
        (n for n, c in counts.items()
         if c >= len(routes) * 0.35 and metres(n, home) > 150.0),
        key=lambda n: -counts[n])

    spots: list[Spot] = []
    if with_repeated and busy:
        picked: list = []
        for index, kind in enumerate(("A", "A", "D")):
            # 서로 겹치지 않게 — 같은 자리에 둘을 심으면 정답이 뭔지 우리도 못 가린다
            far = [n for n in busy
                   if all(metres(n, other) > 60.0 for other in picked)] or busy
            node = rng.choice(far[: max(3, len(far) // 2)])
            picked.append(node)
            spots.append(Spot(f"{kind}{index}", kind, tuple(node), **SPOT_KINDS[kind]))

    # B 는 두 쪽 다 심는다 — 대조군에도 있어야 "A 를 찾았다" 가 구별된다.
    # 여기도 통행이 있는 교차로만 — 안 지나는 교차로에 심으면 없는 것과 같다.
    #
    # **A·D 와 겹치면 안 된다.** 처음에 그 검사를 빼먹었더니 A1 과 B2 가 한 자리에 떨어져
    # 읽기 값이 소수점까지 같았다(둘 다 22.29x · 286.7). 그러면 검출기가 무엇을 찾았는지
    # 우리도 못 가린다 — 정답지가 자기 자신을 헷갈리게 만든 셈이다.
    taken = [s.at for s in spots]
    corners = sorted((n for n in junctions(graph, component)
                      if n in walked and counts[n] >= len(routes) * 0.2
                      and all(metres(n, other) > 60.0 for other in taken)),
                     key=lambda n: -counts[n])
    for index, node in enumerate(corners[:3]):
        spots.append(Spot(f"B{index}", "B", tuple(node), **SPOT_KINDS["B"]))
    return spots


def walk_fixes(path: list, spots: list[Spot], rng: random.Random,
               started_at: datetime) -> list[list]:
    """경로 하나 → fix 목록. 심은 자리를 지나면 그 자리에서 멈춘다.

    지터는 여기서 넣는다 — 관측 모델의 일부지 경로의 성질이 아니다.
    """
    dense = densify(path)
    used: set[str] = set()
    casual_at = (rng.randrange(len(dense)) if rng.random() < CASUAL_CHANCE else None)

    fixes: list[list] = []
    seconds = 0.0

    def emit(point, count: int = 1) -> None:
        nonlocal seconds
        for _ in range(count):
            dlat = math.degrees(rng.gauss(0, JITTER_M) / 6_371_000.0)
            dlng = math.degrees(rng.gauss(0, JITTER_M)
                                / (6_371_000.0 * math.cos(math.radians(point[0]))))
            fixes.append([round(point[0] + dlat, 6), round(point[1] + dlng, 6),
                          round(seconds)])
            seconds += 1.0 / FIX_HZ

    for index, point in enumerate(dense):
        emit(point)
        for spot in spots:
            if spot.spot_id in used or metres(point, spot.at) > TRIGGER_M:
                continue
            used.add(spot.spot_id)
            spot.planned += 1
            if rng.random() < spot.chance:
                held = lognormal_dwell(rng, spot.dwell_median, spot.spread)
                spot.stopped += 1
                spot.dwells.append(round(held, 1))
                emit(point, int(held * FIX_HZ))
        if index == casual_at:
            emit(point, int(lognormal_dwell(rng, *CASUAL_DWELL) * FIX_HZ))

    del started_at            # 시각은 호출자가 붙인다 — 여기는 상대 초만 낸다
    return fixes


def build(persona: str, kind: str, graph: dict, kinds: dict, component: set,
          home, walks: int, seed: int) -> dict | None:
    rng = random.Random(seed)
    routes = walks_from_home(graph, component, home, rng, walks)
    if not routes:
        return None
    spots = plant_spots(routes, graph, component, home, rng,
                        with_repeated=(kind == "planted"))

    out = []
    for index, route in enumerate(routes):
        started = (datetime(YEAR, 1, 1, tzinfo=UTC)
                   + timedelta(days=int(365 * index / max(1, len(routes))),
                               hours=rng.choice((8, 13, 18, 21)),
                               minutes=rng.randrange(60)))
        out.append({"walk_id": f"{persona}-{index:03d}",
                    "started_at": started.isoformat(),
                    "fixes": walk_fixes(route, spots, rng, started)})
    return {
        "id": persona, "kind": kind, "home": list(home), "walks": out,
        # ---- 정답지. 검출기는 이 아래를 보면 안 된다 ----
        "truth_only": {"spots": [asdict(s) for s in spots]},
    }


def to_fixes(walk: dict) -> list[WalkFix]:
    """저장된 fix 목록 → `WalkFix`. 지터는 이미 들어가 있다."""
    started = datetime.fromisoformat(walk["started_at"])
    return [WalkFix(client_seq=index, chain_index=0,
                    at=started + timedelta(seconds=offset),
                    lat=lat, lng=lng, accuracy_m=5.0, is_mock=False)
            for index, (lat, lng, offset) in enumerate(walk["fixes"])]


def load_sheets(path: str, persona: str, radius_u: float, profile) -> list:
    """자료 → 셀로판 장 목록. **`truth_only` 는 안 읽는다.**

    검출기 쪽에서 이걸 쓰면 정답지에 손이 닿을 일이 없다.
    """
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    person = next(p for p in payload["personas"] if p["id"] == persona)
    sheets = []
    for walk in person["walks"]:
        fixes = to_fixes(walk)
        started = fixes[0].at
        computed = compute_facts(walk["walk_id"], "spike", started,
                                 fixes[-1].at + timedelta(seconds=1), fixes)
        sheets.append(paint_sheet(walk["walk_id"], started, computed.segments,
                                  radius_u, profile))
    return sheets


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", help="Overpass 응답 캐시")
    parser.add_argument("--json", required=True, help="만든 자료를 쓸 경로")
    parser.add_argument("--walks", type=int, default=60, help="사람당 산책 수")
    args = parser.parse_args(argv)

    graph, kinds = build_graph(fetch(args.cache))
    component = largest_component(graph)
    homes = sorted(n for n in component if kinds.get(n) in ("service", "residential"))
    print(f"보행 그래프 노드 {len(graph)} · 최대 연결요소 {len(component)} · "
          f"교차로 {len(junctions(graph, component))} · 집 후보 {len(homes)}")

    made, used = [], set()
    for seed, (persona, kind) in enumerate((("P", "planted"), ("N", "null"))):
        for home in homes:
            if home in used:
                continue
            built = build(persona, kind, graph, kinds, component, home,
                          args.walks, seed=41 + seed)
            if built:
                made.append(built)
                used.add(home)
                break

    if len(made) < 2:
        print("집 후보에서 경로를 못 만들었다")
        return 1

    print(f"\n  {'':3}{'유형':<10}{'산책':>5}{'fix':>9}{'심은 자리':>10}   자리별 (멈춤/지남 · 체류 중앙)")
    for person in made:
        spots = person["truth_only"]["spots"]
        detail = " ".join(
            f"{s['spot_id']}:{s['stopped']}/{s['planned']}"
            f"·{statistics.median(s['dwells']) if s['dwells'] else 0:.0f}s"
            for s in spots)
        print(f"  {person['id']:<3}{person['kind']:<10}{len(person['walks']):>5}"
              f"{sum(len(w['fixes']) for w in person['walks']):>9}{len(spots):>10}   {detail}")

    payload = {
        "year": YEAR, "jitter_m": JITTER_M, "fix_hz": FIX_HZ,
        "speed_mps": WALK_SPEED_MPS, "trigger_m": TRIGGER_M,
        "spot_kinds": SPOT_KINDS, "personas": made,
    }
    with open(args.json, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    print(f"\n자료 → {args.json}")
    print("대조군 N 에는 A·D 가 없다 — 검출기가 거기서 찾아내는 것이 거짓 양성의 바닥이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
