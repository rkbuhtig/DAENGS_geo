"""격자를 바꿔도 체류 총량이 보존되나 — 질량 보존 kernel 측정 (M0.5).

    uv run python -m scripts.spikes.territory_paint.mass_conserving_kernel

## 무엇을 묻나

[M0](../../../docs/research/2026-08-27-dwell-becomes-paint.md) 가 이걸 찾았다.

    2 분 머문 한 번 대 그냥 지나간 다섯 번
        15 단위   25.8 대 39.0   → 통과가 이긴다
         8 단위  131.6 대 60.2   → 체류가 이긴다

같은 물리 사건의 뜻이 격자 하나 바꿨다고 뒤집힌다. 그때 결론을 "그러니 촘촘한 격자를
고르자" 로 냈는데, **그건 증상을 보고 눈금을 고르는 것**이다. 먼저 물어야 할 것은 이거다.

> 이 역전이 정보 손실인가, 아니면 **이산화 방식**이 총량을 새게 하는 것인가.

## 왜 샐 것 같은가 — 코드가 이미 말한다

`brush_stamp` 은 도달 범위 안의 **모든 셀 중심에 가중치를 각각 더한다.** 정규화가 없다.
그러면 격자가 촘촘할수록 같은 밴드 안에 셀 중심이 더 많이 들어가서 **관측 하나가 뿌리는
총 질량 자체가 셀 밀도에 비례해 커진다.**

    관측 1 초가 뿌리는 총량 = Σ weight(중심까지 거리)     ← 셀 개수에 비례

즉 `occupancy` 는 "이 근방에 쌓인 시간" 이 아니라 "시간 × 격자 밀도" 였을 수 있다.

## 무엇을 견주나

    현행 kernel     지금 그대로 (정규화 없음)
    질량 보존 kernel  같은 모양인데 **가중치 합을 1 로 정규화**한 뒤 dt 를 곱한다

정규화하면 관측 1 초는 격자가 무엇이든 **총 1 초어치**를 뿌린다. 분배 모양만 달라진다.

`peak` 은 정규화하지 않는다. 둘이 **다른 질문**이라서다 —

    occupancy   정규화 질량 × dt      "얼마나 오래"    보존량
    peak        비정규화 kernel 최대   "얼마나 가까이"   [0,1] 유지

그래야 `min_peak` 계약(`stack`·`select`·`region_visit_rate`)이 그대로 산다.

## 이 스파이크는 코드를 안 고친다

`paint.py` 를 건드리기 전에 **숫자부터** 낸다. kernel 교체는 #69 의 세대 정책상 새 세대
(`profile_fp` 변경)라 되돌릴 수 없는 결정이고, 근거 없이 하지 않는다.
"""

import argparse
import math
import random
import sys
from datetime import UTC, datetime, timedelta

from app.features.territory.paint import NARROW_STEP, brush_stamp
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from app.geo.cells import Cell, cell_size_m, hex_center_latlng

EARTH_R = 6_371_000.0
LAT, LNG = 37.4979, 127.0276
START = datetime(2026, 7, 1, 9, tzinfo=UTC)
SPEED_MPS = 1.2
LEG_M = 120.0
GRIDS = (4.0, 8.0, 15.0)
STOP_S = 120


def _at(x_m: float, wobble: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    east, north = x_m + wobble[0], wobble[1]
    return (LAT + math.degrees(north / EARTH_R),
            LNG + math.degrees(east / (EARTH_R * math.cos(math.radians(LAT)))))


STOP_AT = _at(LEG_M / 2)


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(math.radians(b[1] - a[1]) * EARTH_R * math.cos(math.radians(LAT)),
                      math.radians(b[0] - a[0]) * EARTH_R)


def walk_fixes(stop_s: int, *, jitter_m: float, seed: int) -> list[WalkFix]:
    """동쪽 120m 를 1.2m/s 로, 한가운데서 `stop_s` 초 서 있는다. 1Hz."""
    rng = random.Random(seed)
    fixes: list[WalkFix] = []
    seconds = 0.0

    def push(x_m: float) -> None:
        nonlocal seconds
        wobble = ((rng.gauss(0, jitter_m), rng.gauss(0, jitter_m)) if jitter_m
                  else (0.0, 0.0))
        lat, lng = _at(x_m, wobble)
        fixes.append(WalkFix(client_seq=len(fixes), chain_index=0,
                             at=START + timedelta(seconds=seconds),
                             lat=lat, lng=lng, accuracy_m=5.0, is_mock=False))
        seconds += 1.0

    steps = int((LEG_M / 2) / SPEED_MPS)
    for i in range(steps + 1):
        push(i * SPEED_MPS)
    for _ in range(stop_s):
        push(LEG_M / 2)
    for i in range(1, steps + 1):
        push(LEG_M / 2 + i * SPEED_MPS)
    return fixes


def paint(fixes: list[WalkFix], radius_u: float, *, normalise: bool) -> dict[Cell, float]:
    """장 하나를 칠한다. `normalise` 가 이 스파이크의 유일한 변수다.

    `paint_sheet` 를 그대로 못 쓰는 이유는 정규화 갈래를 넣어야 해서다. 나머지 계산
    (조각 나누기·share)은 원본과 같게 뒀다 — 다른 것이 섞이면 비교가 안 된다.
    """
    computed = compute_facts("w", "d", START, fixes[-1].at + timedelta(seconds=1), fixes)
    step = max(min(radius_u, NARROW_STEP.bands[0]) / 2.0, 1.5)
    field: dict[Cell, float] = {}
    for seg in computed.segments:
        pieces = max(1, math.ceil(seg.dist / step))
        share = seg.dt / pieces
        for index in range(pieces):
            frac = (index + 0.5) / pieces
            lat = seg.a.lat + (seg.b.lat - seg.a.lat) * frac
            lng = seg.a.lng + (seg.b.lng - seg.a.lng) * frac
            stamp = brush_stamp(lat, lng, radius_u, NARROW_STEP)
            total = sum(w for _, w in stamp) if normalise else 1.0
            if total <= 0:
                continue
            for cell, weight in stamp:
                field[cell] = field.get(cell, 0.0) + share * weight / total
    return field


def mass_within(field: dict[Cell, float], radius_u: float, metres: float) -> float:
    """멈춘 자리 둘레 `metres` 안의 물감 총량. **셀 하나가 아니라 적분이다.**"""
    return sum(v for cell, v in field.items()
               if _metres(hex_center_latlng(*cell, radius_u), STOP_AT) <= metres)


def centroid_error(before: dict[Cell, float], after: dict[Cell, float],
                   radius_u: float) -> float:
    """멈춤으로 **늘어난** 물감의 무게중심이 실제 멈춘 자리에서 몇 m 떨어졌나."""
    gained = {c: after[c] - before.get(c, 0.0) for c in after}
    grown = {c: v for c, v in gained.items() if v > 0}
    if not grown:
        return float("nan")
    total = sum(grown.values())
    lat = sum(hex_center_latlng(*c, radius_u)[0] * v for c, v in grown.items()) / total
    lng = sum(hex_center_latlng(*c, radius_u)[1] * v for c, v in grown.items()) / total
    return _metres((lat, lng), STOP_AT)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jitter", type=float, default=0.0, help="GPS 지터 σ(m)")
    parser.add_argument("--passes", type=int, default=5, help="통과 비교용 산책 수")
    args = parser.parse_args(argv)

    print(f"멈춤 {STOP_S}초 · 통과 {args.passes}회 · 지터 σ={args.jitter:.0f}m · "
          f"붓 {NARROW_STEP.name}\n")

    for normalise in (False, True):
        title = "질량 보존 kernel" if normalise else "현행 kernel (정규화 없음)"
        print(f"=== {title} ===")
        print(f"  {'격자':>5}{'셀':>8}{'10m':>9}{'20m':>9}{'30m':>9}"
              f"{'최대 칸':>9}{'중심오차':>9}{'칸/산책':>8}   체류÷통과 산책당 (10m/20m/30m)")

        totals = []
        for radius_u in GRIDS:
            stopped = paint(walk_fixes(STOP_S, jitter_m=args.jitter, seed=7),
                            radius_u, normalise=normalise)
            passing = paint(walk_fixes(0, jitter_m=args.jitter, seed=7),
                            radius_u, normalise=normalise)
            stacked: dict[Cell, float] = {}
            for i in range(args.passes):
                for cell, v in paint(walk_fixes(0, jitter_m=args.jitter, seed=i),
                                     radius_u, normalise=normalise).items():
                    stacked[cell] = stacked.get(cell, 0.0) + v

            reads = [mass_within(stopped, radius_u, m) for m in (10.0, 20.0, 30.0)]
            # **산책당으로 나눈다.** 총량으로 견주면 5 회 통과가 5 회분 시간을 넣으니
            # 당연히 이긴다(5×33 = 165 대 120+33 = 153) — 그건 체류가 진 게 아니라
            # 내가 빈도와 체류를 총량 하나로 견준 것이다. 산책당이 dwell 축의 값이다.
            versus = [mass_within(stacked, radius_u, m) / args.passes
                      for m in (10.0, 20.0, 30.0)]
            verdicts = " ".join(f"{a / b:.1f}x" if b else "—"
                                for a, b in zip(reads, versus, strict=True))
            totals.append(reads[1])
            print(f"  {radius_u:5.0f}{cell_size_m(radius_u, LAT):7.1f}m"
                  f"{reads[0]:9.1f}{reads[1]:9.1f}{reads[2]:9.1f}"
                  f"{max(stopped.values()):9.1f}"
                  f"{centroid_error(passing, stopped, radius_u):8.1f}m"
                  f"{len(stopped):8d}   {verdicts}")

        print(f"  → 20m 총량이 격자에 따라 {max(totals) / min(totals):.1f} 배 흔들린다"
              f"{'  (보존되면 1.0)' if not normalise else ''}")

        print("  → 체류 시간 대비 총량 기울기 (0→240초, 20m 적분): "
              + " · ".join(f"{ru:.0f}u {summarise_slope(dwell_response(ru, normalise=normalise)):.2f}"
                           for ru in GRIDS))
        print()

def dwell_response(radius_u: float, *, normalise: bool, jitter_m: float = 0.0) -> list:
    """체류 시간에 총량이 비례하나 — 보존이 되면 기울기가 1 에 가까워야 한다."""
    out = []
    for stop_s in (0, 30, 60, 120, 240):
        field = paint(walk_fixes(stop_s, jitter_m=jitter_m, seed=7), radius_u,
                      normalise=normalise)
        out.append((stop_s, mass_within(field, radius_u, 20.0)))
    return out


def summarise_slope(rows: list) -> float:
    """(0초 → 240초) 총량 증가를 체류 증가로 나눈 값. 1.0 이면 시간이 그대로 쌓인 것."""
    return (rows[-1][1] - rows[0][1]) / (rows[-1][0] - rows[0][0])


if __name__ == "__main__":
    sys.exit(main())
