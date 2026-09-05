"""Pin-centred bounded queries; cache-only by default, projected public evidence only."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.spikes.storyboard_and_regions.sources import collect, fingerprint
from scripts.spikes.walk_record_lab.core import distance


class ContextReader:
    def __init__(self, cache: Path, key: str = ""):
        self.cache, self.key = cache, key
        self.requests = 0
        self.receipts = {}

    def selected_contexts(self, selection, fetch=False):
        anchors = [{"id": a["id"], "accepted": True, "kind": "behavior",
                    "behavior_code": "sniffing", "location": a["location"]}
                   for a in selection["anchors"]]
        contexts, metrics = self.contexts(anchors, "common", fetch)
        for anchor in selection["anchors"]:
            for entry_id in anchor["entry_ids"]:
                contexts[entry_id] = contexts[anchor["id"]]
        return contexts, metrics

    def read(self, source, params, fetch):
        signature = (source, fingerprint(params))
        if signature in self.receipts:
            return self.receipts[signature]
        path = self.cache / f"{source}-{fingerprint(params)[:16]}.json"
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
        elif not fetch or not self.key:
            result = {"source": source, "status": "cache_missing", "rows": [], "query": params}
        else:
            self.requests += 1
            result = collect(source, params, key=self.key, cache_dir=self.cache, max_pages=6)
        self.receipts[signature] = result
        return result

    def contexts(self, entries, policy, fetch=False):
        out, anchors = {}, []
        # Counters refer to distinct query groups, not provider pages or actual behavior counts.
        self.requests = 0
        for entry in entries:
            if not entry["accepted"] or entry["kind"] == "note":
                continue
            if policy == "behavior" and entry["behavior_code"] == "excretion":
                out[entry["id"]] = {"status": "routine_only", "facts": [], "sources": []}
                continue
            loc = entry["location"]
            point = (loc["lat"], loc["lng"])
            anchor = next((a for a in anchors if distance(point, a["point"])+125 <= 250), None)
            if anchor is None:
                if len(anchors) >= 8:
                    out[entry["id"]] = {"status": "query_budget_exhausted", "facts": []}
                    continue
                params = self.cached_query(point) or {
                    "cx": round(point[1], 6), "cy": round(point[0], 6), "radius": 250}
                anchor = {"point": (params["cy"], params["cx"]),
                          "receipt": self.read("commerce", params, fetch)}
                anchors.append(anchor)
            commerce = anchor["receipt"]
            # Park source is an explicitly scoped first experiment, not nationwide coverage.
            parks = self.read("parks", {"instt_nm": "서울특별시 강남구"}, fetch)
            rivers = self.read("rivers", {}, fetch)
            facts, sources = [], []
            for receipt in (commerce, parks, rivers):
                sources.append({k: receipt.get(k) for k in (
                    "source", "source_url", "status", "captured_at", "snapshot_fingerprint",
                    "query", "pages", "failure")})
            nearby = []
            for row in commerce["rows"]:
                d = row_distance(row, "lat", "lon", point)
                if d is not None and d <= 125:
                    nearby.append(row.get("indsLclsNm") or "미분류")
            if nearby:
                categories = " · ".join(f"{k} {v}곳" for k, v in Counter(nearby).most_common(3))
                facts.append(f"좌표 반경 125m에서 수집된 등록 상가: {categories}")
            candidates = [(d, row) for row in parks["rows"]
                          if (d := row_distance(row, "latitude", "longitude", point)) is not None
                          and d <= 250]
            if candidates:
                d, row = min(candidates, key=lambda item: item[0])
                facts.append(f"{row.get('parkNm') or '이름 미상 공원'} 대표점에서 약 {round(d)}m"
                             " (강남구 제공 자료·공원 내부 판정 아님)")
            # River standard points have sparse coverage; never invent missing geometry.
            candidates = [(d, row) for row in rivers["rows"]
                          if (d := row_distance(row, "bgngPstnLat", "bgngPstnLot", point))
                          is not None and d <= 250]
            if candidates:
                d, row = min(candidates, key=lambda item: item[0])
                facts.append(f"{row.get('rvrNm') or '이름 미상 하천'} 시점 좌표에서 약 {round(d)}m")
            out[entry["id"]] = {
                "status": "available" if facts else "no_supported_context",
                "facts": facts, "sources": sources,
                "limitations": ["주변 자료는 행동 원인·방문·당시 혼잡도를 증명하지 않음",
                                "공원은 강남구 제공 자료만 조회; 하천은 시점 좌표만 사용",
                                "일치 항목 없음은 실제 시설 부재를 뜻하지 않음"],
            }
        return out, {"query_groups_fetched": self.requests, "commerce_anchors": len(anchors),
                     "max_commerce_anchors": 8, "max_pages_per_query": 6,
                     "mode": "fetch_missing" if fetch else "cache_only"}

    def cached_query(self, point):
        """Deleting the first pin must not lose the shared snapshot for remaining pins."""
        for path in sorted(self.cache.glob("commerce-*.json")):
            receipt = json.loads(path.read_text(encoding="utf-8"))
            query = receipt.get("query", {})
            if receipt.get("status") not in {"known", "partial"}:
                continue
            if (query.get("radius") == 250 and "cy" in query and "cx" in query
                    and distance(point, (query["cy"], query["cx"]))+125 <= 250):
                return query
        return None


def row_distance(row, lat_key, lng_key, point):
    try:
        lat, lng = float(row[lat_key]), float(row[lng_key])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None
        return distance(point, (lat, lng))
    except (KeyError, TypeError, ValueError):
        return None
