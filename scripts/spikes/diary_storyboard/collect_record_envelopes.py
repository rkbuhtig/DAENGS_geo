"""Step 2: attach provider-shaped public evidence to behavior, note and photo records."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.spikes.storyboard_and_regions.sources import service_key

from .envelope_sources import PublicDataReader
from .record_envelopes import Envelope, Record, RecordEnvelopeSnapshot, payload_hash

POLICY = "record-envelope-gangnam-v1"
SOURCES = {"parks": "space.park", "rivers": "space.river",
           "commerce": "space.facility", "weather": "environment.weather"}
# Explicit experiment area, not an administrative polygon or nationwide support claim.
BOUNDS = (127.041, 37.480, 127.061, 37.493)
FIELDS = {
    "parks": ("manageNo", "parkNm", "parkSe", "latitude", "longitude", "referenceDate", "insttNm"),
    "rivers": ("rvrCd", "rvrNm", "rvrSeNm", "bgngPstnLat", "bgngPstnLot", "dataCrtrYmd"),
    "commerce": ("bizesId", "bizesNm", "indsLclsCd", "indsLclsNm", "indsMclsCd",
                 "indsMclsNm", "indsSclsCd", "indsSclsNm", "lat", "lon"),
    "weather": ("stnId", "stnNm", "tm", "ta", "rn", "hm", "ws"),
}
COORDS = {"parks": ("latitude", "longitude", "park_representative_point"),
          "rivers": ("bgngPstnLat", "bgngPstnLot", "river_start_point"),
          "commerce": ("lat", "lon", "registered_shop_point")}


def distance_m(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1, math.sqrt(value)))


def query_for(record: Record, source: str, radius: float):
    if record.location is None:
        return None, "location_missing"
    p = record.location.point
    if not BOUNDS[0] <= p.lng <= BOUNDS[2] or not BOUNDS[1] <= p.lat <= BOUNDS[3]:
        return None, "outside_experiment_area"
    if source == "parks":
        return {"instt_nm": "서울특별시 강남구"}, None
    if source == "rivers":
        return {}, None
    if source == "commerce":
        return {"cx": p.lng, "cy": p.lat, "radius": radius}, None
    # Station 108 is an explicitly chosen Seoul station, not an at-pin observation.
    event = record.event_at.astimezone(ZoneInfo("Asia/Seoul"))
    return {"dataCd": "ASOS", "dateCd": "HR", "startDt": event.strftime("%Y%m%d"),
            "startHh": event.strftime("%H"), "endDt": event.strftime("%Y%m%d"),
            "endHh": event.strftime("%H"), "stnIds": "108"}, None


def project(receipt, source, record, radius, max_items):
    """Retain provider field names; calculate distances without deriving behavior meanings."""
    rows, items, invalid = receipt["rows"], [], 0
    times = []
    for index, row in enumerate(rows):
        selected = {key: row[key] for key in FIELDS[source] if key in row}
        if source == "weather":
            try:
                observed = datetime.strptime(str(row["tm"]), "%Y-%m-%d %H:%M").replace(
                    tzinfo=ZoneInfo("Asia/Seoul"))
                expected = record.event_at.astimezone(ZoneInfo("Asia/Seoul")).replace(
                    minute=0, second=0, microsecond=0)
                if str(row["stnId"]) != "108" or observed != expected:
                    raise ValueError("unexpected observation")
            except (ValueError, KeyError, TypeError):
                invalid += 1
                continue
            times.append(observed)
            relation = {"spatial_support": "station_108", "at_pin": False,
                        "offset_seconds_from_record": (observed - record.event_at).total_seconds()}
        else:
            lat, lng, basis = COORDS[source]
            try:
                xy = float(row[lat]), float(row[lng])
                if not all(math.isfinite(v) for v in xy) or not (-90 <= xy[0] <= 90 and -180 <= xy[1] <= 180):
                    raise ValueError("invalid coordinate")
            except (ValueError, KeyError, TypeError):
                invalid += 1
                continue
            point = record.location.point
            distance = distance_m((point.lat, point.lng), xy)
            if distance > radius:
                continue
            relation = {"distance_m": round(distance, 2), "geometry_reference": basis,
                        "calculation": "haversine-radius-6371008.8-v1"}
        items.append({"source_row_index": index, "provider_fields": selected, "relation": relation})
    if source != "weather":
        items.sort(key=lambda item: (item["relation"]["distance_m"], item["source_row_index"]))
    matched = len(items)
    status, reason = receipt["status"], receipt["reason"]
    if status in {"known", "empty"}:
        status = "known" if matched else "empty"
    if invalid or matched > max_items:
        status = "partial"
        reason = "unusable_source_rows" if invalid else "projection_limit"
    payload = {"query": receipt["identity"]["query"], "source_url": receipt["source_url"],
               "source_receipt_sha256": receipt["sha256"],
               "page_sha256": [p["sha256"] for p in receipt["pages"]],
               "provider_metadata": [{"stdrYm": p["body"]["header"]["stdrYm"]}
                                     for p in receipt["pages"]
                                     if source == "commerce" and "stdrYm" in p["body"].get("header", {})],
               "coverage": {"source_status": receipt["status"], "source_reason": receipt["reason"],
                            "reported_total": receipt["reported_total"], "read_rows": len(rows),
                            "unusable_rows": invalid, "matched_rows": matched,
                            "returned_rows": min(matched, max_items)},
               "items": items[:max_items],
               "limits": ["Registered source geometry is not proof of a visit or behavior cause.",
                          "Source coverage is limited to the provider query and successfully read pages."]}
    span = {"start_at": min(times).isoformat(), "end_at": max(times).isoformat()} if times else None
    if source == "weather":
        payload["limits"].append("Station observations are not weather measured at the pin.")
    return payload, status, reason, span


def collect_snapshot(snapshot, reader, *, radius=250, max_items=30):
    if not 25 <= radius <= 500 or not 1 <= max_items <= 100:
        raise ValueError("radius/item count outside experiment bounds")
    if snapshot.context_mode == "synthetic" and snapshot.envelopes:
        raise ValueError("use a records-only input; do not relabel synthetic envelopes as provider data")
    envelopes = list(snapshot.envelopes)
    selected = set(snapshot.selected_envelope_ids)
    ids = {e.id for e in envelopes}
    for record in snapshot.records:
        for source, tag in SOURCES.items():
            query, skip = query_for(record, source, radius)
            receipt = reader.read(source, query) if query is not None else None
            payload, span = None, None
            status = receipt["status"] if receipt else "not_requested"
            reason = receipt["reason"] if receipt else skip
            if status in {"known", "partial", "empty"}:
                payload, status, reason, span = project(receipt, source, record, radius, max_items)
            point = record.location.point.model_dump() if record.location else None
            target = {"record": record.ref.model_dump(), "event_at": record.event_at.isoformat(),
                      "point": point, "radius_m": radius if point and source != "weather" else None}
            provenance = {"provider": "data.go.kr", "operation": source,
                          "retrieved_at": receipt["retrieved_at"] if receipt else None,
                          "temporal_basis": "source_observation" if span else (
                              "lookup_snapshot" if payload is not None else "unknown"),
                          "valid_time": span, "policy_version": POLICY, "synthetic": False}
            value = {"target": target, "tags": [tag], "status": status, "reason": reason,
                     "provenance": provenance, "payload_format": "data-go-kr-field-projection-v1",
                     "payload": payload, "payload_sha256": payload_hash(payload) if payload is not None else None}
            envelope = Envelope(id="env-" + payload_hash(value)[:32], **value)
            previous = [e for e in envelopes if e.target == envelope.target and e.tags == envelope.tags
                        and e.provenance.provider == "data.go.kr" and e.provenance.operation == source]
            selected.difference_update(e.id for e in previous)
            if envelope.id not in ids:
                if previous:
                    envelope.supersedes = previous[-1].id
                envelopes.append(envelope)
                ids.add(envelope.id)
            selected.add(envelope.id)
    result = snapshot.model_dump(mode="json")
    result.update(context_mode="provider", envelopes=[e.model_dump(mode="json") for e in envelopes],
                  selected_envelope_ids=[e.id for e in envelopes if e.id in selected])
    return RecordEnvelopeSnapshot.model_validate(result)


def save_run(out, original, result, reader):
    out.mkdir(parents=True, exist_ok=False)
    wire = result.model_dump(mode="json")
    (out / "snapshot.json").write_text(json.dumps(wire, ensure_ascii=False, indent=2), encoding="utf-8")
    active = [e for e in result.envelopes if e.id in result.selected_envelope_ids]
    metrics = {"policy": POLICY, "input_sha256": payload_hash(original.model_dump(mode="json")),
               "snapshot_sha256": payload_hash(wire), "synthetic_records": result.synthetic,
               "context_mode": result.context_mode, "http_requests": reader.requests,
               "cache_hits": reader.cache_hits, "query_groups": len(reader.memory),
               "records": len(result.records), "envelopes": len(result.envelopes),
               "selected_statuses": dict(Counter(e.status for e in active)),
               "source_receipt_sha256": sorted(r["sha256"] for r in reader.memory.values())}
    (out / "receipt.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 기록별 주변 정보 수집", "", "합성 사용자 기록 + 공급자 응답. LLM 호출 없음.", "",
             f"실제 HTTP 요청 {reader.requests}회 · 캐시 재사용 {reader.cache_hits}개 · 조회 그룹 {len(reader.memory)}개", "",
             "| 기록 | 종류 | 자료 | 상태 | 반환 항목 | 사유 |", "|---|---|---|---|---|---|"]
    for record in result.records:
        for envelope in active:
            if envelope.target.record == record.ref:
                count = envelope.payload["coverage"]["returned_rows"] if envelope.payload else "—"
                lines.append(f"| {record.ref.id} | {record.content.kind} | {envelope.tags[0]} | "
                             f"{envelope.status} | {count} | {envelope.reason or '—'} |")
    lines += ["", "원본 글·사진·행동 및 시각·좌표는 입력 그대로 보존한다.",
              "공원 대표점·하천 시점·상가 등록점 근접은 실제 방문이나 내부 판정이 아니다.",
              "성공한 빈 결과와 실패/부분 수집을 구별한다. 공원은 강남구 제공 자료만 조회한다.",
              "날씨는 지정한 서울 108 관측소의 시간 자료이며 핀에서 직접 측정한 값이 아니다.",
              "원본 API 응답은 private cache에 있고 이 출력에는 허용한 공급자 필드만 포함한다."]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--max-requests", type=int, default=12)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--radius", type=float, default=250)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists; choose a new run directory")
    if args.cache.resolve() == args.out.resolve():
        parser.error("private cache and public output must be separate")
    if args.cache.resolve() in args.out.resolve().parents or args.out.resolve() in args.cache.resolve().parents:
        parser.error("private cache and public output must not contain each other")
    original = RecordEnvelopeSnapshot.model_validate_json(args.input.read_text(encoding="utf-8"))
    reader = PublicDataReader(args.cache, fetch=args.fetch, refresh=args.refresh,
                              key=service_key(args.env_file) if args.fetch else "",
                              max_requests=args.max_requests, max_pages=args.max_pages)
    result = collect_snapshot(original, reader, radius=args.radius)
    print(json.dumps(save_run(args.out, original, result, reader), ensure_ascii=False))


if __name__ == "__main__":
    main()
