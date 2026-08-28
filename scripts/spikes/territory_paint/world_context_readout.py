"""M2 합성 사건 자리에서 **시스템이 가진 진짜 세계 데이터**가 무엇을 돌려주는지 잰다.

    uv run python -m scripts.spikes.territory_paint.world_context_readout \\
        --latent latent.json --cache-world osm_world.json --json world_context.json

갈래는 [memory-engine](../../../docs/explorations/walk/memory-engine.md) §12 —
Walk Capsule 의 event-context 가 "당시 확보 가능했던 주변" 을 동결한다고 했다.
이 스크립트는 그 "확보 가능했던" 이 이 bbox 에서 실제로 얼마인지 잰다.

## 오염 방지 규약 — 실행 전에 적었고, 실행 후 안 고친다

이 실험의 성립 조건이다. 하나라도 어기면 결과 전체를 폐기한다.

1. 판단 재료는 **시스템이 가진 것만**: 로컬 DB(`place`·`facility`), Overpass 추출
   (질의문·bbox·digest 를 결과에 그대로 적는다), M2 합성 산출물. 웹 검색·지도앱·
   작성자(사람이든 LLM 이든)의 지역 지식은 어떤 형태로도 안 들어간다.
2. 결과에 나온 시설 이름·태그를 실제 세계와 대조하거나 정정하지 않는다.
   "그 자리에 실제로 무엇이 있는지" 는 이 실험의 관할 밖이고, 확인할 권한이 시스템에 없다.
3. 질문과 판정 기준은 아래에 **실행 전에** 적었다. 실행 후 기준을 옮기지 않는다.
4. bbox 는 M2 의 것을 그대로 쓴다 — 지역을 새로 고르지 않는다.
5. 이 실험이 재는 것은 "캡슐 event-context 에 무엇이 담기는가" 다.
   "나레이터가 무엇을 말해도 되는가" 는 문법이 정하고, 여기서 판정하지 않는다.

## 사전 등록 — 질문 셋과 판정 기준

    Q1  사건 자리의 세계 명사.  P 의 A·D 자리(개-주어 자리 후보)에서 DB 가 반경
        30/50/100m 안에 무엇을 돌려주나. 판정: **50m 내 이름 있는 행 >= 1 이면 그 자리는
        세계 명사를 얻는다.** 비율이 얼마든 실패가 아니다 — 낙하 문법("이 근처") 의 사용
        빈도를 정하는 수치다.
    Q2  구조적 정지의 지도 맥락.  B 자리와 최근접 crossing/traffic_signals 노드 거리.
        판정: **<= 30m 이면 M4 가 그 자리를 지도로 설명할 재료가 있다.**
    Q3  bbox 지형 밀도.  부류별 개수 그대로 — "국내 OSM 이 듬성하다" 를 가정이 아니라
        측정으로 만든다. 성패 기준 없음.

    보조  대조 노드.  통행 많은 비-자리 노드 5 곳에서 같은 readout — 사건 자리와 비-사건
        자리의 문맥 밀도가 다른지. 다르지 않아도 된다 (문맥은 라벨이 아니라 명명 재료다).

## 좌표에 대한 명기

probe 는 자리별 **실제 멈춤 지점들의 중심**이다 (`truth_only.events.actual_stop_at`).
실제 시스템은 지터 낀 fix 에서 이 위치를 추정하므로 ~σ/√n 의 오차가 더 붙는다 —
σ=8m · 30m 이상 반경에서는 무시할 수준이지만, 이것은 **가정**이므로 적어 둔다.
"""

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from scripts.spikes.territory_paint.real_route import BBOX, OVERPASS, metres

RADII_M = (30.0, 50.0, 100.0)
NOUN_RADIUS_M = 50.0      # Q1 판정 반경. 실행 전에 정했다
CROSSING_RADIUS_M = 30.0  # Q2 판정 반경. 실행 전에 정했다
DB_LIMIT = 5              # 자리당 DB 최근접 몇 건까지 남기나

# 지형 부류. **실행 전에 고정** — 결과를 보고 부류를 늘리면 3 항 위반이다.
TERRAIN_NODE = {"crossing": ('["highway"~"^(crossing|traffic_signals)$"]', "node"),
                "tree":     ('["natural"="tree"]', "node"),
                "bench":    ('["amenity"="bench"]', "node")}
TERRAIN_WAY = {"park":  ('["leisure"~"^(park|garden|dog_park)$"]', "way"),
               "grass": ('["landuse"~"^(grass|recreation_ground)$"]', "way"),
               "water": ('["waterway"]', "way"),
               "water_area": ('["natural"="water"]', "way")}


def terrain_query() -> str:
    """지형 질의. 결과 문서에 그대로 적는다 — 어느 부류를 물었는지 없이 "지형" 이라고만
    쓰면 밀도 숫자가 검증 불가능해진다."""
    south, west, north, east = BBOX
    box = f"({south},{west},{north},{east})"
    parts = [f"{kind}{selector}{box};"
             for selector, kind in TERRAIN_NODE.values()]
    parts += [f"{kind}{selector}{box};" for selector, kind in TERRAIN_WAY.values()]
    return f"[out:json][timeout:90];({''.join(parts)});out body geom;"


def fetch_terrain(cache: str | None) -> dict:
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as handle:
            return json.load(handle)
    request = urllib.request.Request(
        OVERPASS, data=urllib.parse.urlencode({"data": terrain_query()}).encode(),
        headers={"User-Agent": "daengs-geo-spike/0.1"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    if cache:
        with open(cache, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    return payload


def classify(element: dict) -> str | None:
    tags = element.get("tags", {})
    if element["type"] == "node":
        if tags.get("highway") in ("crossing", "traffic_signals"):
            return "crossing"
        if tags.get("natural") == "tree":
            return "tree"
        if tags.get("amenity") == "bench":
            return "bench"
        return None
    if tags.get("leisure") in ("park", "garden", "dog_park"):
        return "park"
    if tags.get("landuse") in ("grass", "recreation_ground"):
        return "grass"
    if "waterway" in tags:
        return "water"
    if tags.get("natural") == "water":
        return "water_area"
    return None


def in_ring(point: tuple, ring: list) -> bool:
    """닫힌 way 안에 있나. 면 부류(공원·풀밭·수면)에서 "안에 있는데 꼭짓점까지 60m" 라는
    왜곡을 막는다 — 안이면 거리 0 이다."""
    lat, lng = point
    inside = False
    for index in range(len(ring) - 1):
        a, b = ring[index], ring[index + 1]
        if (a[0] > lat) != (b[0] > lat):
            cross = (b[1] - a[1]) * (lat - a[0]) / (b[0] - a[0]) + a[1]
            if lng < cross:
                inside = not inside
    return inside


def terrain_index(payload: dict) -> dict[str, list]:
    """부류 → [(이름 or None, 기하)] 목록. 기하는 노드면 점 하나, way 면 점 목록."""
    index: dict[str, list] = {k: [] for k in (*TERRAIN_NODE, *TERRAIN_WAY)}
    for element in payload.get("elements", []):
        kind = classify(element)
        if kind is None:
            continue
        name = element.get("tags", {}).get("name")
        if element["type"] == "node":
            index[kind].append((name, [(element["lat"], element["lon"])]))
        elif element.get("geometry"):
            points = [(g["lat"], g["lon"]) for g in element["geometry"]]
            index[kind].append((name, points))
    return index


AREA_KINDS = frozenset({"park", "grass", "water_area"})


def nearest_terrain(point: tuple, index: dict) -> dict[str, dict]:
    """부류별 최근접. way 는 꼭짓점 최근접 — 면 부류만 내부 판정으로 0 이 될 수 있다.
    선분 최근접이 아니라 꼭짓점 최근접인 것은 **근사**이고 과대평가 쪽으로만 틀린다."""
    out = {}
    for kind, items in index.items():
        best = None
        for name, points in items:
            if (kind in AREA_KINDS and len(points) > 3
                    and points[0] == points[-1] and in_ring(point, points)):
                distance = 0.0
            else:
                distance = min(metres(point, p) for p in points)
            if best is None or distance < best[0]:
                best = (distance, name)
        if best is not None:
            out[kind] = {"m": round(best[0], 1), "name": best[1]}
    return out


async def nearest_rows(db, table: str, point: tuple, radius: float) -> list[dict]:
    """DB 최근접. 시스템이 가진 그대로 — 이름·부류·거리만 가져오고 고치지 않는다."""
    lat, lng = point
    kind_col = "category3" if table == "facility" else "kind"
    rows = (await db.execute(text(
        f"SELECT name, {kind_col} AS kind, "
        f"       ST_Distance(location, "
        f"         ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) AS m "
        f"FROM {table} "
        f"WHERE ST_DWithin(location, "
        f"        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :radius) "
        f"ORDER BY m LIMIT :limit"),
        {"lat": lat, "lng": lng, "radius": radius, "limit": DB_LIMIT},
    )).mappings().all()
    return [{"name": r["name"], "kind": r["kind"], "m": round(r["m"], 1)}
            for r in rows]


def probes_from_latent(payload: dict) -> list[dict]:
    """probe 목록. 자리(A·B·D)는 실제 멈춤 중심, C 는 사건 그대로, 대조는 아래에서 추가."""
    probes = []
    for persona in payload["personas"]:
        if persona["id"] not in ("P", "S"):
            continue
        truth = persona["truth_only"]
        stops: dict[str, list] = {}
        for event in truth["events"]:
            if event["spot_id"]:
                stops.setdefault(event["spot_id"], []).append(
                    tuple(event["actual_stop_at"]))
        for spot in truth["spots"]:
            if persona["id"] == "S" and spot["kind"] != "B":
                continue
            hit = stops.get(spot["spot_id"], [])
            at = (tuple(spot["at"]) if not hit else
                  (statistics.mean(p[0] for p in hit),
                   statistics.mean(p[1] for p in hit)))
            probes.append({"probe": f"{persona['id']}:{spot['spot_id']}",
                           "kind": spot["kind"], "at": list(at),
                           "stops": len(hit)})
        if persona["id"] == "P":
            for number, event in enumerate(e for e in truth["events"]
                                           if e["kind"] == "C"):
                probes.append({"probe": f"P:C{number:02d}", "kind": "C",
                               "at": list(event["actual_stop_at"]), "stops": 1})
    return probes


def control_probes(payload: dict, planted: list[dict]) -> list[dict]:
    """대조 — 사건이 없던 통과 지점. P 의 fix 를 200 걸음마다 표집해 심은 자리들에서
    60m 이상 떨어진 것 중 앞의 5 곳. 무작위가 아니라 결정론이다 — 재현 때문이다."""
    person = next(p for p in payload["personas"] if p["id"] == "P")
    taken = [tuple(p["at"]) for p in planted]
    picked: list[dict] = []
    for walk in person["walks"]:
        for lat, lng, _ in walk["fixes"][::200]:
            point = (lat, lng)
            if all(metres(point, t) > 60.0 for t in taken):
                picked.append({"probe": f"CTRL{len(picked)}", "kind": "ctrl",
                               "at": [lat, lng], "stops": 0})
                taken.append(point)
                if len(picked) == 5:
                    return picked
    return picked


def provenance(cache: str | None, payload: dict, query: str) -> dict:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    fetched = (datetime.fromtimestamp(os.path.getmtime(cache), UTC)
               if cache and os.path.exists(cache) else datetime.now(UTC))
    return {"provider": "OpenStreetMap / Overpass API", "bbox": list(BBOX),
            "query": query, "fetched_at": fetched.isoformat(timespec="seconds"),
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest()[:16],
            "elements": len(payload.get("elements", []))}


def load_inputs(args) -> tuple[dict, dict]:
    """스파이크 단발 실행이라 동기 IO 로 충분하다 — async 진입 전에 다 읽는다."""
    with open(args.latent, encoding="utf-8") as handle:
        latent = json.load(handle)
    return latent, fetch_terrain(args.cache_world)


async def run(args) -> dict:
    latent, terrain_payload = load_inputs(args)
    index = terrain_index(terrain_payload)

    probes = probes_from_latent(latent)
    probes += control_probes(latent, probes)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as db:
            counts = {}
            for table in ("facility", "place"):
                total = (await db.execute(text(
                    "SELECT count(*) FROM " + table +
                    " WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(:lng,:lat)"
                    ", 4326)::geography, :r)"),
                    {"lng": (BBOX[1] + BBOX[3]) / 2, "lat": (BBOX[0] + BBOX[2]) / 2,
                     "r": 1200.0})).scalar()
                counts[table] = total
            for probe in probes:
                point = tuple(probe["at"])
                probe["db"] = {}
                for table in ("facility", "place"):
                    probe["db"][table] = {
                        str(int(r)): await nearest_rows(db, table, point, r)
                        for r in RADII_M}
                probe["terrain"] = nearest_terrain(point, index)
    finally:
        await engine.dispose()

    return {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "latent_source": latent["source"],
            "terrain_source": provenance(args.cache_world, terrain_payload,
                                         terrain_query()),
            "bbox_center_1200m_rows": counts,
            "terrain_bbox_counts": {k: len(v) for k, v in index.items()},
            "noun_radius_m": NOUN_RADIUS_M,
            "crossing_radius_m": CROSSING_RADIUS_M,
            "probes": probes}


def named(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["name"]]


def report(result: dict) -> None:
    print(f"bbox 중심 1.2km 내 DB 행 — facility {result['bbox_center_1200m_rows']['facility']}"
          f" · place {result['bbox_center_1200m_rows']['place']}")
    print("지형 bbox 개수 — " + " · ".join(
        f"{k} {v}" for k, v in result["terrain_bbox_counts"].items()))

    print(f"\n  {'probe':<8}{'종류':<4}{'멈춤':>4} | facility 최근접(50m 내 이름 있는 행) "
          f"| place 최근접 | crossing | 기타 지형 30m 내")
    for probe in result["probes"]:
        fac = named(probe["db"]["facility"][str(int(NOUN_RADIUS_M))])
        plc = named(probe["db"]["place"][str(int(NOUN_RADIUS_M))])
        fac_txt = (f"{fac[0]['name']}({fac[0]['m']}m)+{len(fac) - 1}" if fac else "—")
        plc_txt = (f"{plc[0]['name']}({plc[0]['m']}m)+{len(plc) - 1}" if plc else "—")
        crossing = probe["terrain"].get("crossing")
        cross_txt = f"{crossing['m']}m" if crossing else "—"
        near = [f"{k}:{v['m']}m" for k, v in sorted(probe["terrain"].items())
                if k != "crossing" and v["m"] <= 30.0]
        print(f"  {probe['probe']:<8}{probe['kind']:<4}{probe['stops']:>4} | "
              f"{fac_txt} | {plc_txt} | {cross_txt} | {' '.join(near) or '—'}")

    spots = [p for p in result["probes"] if p["kind"] in ("A", "D")]
    got_noun = [p for p in spots
                if named(p["db"]["facility"][str(int(NOUN_RADIUS_M))])
                or named(p["db"]["place"][str(int(NOUN_RADIUS_M))])]
    bees = [p for p in result["probes"] if p["kind"] == "B"]
    got_cross = [p for p in bees
                 if p["terrain"].get("crossing")
                 and p["terrain"]["crossing"]["m"] <= CROSSING_RADIUS_M]
    print(f"\nQ1  A·D 자리 {len(spots)} 중 세계 명사({int(NOUN_RADIUS_M)}m 내 이름 행) "
          f"얻은 자리 {len(got_noun)}")
    print(f"Q2  B 자리 {len(bees)} 중 crossing {int(CROSSING_RADIUS_M)}m 내 "
          f"{len(got_cross)}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latent", required=True, help="latent_dwell_year 산출물")
    parser.add_argument("--cache-world", help="지형 Overpass 응답 캐시")
    parser.add_argument("--json", required=True, help="결과를 쓸 경로")
    args = parser.parse_args(argv)

    result = asyncio.run(run(args))
    report(result)
    with open(args.json, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    print(f"\n결과 → {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
