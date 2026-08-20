"""좌표 없는 영업중 시설을 주소 지오코딩으로 복구한다.

인허가 원천은 `CRD_INFO_X/Y` 가 공란인 행을 준다. 좌표가 없으면 `place.location` 이
NOT NULL 이라 적재 자체가 안 되고, 적재돼도 `ST_DWithin` 반경 검색에 안 잡힌다 —
사용자에겐 **없는 병원**이 된다. 주소는 대부분 남아 있으므로 되살릴 수 있다.

실측(2026-08-20): 영업중·좌표없음 1,149곳(병원 316 · 약국 833) 중 **96.5% 회복**.
  도로명 그대로 1,022 · 지번 대체 48 · 도로명 상세제거 39 · 실패 40

**좌표만 덮어쓰지 않는다.** 무엇을 질의해 무엇에 매칭됐는지 `place.geocode` 에 남긴다
(migrations/004). 정밀도 `REGION` 은 동 단위라 수백 미터 오차가 나므로 검수 대상이다.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.mois import Kind, MoisClient, MoisRecord, MoisSource, normalize
from app.providers.base import LatLng
from app.providers.registry import geocode_provider

# 상세주소(동·호수·건물명)를 떼는 지점. "…월계로 333, 2층 (월계동)" -> "…월계로 333"
_DETAIL = re.compile(r"[,(]")

_UPSERT = text("""
INSERT INTO place (
    kind, name, address, phone, location, is_night, is_24h, hours, tags,
    source, source_id, source_updated_at, license_status_code, license_status_name,
    coordinate_source, raw_data, geocode, active, updated_at
)
SELECT
    :kind, :name, :address, :phone,
    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
    false, false, NULL, CAST(:tags AS text[]),
    :source, :source_id, :source_updated_at,
    :license_status_code, :license_status_name,
    :coordinate_source, CAST(:raw_data AS jsonb), CAST(:geocode AS jsonb),
    :active, now()
WHERE :lng BETWEEN 123 AND 133 AND :lat BETWEEN 32 AND 40
ON CONFLICT (source, source_id) DO UPDATE SET
    name = EXCLUDED.name,
    address = COALESCE(EXCLUDED.address, place.address),
    phone = COALESCE(EXCLUDED.phone, place.phone),
    -- 원천이 나중에 진짜 좌표를 주면 그쪽이 이긴다. 지오코딩은 어디까지나 대체재다.
    location = CASE WHEN place.coordinate_source = 'mois:epsg5174'
                    THEN place.location ELSE EXCLUDED.location END,
    tags = EXCLUDED.tags,
    source_updated_at = EXCLUDED.source_updated_at,
    license_status_code = EXCLUDED.license_status_code,
    license_status_name = EXCLUDED.license_status_name,
    coordinate_source = CASE WHEN place.coordinate_source = 'mois:epsg5174'
                             THEN place.coordinate_source ELSE EXCLUDED.coordinate_source END,
    raw_data = EXCLUDED.raw_data,
    geocode = EXCLUDED.geocode,
    active = EXCLUDED.active,
    updated_at = now()
RETURNING id
""")


@dataclass
class RepairStats:
    kind: str
    candidates: int = 0        # 영업중인데 좌표 없는 행
    geocoded: int = 0          # 좌표를 얻은 행
    stored: int = 0            # 실제로 DB 에 들어간 행
    failed: int = 0
    by_tier: dict | None = None
    by_precision: dict | None = None

    def as_dict(self) -> dict:
        return {"kind": self.kind, "candidates": self.candidates, "geocoded": self.geocoded,
                "stored": self.stored, "failed": self.failed,
                "by_tier": self.by_tier or {}, "by_precision": self.by_precision or {}}


def address_candidates(raw: dict) -> list[tuple[str, str]]:
    """질의 후보를 정확한 순서로. 도로명 → 도로명(상세제거) → 지번 → 지번(상세제거).

    상세제거가 따로 필요한 이유: "월계로 333, 2층 (월계동)" 처럼 동·호수가 붙으면
    주소검색이 못 잡는 경우가 있다. 건물까지만 남기면 잡힌다.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, value in (("road", raw.get("ROAD_NM_ADDR")), ("lot", raw.get("LOTNO_ADDR"))):
        base = (value or "").strip()
        if not base:
            continue
        for tier, query in ((label, base), (f"{label}_stripped", _DETAIL.split(base)[0].strip())):
            if query and query not in seen:
                seen.add(query)
                out.append((tier, query))
    return out


async def geocode_record(raw: dict) -> tuple[LatLng, dict] | None:
    """후보를 순서대로 시도. 첫 성공에서 멈추고 출처를 함께 돌려준다."""
    provider = geocode_provider()
    for tier, query in address_candidates(raw):
        hit = await provider.geocode_detailed(query) if hasattr(provider, "geocode_detailed") \
            else await provider.geocode(query)
        if hit is None:
            continue
        pos, matched, precision = (hit if isinstance(hit, tuple) else (hit, None, None))
        return pos, {"provider": provider.name, "tier": tier, "query": query,
                     "matched": matched, "precision": precision,
                     "at": datetime.now(UTC).isoformat()}
    return None


async def store_repaired(db: AsyncSession, record: MoisRecord, pos: LatLng, meta: dict) -> bool:
    row = await db.execute(_UPSERT, {
        "kind": record.kind, "name": record.name, "address": record.address,
        "phone": record.phone, "lat": pos.lat, "lng": pos.lng,
        "tags": list(record.tags), "source": record.source, "source_id": record.source_id,
        "source_updated_at": record.source_updated_at,
        "license_status_code": record.license_status_code,
        "license_status_name": record.license_status_name,
        "coordinate_source": f"{meta['provider']}:geocode",
        "raw_data": json.dumps(record.raw_data, ensure_ascii=False),
        "geocode": json.dumps(meta, ensure_ascii=False),
        "active": record.active,
    })
    return row.first() is not None


async def repair(db: AsyncSession, source: MoisSource, service_key: str, *,
                 concurrency: int = 6, limit: int | None = None) -> RepairStats:
    stats = RepairStats(kind=source.kind, by_tier={}, by_precision={})
    items = await MoisClient(service_key).fetch_all(source)

    todo: list[tuple[MoisRecord, dict]] = []
    for item in items:
        record = normalize(item, source)
        if record.x_5174 is not None and record.y_5174 is not None:
            continue                      # 원천 좌표가 있으면 건드리지 않는다
        if not record.active:
            continue                      # 폐업까지 되살릴 이유가 없다
        todo.append((record, item))
    if limit:
        todo = todo[:limit]
    stats.candidates = len(todo)

    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[MoisRecord, LatLng, dict]] = []

    async def work(record: MoisRecord, raw: dict) -> None:
        async with sem:
            hit = await geocode_record(raw)
        if hit is None:
            stats.failed += 1
            return
        pos, meta = hit
        stats.geocoded += 1
        stats.by_tier[meta["tier"]] = stats.by_tier.get(meta["tier"], 0) + 1
        p = meta.get("precision") or "?"
        stats.by_precision[p] = stats.by_precision.get(p, 0) + 1
        results.append((record, pos, meta))

    await asyncio.gather(*(work(r, raw) for r, raw in todo))

    for record, pos, meta in results:                 # 쓰기는 한 세션에서 순차로
        if await store_repaired(db, record, pos, meta):
            stats.stored += 1
    await db.commit()
    return stats


SOURCES_BY_KIND: dict[Kind, str] = {"hospital": "hospital", "pharmacy": "pharmacy"}
