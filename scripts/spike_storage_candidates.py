"""§A 측정: 원좌표를 지운 뒤 무엇을 남길 것인가 — 후보 셋의 실제 값.

    uv run python -m scripts.spike_storage_candidates --personas personas.json \\
        --cache-sheets sheets.pkl

## 무엇을 묻나

결정 #57 이 연속 궤적을 finish 직후 purge 한다. 그러면 무엇을 남기나.
[territory-paint §A](../docs/explorations/walk/territory-paint.md) 가 후보 셋을 열어 뒀는데,
거기 적힌 "~80점 / ~200행" 은 **추정이지 실측이 아니다.** 근거 없는 숫자를 결정에 박지 않는
레포에서 그대로 결정 문서로 넘길 수 없다.

    A. 단순화 궤적    chain 마다 Douglas-Peucker
    B. 셀 맵 + 시각   칸마다 물감·최대세기·첫/마지막 시각
    C. 셀 맵, 집계만  칸마다 물감·최대세기

**A 를 "산책당 폴리라인 하나" 로 하지 않는다.** 그렇게 하면 pause·gap·jump 로 끊긴 자리를
선으로 잇게 되고, 그건 `session-continuity-and-dwell` §7 이 금지한 바로 그 오류다 —
관측하지 않은 이동을 지어낸다. chain 마다 따로 단순화하고 chain 경계를 보존한다.

## 재는 축 넷

    저장량      실제 점/행 수와 연 환산 (개 한 마리, 1,000 회)
    재투영      다른 붓·다른 셀로 다시 칠할 수 있나, 그때 오차는
    순서        방문 순서를 되짚을 수 있나
    집 노출     그 형태만으로 집을 얼마나 정확히 찍을 수 있나

뒤 둘이 "갈리는 축은 셀이냐 선이냐가 아니라 순서를 남기느냐" 를 숫자로 바꾼 것이다.
그 정리는 리뷰에서 나온 가설이고, 여기서 처음 잰다.
"""

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

from app.geo.cells import cell_size_m, hex_center_latlng
from app.geo.paint import paint_sheet
from scripts.spike_paint import segments_for
from scripts.spike_persona_experiment import PROFILE, RADIUS_U, load

EARTH_R = 6_371_000.0
WALKS_PER_YEAR = 1000          # 하루 2~3 회. 연 환산의 기준
SIMPLIFY_TOLERANCES = (2.0, 5.0, 10.0, 20.0)


def ground_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot(
        math.radians(b[1] - a[1]) * EARTH_R * math.cos(lat),
        math.radians(b[0] - a[0]) * EARTH_R,
    )


def _perp_m(point, start, end) -> float:
    """선분에서 점까지의 수직 거리(m). 등장방형 — 산책 반경에서 오차는 cm 급."""
    lat0 = start[0]
    cos_lat = math.cos(math.radians(lat0))

    def xy(p):
        return (math.radians(p[1] - start[1]) * EARTH_R * cos_lat,
                math.radians(p[0] - lat0) * EARTH_R)

    px, py = xy(point)
    ax, ay = xy(start)
    bx, by = xy(end)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def douglas_peucker(points: list, tolerance: float) -> list:
    """고전 단순화. 끝점은 항상 남는다."""
    if len(points) < 3:
        return list(points)
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _perp_m(points[i], points[0], points[-1])
        if d > worst:
            worst, index = d, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    left = douglas_peucker(points[: index + 1], tolerance)
    right = douglas_peucker(points[index:], tolerance)
    return left[:-1] + right


def simplify_by_chain(segments, tolerance: float) -> list[list]:
    """**chain 마다** 따로 단순화한다. chain 을 가로질러 잇지 않는다.

    산책 하나를 폴리라인 하나로 접으면 pause·gap·jump 자리가 선이 되고, 그것은 관측하지
    않은 이동을 지어내는 것이다(§7). 그래서 반환값도 폴리라인 **목록**이다.
    """
    chains: dict[int, list] = {}
    for seg in segments:
        run = chains.setdefault(seg.chain_index, [])
        if not run:
            run.append((seg.a.lat, seg.a.lng))
        run.append((seg.b.lat, seg.b.lng))
    return [douglas_peucker(run, tolerance) for run in chains.values() if len(run) >= 2]


@dataclass
class Candidate:
    name: str
    units: str
    per_walk: float
    numbers_per_walk: float
    reprojectable: bool
    keeps_order: bool


def repaint_error(original, polylines, radius_u, profile) -> float:
    """단순화한 선으로 다시 칠하면 원본 칠과 얼마나 다른가 (칸 집합 Jaccard 거리)."""
    from app.features.walk.facts import Segment
    from app.features.walk.models import WalkFix

    fake: list[Segment] = []
    base = original[0].a.at if original else datetime.now(UTC)
    for chain, line in enumerate(polylines):
        for i in range(len(line) - 1):
            a = WalkFix(client_seq=i, chain_index=chain, at=base,
                        lat=line[i][0], lng=line[i][1], accuracy_m=5.0, is_mock=False)
            b = WalkFix(client_seq=i + 1, chain_index=chain, at=base,
                        lat=line[i + 1][0], lng=line[i + 1][1], accuracy_m=5.0, is_mock=False)
            dist = ground_m(line[i], line[i + 1])
            fake.append(Segment(a=a, b=b, dt=dist / 1.2, dist=dist,
                                offset_m=0.0, moving=True, chain_index=chain))
    if not fake:
        return 1.0
    before = set(paint_sheet("o", base, original, radius_u, profile).occupancy)
    after = set(paint_sheet("s", base, fake, radius_u, profile).occupancy)
    union = before | after
    return 1.0 - len(before & after) / len(union) if union else 0.0


def shuffled_baseline(sheet, radius_u: float, truth_order: list, rng) -> float:
    """무작위 순서의 이웃 일치율. 재구성 점수가 이것보다 나은지 봐야 뜻이 있다."""
    cells = list(sheet.occupancy)
    if len(cells) < 3:
        return 0.0
    rng.shuffle(cells)
    truth_pairs = {frozenset(p) for p in pairwise(truth_order)}
    if not truth_pairs:
        return 0.0
    guess_pairs = {frozenset(p) for p in pairwise(cells)}
    return len(truth_pairs & guess_pairs) / len(truth_pairs)


def order_recovery(sheet, radius_u: float, truth_order: list) -> float:
    """집계만 남은 칸 집합에서 방문 **순서**를 되짚을 수 있나.

    최근접 이웃으로 칸을 이어 경로를 재구성하고, 실제 방문 순서와 얼마나 맞는지 본다.
    지표는 켄달 타우가 아니라 **이웃 일치율** — 재구성한 이웃 쌍이 실제로도 이웃이었나.
    순서가 남아 있으면 1 에 가깝고, 사라졌으면 우연 수준으로 떨어진다.
    """
    cells = list(sheet.occupancy)
    if len(cells) < 3:
        return 0.0
    coords = {c: hex_center_latlng(*c, radius_u) for c in cells}
    start = min(cells)
    walk, remaining = [start], set(cells) - {start}
    while remaining:
        last = coords[walk[-1]]
        nxt = min(remaining, key=lambda c: (ground_m(last, coords[c]), c))
        walk.append(nxt)
        remaining.discard(nxt)

    truth_pairs = {frozenset(p) for p in pairwise(truth_order)}
    if not truth_pairs:
        return 0.0
    guess_pairs = {frozenset(p) for p in pairwise(walk)}
    return len(truth_pairs & guess_pairs) / len(truth_pairs)


def first_seen_cells(segments, radius_u: float) -> dict:
    """칸마다 처음 관측된 시각.

    `Cellophane` 은 이걸 안 들고 있다 — occupancy 와 peak 뿐이다. 후보 B("셀 맵 + 시각")를
    재려면 여기서 따로 만들어야 한다는 사실 자체가 측정 결과의 일부다: 시각을 남기려면
    지금 저장 형태에 **없는 것을 더해야** 한다.
    """
    from app.geo.cells import hex_cell

    first: dict = {}
    for seg in segments:
        cell = hex_cell(seg.a.lat, seg.a.lng, radius_u)
        if cell not in first:
            first[cell] = seg.a.at
    return first


def home_exposure_trajectory(segments, home: tuple[float, float]) -> float:
    """A. 궤적을 남기면 — 첫 점이 곧 출발지다. 오차는 GPS 지터뿐."""
    if not segments:
        return float("nan")
    return ground_m((segments[0].a.lat, segments[0].a.lng), home)


def home_exposure_first_cell(segments, radius_u: float, home: tuple[float, float]) -> float:
    """B. 셀 맵 + 시각을 남기면 — 가장 이른 칸이 출발지다. 오차에 셀 크기가 더해진다."""
    first = first_seen_cells(segments, radius_u)
    if not first:
        return float("nan")
    cell = min(first, key=lambda c: (first[c], c))
    return ground_m(hex_center_latlng(*cell, radius_u), home)


def home_exposure_occupancy(sheet, radius_u: float, home: tuple[float, float]) -> float:
    """C. 집계만 남기면 — 물감이 가장 많은 칸을 찍는 수밖에 없다."""
    if not sheet.occupancy:
        return float("nan")
    cell = max(sheet.occupancy, key=lambda c: (sheet.occupancy[c], c))
    return ground_m(hex_center_latlng(*cell, radius_u), home)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--personas", required=True)
    parser.add_argument("--cache-sheets")
    parser.add_argument("--sample", type=int, default=14, help="페르소나당 표본 산책 수")
    parser.add_argument("--json", help="측정값을 쓸 경로")
    args = parser.parse_args(argv)

    with open(args.personas, encoding="utf-8") as handle:
        source = json.load(handle)
    homes = {e["id"]: tuple(e["home"]) for e in source["personas"]}
    routes = {e["id"]: [w["route"] for w in e["walks"]] for e in source["personas"]}

    people = load(args.personas, args.cache_sheets)
    cell_m = cell_size_m(RADIUS_U, next(iter(homes.values()))[0])
    print(f"격자 {RADIUS_U:.0f} 단위(실제 {cell_m:.1f}m) · 붓 {PROFILE.name} · "
          f"연 환산 {WALKS_PER_YEAR} 회 기준\n")

    rng = random.Random(4)
    points_by_tol: dict[float, list[int]] = {t: [] for t in SIMPLIFY_TOLERANCES}
    clean_by_tol: dict[float, list[int]] = {t: [] for t in SIMPLIFY_TOLERANCES}
    baseline_scores: list[float] = []
    error_by_tol: dict[float, list[float]] = {t: [] for t in SIMPLIFY_TOLERANCES}
    chains_per_walk: list[int] = []
    cells_per_walk: list[int] = []
    order_scores: list[float] = []
    home_by_occ: list[float] = []
    home_by_first: list[float] = []
    home_by_traj: list[float] = []

    for person in people:
        picks = rng.sample(range(len(person.sheets)), min(args.sample, len(person.sheets)))
        raw = routes[person.persona]
        for index in picks:
            segments = segments_for([tuple(p) for p in raw[index]], rng)
            if not segments:
                continue
            sheet = paint_sheet("m", segments[0].a.at, segments, RADIUS_U, PROFILE)
            cells_per_walk.append(len(sheet.occupancy))
            chains_per_walk.append(len({s.chain_index for s in segments}))

            for tol in SIMPLIFY_TOLERANCES:
                lines = simplify_by_chain(segments, tol)
                points_by_tol[tol].append(sum(len(line) for line in lines))
                error_by_tol[tol].append(repaint_error(segments, lines, RADIUS_U, PROFILE))
                # 지터 없는 원 경로를 같은 자로 재서 "못 줄이는 이유" 를 가른다
                clean = douglas_peucker([tuple(p) for p in raw[index]], tol)
                clean_by_tol[tol].append(len(clean))

            truth: list = []
            seen = set()
            for seg in segments:                       # 실제 방문 순서 (칸 단위)
                from app.geo.cells import hex_cell
                cell = hex_cell(seg.a.lat, seg.a.lng, RADIUS_U)
                if cell not in seen:
                    seen.add(cell)
                    truth.append(cell)
            order_scores.append(order_recovery(sheet, RADIUS_U, truth))
            baseline_scores.append(shuffled_baseline(sheet, RADIUS_U, truth, rng))
            home = homes[person.persona]
            home_by_traj.append(home_exposure_trajectory(segments, home))
            home_by_first.append(home_exposure_first_cell(segments, RADIUS_U, home))
            home_by_occ.append(home_exposure_occupancy(sheet, RADIUS_U, home))

    med = statistics.median
    print("=== A. chain 당 단순화 궤적 ===")
    print(f"  {'허용오차':>8} {'점/산책':>9} {'지터없으면':>10} {'재도색 오차':>12} {'연 저장(숫자)':>14}")
    for tol in SIMPLIFY_TOLERANCES:
        pts = med(points_by_tol[tol])
        clean = med(clean_by_tol[tol])
        err = med(error_by_tol[tol])
        print(f"  {tol:7.0f}m {pts:9.0f} {clean:10.0f} {err:11.1%} "
              f"{pts * 2 * WALKS_PER_YEAR:13,.0f}")
    print("  ↑ 두 열의 차이가 GPS 지터가 만든 점이다 — 경로가 복잡해서 못 줄이는 것이 아니다")

    cells = med(cells_per_walk)
    print(f"\n=== B·C. 셀 맵 (칸 {cells:.0f}/산책, chain {med(chains_per_walk):.0f}) ===")
    print(f"  B 시각 포함  칸당 숫자 4 (물감·세기·첫·마지막) → 연 {cells * 4 * WALKS_PER_YEAR:,.0f}")
    print(f"  C 집계만     칸당 숫자 2 (물감·세기)          → 연 {cells * 2 * WALKS_PER_YEAR:,.0f}")

    print("\n=== 순서를 되짚을 수 있나 (C. 집계만 남았을 때) ===")
    guess, chance = med(order_scores), med(baseline_scores)
    print(f"  최근접 이웃 재구성   {guess:6.1%}")
    print(f"  무작위 순서(기준선)  {chance:6.1%}")
    print(f"  → 우연 대비 {guess / chance:.1f} 배" if chance
          else "  → 기준선이 0 이라 배수를 못 낸다")

    print("\n=== 집이 얼마나 드러나나 (산책 한 번의 형태만으로) ===")
    print(f"  A 궤적       첫 점        → {med(home_by_traj):7.1f}m")
    print(f"  B 셀맵+시각  가장 이른 칸 → {med(home_by_first):7.1f}m")
    print(f"  C 집계만     물감 최대 칸 → {med(home_by_occ):7.1f}m")

    if args.json:
        payload = {
            "grid": {"radius_u": RADIUS_U, "cell_m": cell_m, "brush": PROFILE.name},
            "walks_per_year": WALKS_PER_YEAR,
            "simplify": {str(t): {"points": med(points_by_tol[t]),
                                  "repaint_error": med(error_by_tol[t])}
                         for t in SIMPLIFY_TOLERANCES},
            "cells_per_walk": cells,
            "order_recovery": med(order_scores),
            "order_baseline": med(baseline_scores),
            "simplify_clean": {str(t): med(clean_by_tol[t]) for t in SIMPLIFY_TOLERANCES},
            "home_by_trajectory_m": med(home_by_traj),
            "home_by_first_cell_m": med(home_by_first),
            "home_by_occupancy_m": med(home_by_occ),
            "sample_walks": len(cells_per_walk),
        }
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"\n측정값 → {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
