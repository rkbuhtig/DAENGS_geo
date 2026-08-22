"""TMAP 보행자 옵션 조사 — 옵션 fan-out 을 계속 할지 **데이터로** 정하기 위한 것.

질문 셋 (docs/research/2026-08-19-tmap-live.md 는 경로 하나뿐이라 답을 못 한다):
  1. 밀도      1km 당 횡단·계단·지하·육교가 몇 개인가 (지역별)
  2. 커버리지  계단·지하·육교가 **한 번이라도** 보고되는 경로가 몇 % 인가
  3. 분산      같은 쌍에서 옵션(추천/큰길/계단제외)이 실질적으로 다른 비율
그리고 받아둔 데이터로 "단발 + 필요할 때만 한 번 더" 정책을 오프라인 시뮬레이션해서
지금의 전부-받아서-점수 방식과 **호출 수 · 일치율**을 비교한다.

쌍은 DB 의 실제 활성 병원끼리 (출발도 병원 — 병원은 주거·상가 가로변에 있어 출발지로도 자연스럽다).
Usage Gate 를 타지 않는다 — registry 를 거치지 않고 TMAP 을 직접 부른다. 원본 JSON 은 out/raw/ 에
남겨 재실행이 공짜고, 파서가 바뀌면 `--reparse` 로 호출 없이 다시 집계한다.

    DAENGS_TMAP_APP_KEY=... uv run python scripts/tmap_option_survey.py --dry-run     # 호출 수만
    DAENGS_TMAP_APP_KEY=... uv run python scripts/tmap_option_survey.py               # 실행
    uv run python scripts/tmap_option_survey.py --provider fake                      # 키 없이 파이프라인 점검
"""

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.journey.advice import choose_walk, dog_time_factor
from app.providers.base import LatLng, RouteResult, WalkOption
from app.providers.fake import haversine_m
from app.providers.tmap import OPTION as TMAP_OPTION
from app.providers.tmap import URL as TMAP_URL
from app.providers.tmap_parse import parse_tmap

# 지역: (설명, 위도0, 위도1, 경도0, 경도1). 활성 병원 수 2026-08-22 기준.
REGIONS: dict[str, tuple[str, float, float, float, float]] = {
    "gangnam":       ("평지 격자 · 강남",        37.48, 37.53, 127.02, 127.07),   # 89
    "seongbuk":      ("구릉 · 성북",             37.58, 37.62, 126.99, 127.05),   # 47
    "yeongdeungpo":  ("구도심 평지 · 영등포",     37.50, 37.54, 126.88, 126.93),   # 38
    "busan_dongnae": ("구릉 구도심 · 부산 동래",  35.19, 35.23, 129.06, 129.10),   # 35
}
DIST_BANDS_M = ((300, 900), (900, 1600), (1600, 2500))   # 목적지는 거리 밴드별로 하나씩
MATERIAL_MIN_DELTA = 3          # 옵션 간 "실질적으로 다르다" — 시간 3분 또는 시설 1개


@dataclass(frozen=True)
class Node:
    id: int
    name: str
    pos: LatLng


@dataclass(frozen=True)
class Pair:
    region: str
    origin: Node
    dest: Node
    straight_m: int


# ------------------------------------------------------------------ 표본
async def sample_pairs(regions: list[str], per_region: int, per_origin: int, seed: str) -> list[Pair]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    pairs: list[Pair] = []
    try:
        async with engine.connect() as conn:
            for region in regions:
                _, lat0, lat1, lng0, lng1 = REGIONS[region]
                rows = (await conn.execute(text("""
                    SELECT id, name, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
                    FROM place
                    WHERE kind = 'hospital' AND active
                      AND ST_Y(location::geometry) BETWEEN :lat0 AND :lat1
                      AND ST_X(location::geometry) BETWEEN :lng0 AND :lng1
                    ORDER BY md5(id::text || :seed)
                    LIMIT :n
                """), {"lat0": lat0, "lat1": lat1, "lng0": lng0, "lng1": lng1,
                       "seed": seed, "n": per_region})).all()
                for oid, oname, olat, olng in rows:
                    origin = Node(oid, oname, LatLng(olat, olng))
                    cands = (await conn.execute(text("""
                        SELECT p.id, p.name, ST_Y(p.location::geometry), ST_X(p.location::geometry),
                               ST_Distance(p.location, o.location) AS d
                        FROM place p JOIN place o ON o.id = :oid
                        WHERE p.kind = 'hospital' AND p.active AND p.id <> o.id
                          AND ST_DWithin(p.location, o.location, :maxm)
                          AND ST_Distance(p.location, o.location) >= :minm
                        ORDER BY d
                        LIMIT 40
                    """), {"oid": oid, "maxm": DIST_BANDS_M[-1][1], "minm": DIST_BANDS_M[0][0]})).all()
                    pairs.extend(_pick_dests(region, origin, cands, per_origin))
    finally:
        await engine.dispose()
    return pairs


def _pick_dests(region: str, origin: Node, cands, k: int) -> list[Pair]:
    """거리 밴드마다 가장 가까운 하나. 밴드가 비면 남은 후보 중 가까운 순으로 채운다.
    가까운 k 개만 집으면 강남은 전부 400m 짜리가 된다 — 검색 반경(2km) 분포를 따라가야 한다."""
    chosen: list = []
    for lo, hi in DIST_BANDS_M:
        for c in cands:
            if lo <= c[4] < hi and c not in chosen:
                chosen.append(c)
                break
        if len(chosen) >= k:
            break
    for c in cands:
        if len(chosen) >= k:
            break
        if c not in chosen:
            chosen.append(c)
    return [Pair(region, origin, Node(c[0], c[1], LatLng(c[2], c[3])), int(c[4])) for c in chosen[:k]]


# ------------------------------------------------------------------ 호출
class Fetcher:
    """원본 JSON 을 raw/ 에 남긴다. 있으면 호출 안 함."""

    def __init__(self, provider: str, raw_dir: Path, sleep_s: float):
        self.provider, self.raw_dir, self.sleep_s = provider, raw_dir, sleep_s
        self.calls = self.cached = self.errors = 0
        self._client = httpx.AsyncClient(timeout=10.0)
        self._key = settings.tmap_app_key

    def path(self, pair: Pair, option: WalkOption) -> Path:
        return self.raw_dir / f"{pair.origin.id}-{pair.dest.id}-{option}.json"

    async def fetch(self, pair: Pair, option: WalkOption) -> dict | None:
        p = self.path(pair, option)
        if p.exists():
            self.cached += 1
            return json.loads(p.read_text(encoding="utf-8"))
        try:
            data = await (self._fake(pair, option) if self.provider == "fake" else self._tmap(pair, option))
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            self.errors += 1
            p.with_suffix(".error").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
            return None
        self.calls += 1
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if self.sleep_s:
            await asyncio.sleep(self.sleep_s)
        return data

    async def _tmap(self, pair: Pair, option: WalkOption) -> dict:
        if not self._key:
            sys.exit("DAENGS_TMAP_APP_KEY 가 없다. --provider fake 로 파이프라인만 점검하거나 키를 넣어라.")
        body = {
            "startX": pair.origin.pos.lng, "startY": pair.origin.pos.lat,
            "endX": pair.dest.pos.lng, "endY": pair.dest.pos.lat,
            "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
            "startName": "출발", "endName": "도착",
            "searchOption": TMAP_OPTION[option],
        }
        r = await self._client.post(TMAP_URL, json=body, params={"version": 1},
                                    headers={"appKey": self._key, "Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()

    async def _fake(self, pair: Pair, option: WalkOption) -> dict:
        """파이프라인 점검용 **가짜** GeoJSON. 시설은 쌍 id 로 결정론 패턴 — 집계·시뮬 코드를 밟게 하려는 것뿐,
        숫자에 의미는 없다. summary 에 provider=fake 가 찍힌다."""
        o, d = pair.origin.pos, pair.dest.pos
        dist = int(haversine_m(o, d) * (1.4 if option == "no_stairs" else 1.3))
        feats: list[dict] = [{"properties": {"totalDistance": dist, "totalTime": int(dist / 1.22)},
                              "geometry": {"type": "LineString",
                                           "coordinates": [[o.lng, o.lat], [d.lng, d.lat]]}}]
        k = (pair.origin.id + pair.dest.id) % 5
        if k == 0 and option != "no_stairs":
            feats.append({"properties": {"turnType": 127},
                          "geometry": {"type": "Point", "coordinates": [o.lng, o.lat]}})
        for _ in range(k):
            feats.append({"properties": {"turnType": 211},
                          "geometry": {"type": "Point", "coordinates": [d.lng, d.lat]}})
        await asyncio.sleep(0)
        return {"features": feats}

    async def close(self):
        await self._client.aclose()


# ------------------------------------------------------------------ 집계
CSV_FIELDS = ["region", "origin_id", "origin_name", "dest_id", "dest_name", "straight_m", "option",
              "distance_m", "duration_s", "crosswalk", "big_crossings", "stairs", "underpass", "underpass_m",
              "origin_passage_m", "overpass", "elevator", "slope", "big_road_ratio"]


def row_of(pair: Pair, option: WalkOption, r: RouteResult) -> dict:
    f = r.facilities
    return {"region": pair.region, "origin_id": pair.origin.id, "origin_name": pair.origin.name,
            "dest_id": pair.dest.id, "dest_name": pair.dest.name, "straight_m": pair.straight_m,
            "option": option, "distance_m": r.distance_m, "duration_s": r.duration_s,
            "crosswalk": f.crosswalk, "big_crossings": f.big_crossings, "stairs": f.stairs,
            "underpass": f.underpass, "underpass_m": f.underpass_m, "origin_passage_m": f.origin_passage_m,
            "overpass": f.overpass, "elevator": f.elevator, "slope": f.slope, "big_road_ratio": f.big_road_ratio}


def _mean(xs) -> float:
    xs = list(xs)
    return round(statistics.fmean(xs), 2) if xs else 0.0


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


Results = dict[tuple[int, int], dict[WalkOption, tuple[Pair, RouteResult]]]


def summarize(results: Results, options: list[WalkOption], fetcher: Fetcher) -> str:
    out: list[str] = []
    w = out.append
    w(f"provider={fetcher.provider} · 호출 {fetcher.calls} · 캐시 {fetcher.cached} · 오류 {fetcher.errors}\n")

    # ---- 1·2 밀도와 커버리지 — 지역 × 옵션
    w("## 1·2. 밀도 (1km 당) 와 커버리지 (한 번이라도 보고된 경로 비율)\n")
    w("| 지역 | 옵션 | n | 평균 m | 평균 분 | 횡단/km | 계단/km | 지하/km | 육교/km"
      " | 계단≥1 | 지하≥1 | 육교≥1 | 셋 중 하나 |")
    w("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    regions = sorted({p.region for v in results.values() for p, _ in v.values()})
    for region in regions + ["ALL"]:
        for opt in options:
            rs = [r for v in results.values() if opt in v
                  for p, r in [v[opt]] if region == "ALL" or p.region == region]
            if not rs:
                continue
            km = [r.distance_m / 1000 for r in rs]
            fac = [r.facilities for r in rs]
            n = len(rs)
            w(f"| {region} | {opt} | {n} | {_mean(r.distance_m for r in rs):.0f}"
              f" | {_mean(r.duration_s / 60 for r in rs):.0f}"
              f" | {_mean(f.crosswalk / k for f, k in zip(fac, km))}"
              f" | {_mean(f.stairs / k for f, k in zip(fac, km))}"
              f" | {_mean(f.underpass / k for f, k in zip(fac, km))}"
              f" | {_mean(f.overpass / k for f, k in zip(fac, km))}"
              f" | {_pct(sum(f.stairs >= 1 for f in fac), n)}"
              f" | {_pct(sum(f.underpass >= 1 for f in fac), n)}"
              f" | {_pct(sum(f.overpass >= 1 for f in fac), n)}"
              f" | {_pct(sum(f.stairs + f.underpass + f.overpass >= 1 for f in fac), n)} |")

    # ---- 3 옵션 간 분산 — 추천(0) 기준
    base: WalkOption = "recommended"
    w("\n## 3. 옵션 간 분산 — 추천 기준, 같은 쌍에서\n")
    w(f"\"실질적으로 다르다\" = |Δ분| ≥ {MATERIAL_MIN_DELTA} 또는 계단·지하·육교 중 하나라도 개수가 다름\n")
    w("| 비교 | 쌍 | Δm 중앙 | Δ분 중앙 | 계단 다름 | 지하 다름 | 육교 다름 | 실질 다름 | 완전 동일 |")
    w("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for opt in options:
        if opt == base:
            continue
        both = [(v[base][1], v[opt][1]) for v in results.values() if base in v and opt in v]
        if not both:
            continue
        dm = [b.distance_m - a.distance_m for a, b in both]
        dmin = [(b.duration_s - a.duration_s) / 60 for a, b in both]
        ds = sum(a.facilities.stairs != b.facilities.stairs for a, b in both)
        du = sum(a.facilities.underpass != b.facilities.underpass for a, b in both)
        do = sum(a.facilities.overpass != b.facilities.overpass for a, b in both)
        mat = sum(_material(a, b) for a, b in both)
        # 완전 동일 = 거리·시간·시설이 전부 같음. 돈 내고 같은 걸 두 번 받은 것
        same = sum(a.distance_m == b.distance_m and a.duration_s == b.duration_s
                   and a.facilities == b.facilities for a, b in both)
        n = len(both)
        w(f"| {base} vs {opt} | {n} | {statistics.median(dm):.0f} | {statistics.median(dmin):.1f}"
          f" | {_pct(ds, n)} | {_pct(du, n)} | {_pct(do, n)} | {_pct(mat, n)} | {_pct(same, n)} |")

    # ---- 4 정책 시뮬레이션
    w("\n## 4. 정책 시뮬레이션 — 같은 데이터로 오프라인\n")
    w("- **FULL**: 옵션 전부 받아 `choose_walk` 로 선택 (지금 방식). 프로필 없음, avoid 없음, 밤 아님")
    w("- **B-any**: 추천 하나만 받고, 계단·지하·육교가 하나라도 있으면 계단제외를 **한 번 더** 받아 둘 중 선택")
    w("- **B-stairs**: 위와 같되 트리거가 계단뿐")
    w("- **SINGLE**: 추천 하나만. 비교 없음\n")
    w("| 정책 | 쌍당 호출 | FULL 과 같은 선택 | 다를 때 Δ분 (B−FULL, 평균) | 다를 때 Δ계단 (B−FULL, 평균) |")
    w("|---|--:|--:|--:|--:|")
    factor = dog_time_factor(None)
    pairs_all = [v for v in results.values() if base in v]
    if pairs_all:
        full_pick: dict[int, RouteResult] = {}
        for i, v in enumerate(pairs_all):
            rs = [r for _, r in v.values()]
            full_pick[i] = choose_walk(rs, base, [], None, factor, False)[0] if len(rs) > 1 else rs[0]
        for name, trigger in (("B-any", lambda f: f.stairs + f.underpass + f.overpass >= 1),
                              ("B-stairs", lambda f: f.stairs >= 1),
                              ("SINGLE", lambda f: False)):
            calls = 0
            agree = 0
            dmin: list[float] = []
            dst: list[int] = []
            for i, v in enumerate(pairs_all):
                primary = v[base][1]
                cand = [primary]
                calls += 1
                if trigger(primary.facilities) and "no_stairs" in v:
                    cand.append(v["no_stairs"][1])
                    calls += 1
                pick = choose_walk(cand, base, [], None, factor, False)[0] if len(cand) > 1 else cand[0]
                if pick is full_pick[i]:
                    agree += 1
                else:
                    dmin.append((pick.duration_s - full_pick[i].duration_s) * factor / 60)
                    dst.append(pick.facilities.stairs - full_pick[i].facilities.stairs)
            n = len(pairs_all)
            w(f"| {name} | {calls / n:.2f} | {_pct(agree, n)} | {_mean(dmin):+.1f} | {_mean(dst):+.2f} |")
        w(f"| FULL | {_mean(len(v) for v in pairs_all):.2f} | 100% | - | - |")
    w("\n'다를 때 Δ' 가 0 근처면 B 는 FULL 과 사실상 같은 답을 더 싸게 낸 것이다. 계단 Δ 가 양수면 B 가 계단을 더 먹었다.")
    return "\n".join(out)


def _material(a: RouteResult, b: RouteResult) -> bool:
    fa, fb = a.facilities, b.facilities
    return (abs(a.duration_s - b.duration_s) / 60 >= MATERIAL_MIN_DELTA
            or fa.stairs != fb.stairs or fa.underpass != fb.underpass or fa.overpass != fb.overpass)


# ------------------------------------------------------------------ main
async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["tmap", "fake"], default="tmap")
    ap.add_argument("--regions", default=",".join(REGIONS), help="쉼표 구분. 기본 전부")
    ap.add_argument("--origins-per-region", type=int, default=8)
    ap.add_argument("--dests-per-origin", type=int, default=3)
    ap.add_argument("--options", default="recommended,main_road,no_stairs")
    ap.add_argument("--out", default="docs/research/tmap-option-survey")
    ap.add_argument("--seed", default="2026-08-22")
    ap.add_argument("--sleep", type=float, default=0.25, help="호출 간격(초). free 키 예의")
    ap.add_argument("--dry-run", action="store_true", help="표본만 뽑고 호출 수를 출력")
    ap.add_argument("--reparse", action="store_true", help="raw/ 만 다시 집계. 호출 없음")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")     # Windows 콘솔은 cp949 — 한글·— 가 깨지거나 죽는다

    regions = [r.strip() for r in a.regions.split(",") if r.strip()]
    unknown = [r for r in regions if r not in REGIONS]
    if unknown:
        sys.exit(f"모르는 지역: {unknown}. 가능: {list(REGIONS)}")
    options: list[WalkOption] = [o.strip() for o in a.options.split(",")]  # type: ignore[misc]
    bad = [o for o in options if o not in TMAP_OPTION]
    if bad:
        sys.exit(f"모르는 옵션: {bad}. 가능: {list(TMAP_OPTION)}")

    out = Path(a.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    pairs = await sample_pairs(regions, a.origins_per_region, a.dests_per_origin, a.seed)
    by_region = {r: sum(p.region == r for p in pairs) for r in regions}
    print(f"표본 {len(pairs)}쌍 {by_region} × 옵션 {len(options)} = 호출 {len(pairs) * len(options)}")
    if a.dry_run:
        for p in pairs[:6]:
            print(f"  {p.region:14} {p.origin.name} → {p.dest.name} ({p.straight_m}m)")
        print("  ...")
        return

    fetcher = Fetcher(a.provider, raw, a.sleep)
    results: Results = {}
    rows: list[dict] = []
    t0 = time.monotonic()
    try:
        for i, pair in enumerate(pairs, 1):
            for opt in options:
                if a.reparse:
                    p = fetcher.path(pair, opt)
                    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
                else:
                    data = await fetcher.fetch(pair, opt)
                if data is None:
                    continue
                r = parse_tmap(data, opt)
                if r.distance_m == 0:
                    continue                      # 경로 없음 응답
                results.setdefault((pair.origin.id, pair.dest.id), {})[opt] = (pair, r)
                rows.append(row_of(pair, opt, r))
            if i % 10 == 0:
                print(f"  {i}/{len(pairs)} 쌍 · 호출 {fetcher.calls} · 캐시 {fetcher.cached}"
                      f" · 오류 {fetcher.errors} · {time.monotonic() - t0:.0f}s", flush=True)
    finally:
        await fetcher.close()

    with (out / "rows.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    fetcher.provider = "cache(reparse)" if a.reparse else a.provider
    head = (f"# TMAP 보행자 옵션 조사\n\n표본 {len(pairs)}쌍 {by_region} · 옵션 {options} · seed `{a.seed}`"
            f" · 유효 결과 {len(rows)}행\n\n")
    summary = head + summarize(results, options, fetcher)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"\n→ {out / 'rows.csv'} · {out / 'summary.md'} · raw {raw}")


if __name__ == "__main__":
    asyncio.run(main())
