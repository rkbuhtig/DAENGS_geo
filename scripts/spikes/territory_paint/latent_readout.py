"""심은 자료를 **정답을 알고** 읽는다 — 채점자의 눈금을 확인하는 자리다.

검출이 아니다. 검출은 자리를 **모르는 채로** field 에서 찾아내는 것이고 그게 M3 다. 여기서는
정답 자리에 읽기 장치를 대 보고, 같은 장치를 field 전체에 훑어 그 분포와 견준다.

**그 견줌이 이 스크립트의 존재 이유다.** 정답 자리만 읽으면 값이 커 보이는지 아닌지를 알 수
없다 — field 어디에나 그만한 값이 널려 있으면 그 읽기는 아무것도 못 가린 것이다.

    uv run python -m scripts.spikes.territory_paint.latent_readout --json latent.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

from app.features.territory.dwell import (
    _cells_within,
    cell_spacing_m,
    contrast,
    read_at,
    route_baseline,
)
from app.features.territory.layers import (
    Aggregation,
    LayerSpec,
    Projection,
    Selector,
    render,
)
from app.features.territory.paint import NARROW_STEP, BrushProfile, flat
from app.geo.cells import cell_size_m, hex_center_latlng
from scripts.spikes.territory_paint.latent_dwell_year import load_sheets

BRUSHES = {b.name: b for b in
           (NARROW_STEP, BrushProfile("계단 3·8", (3.0, 8.0), (1.0, 0.45)), flat(6.0))}


def spec_for(brush: BrushProfile, radius_u: float) -> LayerSpec:
    return LayerSpec(selector=Selector.of(),
                     aggregation=Aggregation(metric="occupancy"),
                     projection=Projection(radius_u=radius_u, brush=brush.name,
                                           profile_fp=brush.fingerprint))


def quantile(values: list[float], share: float) -> float:
    return values[min(len(values) - 1, int(len(values) * share))]


def field_contrasts(layer, centres: dict, read_m: float, radius_u: float,
                    baseline: float) -> list[float]:
    """칠해진 칸마다 둘레를 적분해 얻은 대비. **기준선을 만든 그 계산 그대로**다."""
    return sorted(
        (sum(layer.canvas[c].occupancy
             for c in _cells_within(centres, centre, read_m, radius_u))
         / layer.selected) / baseline
        for centre in centres.values())


def concentration(layer, centres: dict, centre, read_m: float,
                  radius_u: float) -> tuple[float, float]:
    """(산책당 최고 칸, 최고 칸이 원반에서 차지하는 몫).

    **통과는 퍼지고 체류는 뭉친다**는 가정이 맞다면 여기서 갈려야 한다. 원반 합만 보면
    공간적으로 넓게 퍼진 통행이 한 자리에 뭉친 체류를 이긴다.
    """
    near = _cells_within(centres, centre, read_m, radius_u)
    values = [layer.canvas[c].occupancy for c in near]
    return max(values) / layer.selected, max(values) / sum(values)


def report(path: str, brush: BrushProfile, radius_u: float, read_m: float) -> None:
    spec = spec_for(brush, radius_u)
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    lat = payload["personas"][0]["home"][0]
    print(f"붓 {brush.name}(도달 {brush.reach_m:.0f}m) · 격자 {radius_u:.0f}단위"
          f"(칸 반지름 {cell_size_m(radius_u, lat):.1f}m · 중심 간격 "
          f"{cell_spacing_m(radius_u, lat):.1f}m) · 읽기 반경 {read_m:.0f}m")

    for person in payload["personas"]:
        sheets = load_sheets(path, person["id"], radius_u, brush)
        base = route_baseline(sheets, spec, read_m)
        layer = render(sheets, spec)
        centres = {c: hex_center_latlng(*c, radius_u) for c in layer.canvas}
        values = field_contrasts(layer, centres, read_m, radius_u, base.value)
        print(f"\n== {person['id']} ({person['kind']}) 기준선 {base.value:.1f} · 장 "
              f"{base.selected} · 칠한 칸 {len(values)}")
        print(f"   field 대비 분포  중앙 {statistics.median(values):.2f}  "
              f"p90 {quantile(values, 0.90):.2f}  p99 {quantile(values, 0.99):.2f}  "
              f"최대 {values[-1]:.2f}")

        peak = max(centres.values(), key=lambda ctr: sum(
            layer.canvas[c].occupancy for c in _cells_within(centres, ctr, read_m, radius_u)))
        rows = [("field 최고봉", peak, "심은 것 없음")]
        rows += [(f"{s['spot_id']} {s['kind']}", tuple(s["at"]),
                  f"{s['stopped']}/{s['planned']} 멈춤")
                 for s in person["truth_only"]["spots"]]
        for name, centre, truth in rows:
            reading = read_at(sheets, spec, centre, read_m)
            top, share = concentration(layer, centres, centre, read_m, radius_u)
            print(f"   {name:<14} 대비 {contrast(reading, base):>6.1f}x  "
                  f"등장 {reading.visit_rate * 100:>5.1f}%  "
                  f"갔을때 {reading.dwell_per_visit:>6.1f}  "
                  f"최고칸 {top:>5.1f}  집중 {share:>5.1%}   {truth}")

        kinds: dict[str, int] = {}
        for event in person["truth_only"]["events"]:
            kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
        print(f"   실제 사건 {len(person['truth_only']['events'])}: {kinds}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", required=True, help="latent_dwell_year 가 만든 자료")
    parser.add_argument("--brush", default=NARROW_STEP.name, choices=sorted(BRUSHES))
    parser.add_argument("--radius-u", type=float, default=8.0)
    parser.add_argument("--read-m", type=float, default=25.0)
    args = parser.parse_args(argv)
    report(args.json, BRUSHES[args.brush], args.radius_u, args.read_m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
