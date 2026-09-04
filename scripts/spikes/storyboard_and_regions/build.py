"""Build a self-contained storyboard from synthetic walks and local source snapshots."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from scripts.spikes.storyboard_and_regions.geometry import Regions
from scripts.spikes.storyboard_and_regions.sources import (
    collect_defaults,
    collect_water_geometry,
    fingerprint,
    service_key,
)

# Hand-drawn story scenario, not road routing, actual user activity, or navigation advice.
WAYPOINTS = [
    [127.0448, 37.4878], [127.0463, 37.4889], [127.0500, 37.4894],
    [127.0533, 37.4891], [127.05633, 37.48928], [127.0570, 37.4876],
    [127.0561, 37.4853], [127.0540, 37.4843], [127.0502, 37.4827],
    [127.0475, 37.4843], [127.0488, 37.4861], [127.0500, 37.4877],
]
BOUNDS = (127.041, 37.480, 127.061, 37.493)


def scenario_spec(with_gap: bool = False):
    from scripts.sim.walk.spec import WalkTraceScenarioSpec

    lng, lat = WAYPOINTS[0]
    xy = [[math.radians(x-lng)*6_371_000*math.cos(math.radians(lat)),
           math.radians(y-lat)*6_371_000] for x, y in WAYPOINTS]
    return WalkTraceScenarioSpec.model_validate({
        "format": "walk-trace-scenario-v1", "seed": 904, "dog_id": "storyboard-fixture",
        "started_at": "2026-09-04T18:00:00+09:00", "origin": {"lat": lat, "lng": lng},
        "route": {"name": "hand-drawn-dogok-loop", "points_xy": xy},
        "motion": {"name": "evening-storyboard", "base_speed_mps": 1.25,
                   "holds": [{"progress_m": 1020, "duration_s": 35}]},
        "sensor": {"kind": "perfect", "sample_interval_s": 5, "accuracy_m": 3},
        "faults": ([{"kind": "dropout", "id": "missing-observations",
                     "start_s": 1000, "end_s": 1180}] if with_gap else []),
    })


def project_context(snapshots: dict, regions: Regions, water: dict) -> dict:
    """Project the minimum public fields; omit service keys, addresses and contact fields."""
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform

    parks = []
    shops = []
    for source, xkey, ykey, destination in (
        ("parks", "longitude", "latitude", parks), ("commerce", "lon", "lat", shops),
    ):
        for row in snapshots[source]["rows"]:
            try:
                lng, lat = float(row[xkey]), float(row[ykey])
            except (KeyError, ValueError, TypeError):
                continue
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                continue
            item = {"point": [lng, lat], "xy": regions.forward(lng, lat)}
            if source == "parks":
                item.update(id=row.get("manageNo"), name=row.get("parkNm"),
                            kind=row.get("parkSe"), reference_date=row.get("referenceDate"))
            else:
                item.update(id=row.get("bizesId"), category=row.get("indsLclsNm") or "미분류")
            destination.append(item)
    transformer = Transformer.from_crs(3857, 5179, always_xy=True).transform
    water_shapes = []
    for feature in water.get("features", []):
        geom = transform(transformer, shape(feature["geometry"]))
        if not geom.is_valid:
            continue
        water_shapes.append({"name": feature.get("properties", {}).get("name", "이름 없음"),
                             "shape": geom})
    river_names = {r.get("rvrNm", "") for r in snapshots["rivers"]["rows"]}
    return {"parks": parks, "shops": shops, "water": water_shapes,
            "river_names": river_names, "snapshots": snapshots, "water_receipt": water,
            "water_geojson": [{"type": "Feature", "properties": {"name": r["name"]},
                               "geometry": mapping(transform(regions.reverse, r["shape"]))}
                              for r in water_shapes]}


def context_at(point: list[float], context: dict, regions: Regions) -> dict:
    from shapely.geometry import Point

    xy = regions.forward(*point)
    distance = lambda item: math.dist(xy, item["xy"])
    parks = sorted(context["parks"], key=distance)
    park = parks[0] if parks and distance(parks[0]) <= 250 else None
    nearby = [s for s in context["shops"] if distance(s) <= 125]
    commerce_receipt = context["snapshots"]["commerce"]
    query = commerce_receipt["query"]
    contained = math.dist(xy, regions.forward(float(query["cx"]), float(query["cy"]))) + 125
    commerce_complete = (commerce_receipt["status"] == "known"
                         and contained <= float(query["radius"]))
    waters = sorted(context["water"], key=lambda w: w["shape"].distance(Point(xy)))
    water = waters[0] if waters and waters[0]["shape"].distance(Point(xy)) <= 250 else None
    return {
        "park": ({k: park[k] for k in ("id", "name", "kind", "point", "reference_date")}
                 | {"distance_m": round(distance(park))} if park else None),
        "park_status": context["snapshots"]["parks"]["status"],
        "commerce": {"count": len(nearby), "radius_m": 125,
                     "categories": dict(Counter(s["category"] for s in nearby).most_common(3)),
                     "complete": commerce_complete},
        "water": ({"name": water["name"],
                   "distance_m": round(water["shape"].distance(Point(xy))),
                   "geometry_source": "EGIS",
                   "standard_name_present": water["name"] in context["river_names"]}
                  if water else None),
        "river_status": context["snapshots"]["rivers"]["status"],
    }


def build_story(regions: Regions, context: dict, *, with_gap=False, with_pin=True) -> dict:
    from scripts.sim.walk.bundle import build_scenario_from_spec

    spec = scenario_spec(with_gap)
    artifacts = build_scenario_from_spec(spec)
    computed = artifacts.computed
    start = computed.facts.started_at
    fixes = computed.receipt_input.accepted_fixes
    duration = (computed.facts.ended_at - start).total_seconds()
    runs = regions.ordered_runs(computed.trail.segments, start)

    def fix_at(seconds):
        return min(fixes, key=lambda f: abs((f.at-start).total_seconds()-seconds))

    scenes = []

    def scene(at, kind, title, text, evidence, focus=None):
        fix = fix_at(at)
        point = focus or [fix.lng, fix.lat]
        scenes.append({"at_s": round(at, 3), "kind": kind, "title": title, "text": text,
                       "evidence": evidence, "point": point,
                       "region": regions.locate(*point, fix.accuracy_m or 0),
                       "context": context_at(point, context, regions)})

    scene(0, "start", "오늘의 산책이 시작된다", "걸음과 동네, 중간에 남긴 장면을 따라가 볼까요.",
          ["합성 산책 · 기존 Walk 계산기", "동네 · SGIS 2025-06-30"])
    seen_regions = set()
    for run in runs:
        if run["status"] != "known" or run["end_s"]-run["start_s"] < 60:
            continue
        name = run["regions"][0]["name"]
        if run["start_s"] == 0:
            seen_regions.add(name)
            continue
        title = f"다시 만난 {name}" if name in seen_regions else f"{name}의 한 구간"
        seen_regions.add(name)
        scene(run["start_s"]+20, "region", title,
              f"기록된 경로가 {name} 경계 안으로 이어져요.",
              ["SGIS 센서스 경계 × 합성 관측 경로", "구간 시각은 관측점 사이 선형 보간"])

    # Context scenes use observed samples, not invisible ground-truth during a gap.
    park_fix = min(fixes, key=lambda f: math.dist(regions.forward(f.lng, f.lat),
                                                regions.forward(127.05633, 37.48928)))
    at = (park_fix.at-start).total_seconds()
    ctx = context_at([park_fix.lng, park_fix.lat], context, regions)
    if ctx["park"]:
        name = ctx["park"]["name"]
        scene(at, "park", f"{name} 가까이",
              f"공원 대표 좌표에서 약 {ctx['park']['distance_m']}m인 관측점이에요. "
              "공원 안에 들어갔는지는 이 자료만으로 알 수 없어요.",
              ["전국도시공원정보 · 대표점까지 직선거리", "입장·이용·반려견 동반 허용은 미확인"])
    if with_pin:
        scene(at+10, "pin", "잠깐, 이 장면을 남기자", "“여기서 같이 찍은 순간을 남겼다.”",
              ["시나리오로 만든 Pin 메모", "실제 사용자 메모·사진 아님"])

    shop_candidates = []
    for fix in fixes[::12]:
        ctx = context_at([fix.lng, fix.lat], context, regions)
        if ctx["commerce"]["complete"]:
            shop_candidates.append((ctx["commerce"]["count"], fix))
    if shop_candidates:
        count, fix = max(shop_candidates, key=lambda pair: pair[0])
        scene((fix.at-start).total_seconds(), "commerce", "주변에는 어떤 가게가 있을까",
              f"이 관측점 반경 125m의 수집 자료에는 상가 {count}개가 등록되어 있어요. "
              "지나친 풍경을 설명하는 단서예요.",
              ["소상공인시장진흥공단 · 등록 상가", "현재 영업·방문·혼잡도는 미확인"])

    water_candidates = []
    for fix in fixes[::12]:
        ctx = context_at([fix.lng, fix.lat], context, regions)
        if ctx["water"]:
            water_candidates.append((ctx["water"]["distance_m"], fix, ctx["water"]))
    if water_candidates:
        distance, fix, water = min(water_candidates, key=lambda pair: pair[0])
        name = water["name"]
        scene((fix.at-start).total_seconds(), "water", f"{name} 주변의 장면",
              f"EGIS 하천 경계에서 약 {distance}m인 관측점이에요. "
              "하천 산책로를 걸었는지까지 판정하지는 않아요.",
              ["EGIS 하천 형상 · 보조 출처", "전국하천표준데이터와 별도 출처"])

    for gap in computed.trail.gaps:
        seconds = (gap.a.at-start).total_seconds()
        scene(seconds, "gap", "이 사이의 걸음은 보이지 않는다",
              f"약 {round(gap.dt)}초 동안 관측이 비었어요. 이동·체류·동네 통과를 만들어내지 않아요.",
              ["Walk CanonicalTrail.gaps", "누락 구간을 경로 선으로 연결하지 않음"],
              [gap.a.lng, gap.a.lat])

    scene(duration-20, "game", "동네 게임의 결과를 붙인다면", "시나리오 결과: 영역 2칸 획득.",
          ["독립된 게임 결과 fixture", "산책 거리·행정동 진입으로 계산한 보상 아님"])
    distance = artifacts.derived["facts"]["moving_distance_m"]
    scene(duration, "end", "한 바퀴가 장면으로 남았다",
          f"관측으로 계산한 이동거리 {distance/1000:.2f}km. "
          "남아 있는 기록의 순서대로 오늘의 흐름을 마무리해요.", ["기존 WalkFacts 이동거리"])
    scenes.sort(key=lambda s: s["at_s"])
    for number, shot in enumerate(scenes):
        shot["id"] = f"scene-{number+1}"
    return {"name": "기록이 끊긴 산책" if with_gap else "기본 산책" if with_pin else "Pin 없는 산책",
            "synthetic": True, "spec": spec.model_dump(mode="json"),
            "duration_s": duration, "facts": artifacts.derived["facts"],
            "quality": artifacts.derived["quality"], "runs": runs, "scenes": scenes,
            "segments": [{"a": [s.a.lng, s.a.lat], "b": [s.b.lng, s.b.lat],
                          "start_s": (s.a.at-start).total_seconds(),
                          "end_s": (s.b.at-start).total_seconds()} for s in computed.trail.segments],
            "gaps": [{"start_s": (g.a.at-start).total_seconds(), "duration_s": g.dt}
                     for g in computed.trail.gaps]}


def build_bundle(regions: Regions, snapshots: dict, water: dict) -> dict:
    context = project_context(snapshots, regions, water)
    # Restrict distance calculations to the display corridor; polygons retain original edges.
    from shapely.geometry import box

    window = box(*regions.forward(BOUNDS[0], BOUNDS[1]),
                 *regions.forward(BOUNDS[2], BOUNDS[3])).buffer(500)
    regions.polygons = [(r, p) for r, p in regions.polygons if p.intersects(window)]
    stories = [build_story(regions, context),
               build_story(regions, context, with_gap=True),
               build_story(regions, context, with_pin=False)]
    river_rows = snapshots["rivers"]["rows"]
    receipts = {name: {k: v for k, v in data.items() if k != "rows"}
                | {"collected_rows": len(data["rows"])} for name, data in snapshots.items()}
    receipts["rivers"]["local_names_missing"] = [
        name for name in ("양재천", "탄천") if not any(r.get("rvrNm") == name for r in river_rows)
    ] if snapshots["rivers"]["status"] == "known" else None
    receipts["rivers"]["rows_with_start_coordinate"] = sum(
        bool(r.get("bgngPstnLat") and r.get("bgngPstnLot")) for r in river_rows)
    bundle = {"format": "storyboard-regions-spike-v1", "bounds": BOUNDS,
              "regions": regions.display_features(BOUNDS), "region_receipt": regions.receipt,
              "parks": [{k: r[k] for k in ("name", "point", "reference_date")}
                        for r in context["parks"] if BOUNDS[0] <= r["point"][0] <= BOUNDS[2]
                        and BOUNDS[1] <= r["point"][1] <= BOUNDS[3]],
              "water": context["water_geojson"],
              "water_receipt": {k: v for k, v in water.items() if k != "features"},
              "sources": receipts, "stories": stories,
              "narrator": "deterministic-templates-v1; no LLM call",
              "limitations": ["합성 산책·Pin·게임 결과. 실제 주변 공공데이터와 결합한 개발 실험",
                              "사진·실시간 행사·날씨·반려견 출입 정보는 수집하지 않음",
                              "지오 경로·스토리보드의 운영 저장 계약은 미승인",
                              "SGIS 활용 결과 사본 제출 필요 · 경계 기준 2025-06-30"]}
    bundle["fingerprint"] = fingerprint(bundle)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary-zip", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--fetch", action="store_true", help="Permit missing source fetches")
    parser.add_argument("--refresh", action="store_true", help="Refetch; requires --fetch")
    args = parser.parse_args()
    if args.refresh and not args.fetch:
        parser.error("--refresh requires --fetch")
    if args.fetch:
        snapshots = collect_defaults(args.cache_dir, service_key(args.env_file),
                                     refresh=args.refresh)
        water = collect_water_geometry(args.cache_dir, refresh=args.refresh)
    else:
        # Exact expected request fingerprints, no glob-based selection of arbitrary snapshots.
        queries = {"parks": {"instt_nm": "서울특별시 강남구"}, "rivers": {},
                   "commerce": {"cx": 127.052, "cy": 37.487, "radius": 1200}}
        snapshots = {name: json.loads((args.cache_dir /
                     f"{name}-{fingerprint(query)[:16]}.json").read_text(encoding="utf-8"))
                     for name, query in queries.items()}
        water = json.loads((args.cache_dir / "egis-water-receipt.json").read_text(encoding="utf-8"))
    bundle = build_bundle(Regions.from_zip(args.boundary_zip), snapshots, water)
    args.out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    (args.out / "storyboard.json").write_text(payload, encoding="utf-8")
    template = Path(__file__).with_name("viewer.html").read_text(encoding="utf-8")
    (args.out / "index.html").write_text(template.replace("__STORYBOARD_DATA__",
        payload.replace("<", "\\u003c").replace("&", "\\u0026")), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "fingerprint": bundle["fingerprint"],
                      "scenes": [len(s["scenes"]) for s in bundle["stories"]]}))


if __name__ == "__main__":
    main()
