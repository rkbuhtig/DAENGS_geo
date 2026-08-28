"""M2 사건 자리에 3축 Context Signature 원자를 붙인다 — Phase 1.

    DAENGS_DATA_GO_KR_SERVICE_KEY=... uv run python -m \\
        scripts.spikes.territory_paint.context_signature_readout \\
        --latent latent.json --json world_signature.json

[world-context-readout](world_context_readout.py) 의 다음 판이다. 그 실험이 "현재 레포
DB 로는 사건 자리가 세계 명사를 못 얻는다(0/3)" 를 쟀다면, 이번엔 **외부 원천 3축으로
장소의 성격(원자)이 서는지** 를 잰다. 라벨("공원 가장자리" 같은)은 만들지 않는다 —
그건 판정층 몫이고, 여기는 원자까지다.

## 오염 방지 규약 — 실행 전에 적었고, 실행 후 안 고친다

world_context_readout 의 규약 5개를 그대로 상속하고 둘을 더한다.

6. **축과 원천은 아래 3개로 실행 전에 고정한다.** 결과를 보고 축을 늘리거나 원천을
   바꾸면 폐기다.
7. 결과의 명사는 **원천이 준 것만** 쓴다(피복 분류명·업종 분류명·하천명). 우리가 지어낸
   라벨은 원자에 못 들어간다.

## 3축 — 실행 전 고정

    land_cover   EGIS WMS GetFeatureInfo · 레이어 EGIS:lv3_10th_g
                 → l1/l2/l3 코드 + 분류명. 레이어명이 곧 세대(source_version)
    commerce     소진공 storeListInRadius · 반경 100m (사전 고정 — 50m 는 건물 스냅
                 양자화로 대부분 0 이었다. 원자는 업종 대분류 카운트 + 최근접 건물 거리.
                 상호명은 받아도 버린다)
    water        EGIS WFS me:adm_river · 상자 ±3km 1회 질의 → 자리별 최근접 거리 + 하천명
                 (선분 아닌 꼭짓점 최근접 — 과대평가 방향 근사)

resultCode 03(NODATA) 은 실패가 아니라 **관측된 부재(0건)** 다. 질의 자체가 죽은 것
(HTTP 오류·타임아웃)만 unknown 이다. 부재와 미지를 가르는 것이 이 계약의 반이다.

## 사전 등록 질문과 판정 기준

    Q1  Coverage        자리마다 3축 중 몇 축이 known 인가 (0건 포함 known).
                        fully(3) / partial(1~2) / unknown(0) 로 센다
    Q2  Discrimination  A·D 자리(개-주어 후보)끼리 signature 가 실제로 다른가.
                        **범주 축만** 판정에 쓴다 — 문턱 발명을 피하려고:
                        (a) 피복 l2_code 가 다르거나 (b) 업종 대분류 multiset 이 다르면
                        그 쌍은 구분된다. 연속값(거리)은 보고만 하고 판정에 안 쓴다
    Q3  Added nouns     자리마다 원천이 준 명사가 몇 종 생겼나 —
                        world-context-readout 의 "DB 명사 0/3" 과 대비한다

## 좌표에 대한 명기

probe 는 world_context_readout 과 같다 — 자리별 실제 멈춤 중심. 시스템의 위치 추정
오차(~σ/√n)는 반영 안 됐다 (가정).
"""

import argparse
import json
import math
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime

from scripts.spikes.territory_paint.real_route import BBOX, metres
from scripts.spikes.territory_paint.world_context_readout import probes_from_latent

LAND_LAYER = "EGIS:lv3_10th_g"
RIVER_TYPE = "me:adm_river"
COMMERCE_RADIUS_M = 100.0
RIVER_BOX_HALF_M = 3000.0

EGIS_WMS = "https://api.mcee.go.kr/geoserver/wms"
EGIS_WFS = "https://api.mcee.go.kr/geoserver/wfs"
SDSC = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"

_CTX = ssl.create_default_context()


def to3857(lat: float, lng: float) -> tuple[float, float]:
    x = lng * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * 20037508.34 / math.pi
    return x, y


def _get_json(url: str, timeout: float = 60.0) -> dict:
    with urllib.request.urlopen(url, context=_CTX, timeout=timeout) as response:
        return json.load(response)


# ---- 축 1: 토지피복 (점 질의) ----

def land_cover_at(lat: float, lng: float) -> dict:
    """GetFeatureInfo 한 점. feature 없음(바다 밖 등)은 unknown 으로 남긴다."""
    x, y = to3857(lat, lng)
    half = 60.0
    params = urllib.parse.urlencode({
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
        "LAYERS": LAND_LAYER, "QUERY_LAYERS": LAND_LAYER, "CRS": "EPSG:3857",
        "BBOX": f"{x - half},{y - half},{x + half},{y + half}",
        "WIDTH": "101", "HEIGHT": "101", "I": "50", "J": "50",
        "INFO_FORMAT": "application/json", "FEATURE_COUNT": "1"})
    try:
        features = _get_json(f"{EGIS_WMS}?{params}").get("features", [])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"status": "unknown", "error": type(error).__name__}
    if not features:
        return {"status": "unknown", "error": "no_feature"}
    props = features[0].get("properties", {})
    return {"status": "known",
            "l1_code": props.get("l1_code"), "l1_name": props.get("l1_name"),
            "l2_code": props.get("l2_code"), "l2_name": props.get("l2_name"),
            "l3_code": props.get("l3_code")}


# ---- 축 2: 상권 업종 (반경 질의) ----

def commerce_at(lat: float, lng: float, service_key: str) -> dict:
    """업종 대분류 카운트 + 최근접 건물 거리. 상호명은 집계에 안 들어간다.

    좌표가 건물 단위로 스냅돼 있어 카운트는 계단식이다 — 여기 명기해 두지 않으면
    "반경 100m 에 카페 0" 을 "카페 골목이 아니다" 로 오독한다.
    """
    params = urllib.parse.urlencode({
        "pageNo": 1, "numOfRows": 500, "radius": int(COMMERCE_RADIUS_M),
        "cx": f"{lng:.6f}", "cy": f"{lat:.6f}", "type": "json"})
    try:
        data = _get_json(f"{SDSC}?serviceKey={service_key}&{params}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"status": "unknown", "error": type(error).__name__}
    code = data.get("header", {}).get("resultCode")
    if code == "03":  # NODATA — 관측된 부재. 실패가 아니다
        return {"status": "known", "total": 0, "major": {}, "nearest_m": None}
    if code != "00":
        return {"status": "unknown", "error": f"resultCode:{code}"}
    items = data.get("body", {}).get("items", []) or []
    major = Counter(item.get("indsLclsNm") for item in items)
    nearest = min((metres((lat, lng), (float(item["lat"]), float(item["lon"])))
                   for item in items), default=None)
    return {"status": "known", "total": len(items),
            "major": dict(major.most_common()),
            "nearest_m": round(nearest, 1) if nearest is not None else None}


# ---- 축 3: 하천 (상자 1회 질의 → 자리별 거리) ----

def fetch_rivers() -> list[dict] | None:
    center_lat = (BBOX[0] + BBOX[2]) / 2
    center_lng = (BBOX[1] + BBOX[3]) / 2
    x, y = to3857(center_lat, center_lng)
    half = RIVER_BOX_HALF_M
    params = urllib.parse.urlencode({
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "typeNames": RIVER_TYPE, "outputFormat": "application/json", "count": "300",
        "srsName": "EPSG:3857",
        "bbox": f"{x - half},{y - half},{x + half},{y + half},urn:ogc:def:crs:EPSG::3857"})
    try:
        return _get_json(f"{EGIS_WFS}?{params}", timeout=90).get("features", [])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _vertex_min(px: float, py: float, coordinates) -> float:
    best = float("inf")

    def walk(node) -> None:
        nonlocal best
        if node and isinstance(node[0], (int, float)):
            best = min(best, math.hypot(node[0] - px, node[1] - py))
            return
        for child in node:
            walk(child)

    walk(coordinates)
    return best


def water_at(lat: float, lng: float, rivers: list[dict] | None) -> dict:
    if rivers is None:
        return {"status": "unknown", "error": "wfs_failed"}
    if not rivers:
        return {"status": "known", "river_name": None, "distance_m": None}
    x, y = to3857(lat, lng)
    cos = math.cos(math.radians(lat))
    scored = sorted(((_vertex_min(x, y, f["geometry"]["coordinates"]) * cos),
                     f["properties"].get("name")) for f in rivers)
    distance, name = scored[0]
    return {"status": "known", "river_name": name, "distance_m": round(distance, 1)}


# ---- 판정 (사전 등록 기준 그대로 — 문턱 없음) ----

def coverage_of(signature: dict) -> str:
    known = sum(1 for axis in ("land", "commerce", "water")
                if signature[axis]["status"] == "known")
    return {3: "fully", 0: "unknown"}.get(known, "partial")


def categorically_distinct(a: dict, b: dict) -> bool:
    """범주 축만 본다. 거리(연속값)는 판정 밖 — 문턱을 여기서 만들지 않는다."""
    if (a["land"].get("l2_code") and b["land"].get("l2_code")
            and a["land"]["l2_code"] != b["land"]["l2_code"]):
        return True
    return (a["commerce"]["status"] == b["commerce"]["status"] == "known"
            and a["commerce"].get("major") != b["commerce"].get("major"))


def source_nouns(signature: dict) -> list[str]:
    """원천이 준 명사만. 우리가 지은 라벨은 여기 못 들어온다 (규약 7)."""
    nouns = []
    if signature["land"].get("l2_name"):
        nouns.append(signature["land"]["l2_name"])
    nouns.extend(k for k in signature["commerce"].get("major", {}) if k)
    if signature["water"].get("river_name"):
        nouns.append(signature["water"]["river_name"])
    return nouns


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latent", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args(argv)

    service_key = os.environ.get("DAENGS_DATA_GO_KR_SERVICE_KEY", "")
    if not service_key:
        print("DAENGS_DATA_GO_KR_SERVICE_KEY 가 없다 — commerce 축이 전부 unknown 이 된다")

    with open(args.latent, encoding="utf-8") as handle:
        latent = json.load(handle)
    probes = probes_from_latent(latent)
    rivers = fetch_rivers()

    for probe in probes:
        lat, lng = probe["at"]
        probe["signature"] = {
            "land": land_cover_at(lat, lng),
            "commerce": (commerce_at(lat, lng, service_key) if service_key
                         else {"status": "unknown", "error": "no_key"}),
            "water": water_at(lat, lng, rivers),
        }
        probe["coverage"] = coverage_of(probe["signature"])
        probe["nouns"] = source_nouns(probe["signature"])

    print(f"  {'probe':<8}{'종류':<4}{'cover':<8} | 피복(l2) | 업종@100m | 하천 | 명사 수")
    for probe in probes:
        sig = probe["signature"]
        land = sig["land"].get("l2_name") or f"({sig['land'].get('error')})"
        commerce = sig["commerce"]
        commerce_text = ("(" + str(commerce.get("error")) + ")"
                         if commerce["status"] != "known"
                         else " ".join(f"{k}{v}" for k, v in
                                       list(commerce["major"].items())[:3]) or "0건")
        water = sig["water"]
        water_text = (f"{water.get('river_name')} {water.get('distance_m')}m"
                      if water.get("river_name") else f"({water.get('error', '없음')})")
        print(f"  {probe['probe']:<8}{probe['kind']:<4}{probe['coverage']:<8} | "
              f"{land} | {commerce_text} | {water_text} | {len(probe['nouns'])}")

    dog_probes = [p for p in probes if p["kind"] in ("A", "D")]
    pairs = [(a, b) for i, a in enumerate(dog_probes) for b in dog_probes[i + 1:]]
    distinct = [p for p in pairs
                if categorically_distinct(p[0]["signature"], p[1]["signature"])]
    fully = [p for p in probes if p["coverage"] == "fully"]
    with_noun = [p for p in dog_probes if p["nouns"]]

    print(f"\nQ1  fully known {len(fully)}/{len(probes)} "
          f"(partial {sum(1 for p in probes if p['coverage'] == 'partial')} · "
          f"unknown {sum(1 for p in probes if p['coverage'] == 'unknown')})")
    print(f"Q2  A·D 자리 쌍 {len(pairs)} 중 범주 축에서 구분되는 쌍 {len(distinct)}")
    print(f"Q3  A·D 자리 {len(dog_probes)} 중 원천 명사를 얻은 자리 {len(with_noun)} "
          f"(world-context-readout 의 DB 명사는 0/3 이었다)")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "latent_source": latent["source"],
        "axes": {"land": {"provider": "EGIS WMS GetFeatureInfo", "layer": LAND_LAYER},
                 "commerce": {"provider": "SEMAS storeListInRadius",
                              "radius_m": COMMERCE_RADIUS_M,
                              "note": "좌표는 건물 스냅 — 카운트는 계단식"},
                 "water": {"provider": "EGIS WFS", "type": RIVER_TYPE,
                           "box_half_m": RIVER_BOX_HALF_M,
                           "note": "꼭짓점 최근접 — 과대평가 방향 근사"}},
        "probes": probes,
    }
    with open(args.json, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print(f"\n결과 → {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
