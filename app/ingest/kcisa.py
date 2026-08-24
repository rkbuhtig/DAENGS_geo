"""KCISA 반려동물 동반 문화시설 CSV → facility 기반층 적재.

`python -m app.ingest.kcisa --csv <path> --snapshot 2025-03-24`

증분 없음: 원천에 안정 ID가 없어 스냅샷 **통째 교체**가 유일하게 결정론적이다.
한 트랜잭션 안에서 전량 삭제 → 적재 → 의료 링크 재구축까지 간다. 실패하면 이전
스냅샷이 그대로 남는다. 의료 검색이 이 표를 직접 읽지 않고 place(MOIS)를 통해
읽는 한, 교체 중에도 병원/약국 기능은 흔들리지 않는다.

원천 좌표는 WGS84. '정보없음'은 None으로 눕힌다 — 모름을 값으로 취급하지 않는다.
"""

import argparse
import asyncio
import csv
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.ingest.linking import rebuild_links

SOURCE = "public:kcisa:pet_facility"

# 카테고리3 → kind 슬러그. 새 값이 나타나면 'etc'로 눕히고 category3 원문으로 추적한다.
KINDS = {
    "동물병원": "hospital",
    "동물약국": "pharmacy",
    "반려동물용품": "goods",
    "미용": "grooming",
    "여행지": "travel",
    "박물관": "museum",
    "미술관": "gallery",
    "문예회관": "arts_center",
    "카페": "cafe",
    "식당": "restaurant",
    "펜션": "pension",
    "호텔": "hotel",
    "위탁관리": "boarding",
}

_MISSING = {"", "정보없음", "-", "없음", "NULL"}


def _clean(value: str | None) -> str | None:
    text_ = (value or "").strip()
    return None if text_ in _MISSING else text_


def _flag(value: str | None) -> bool | None:
    v = _clean(value)
    if v is None:
        return None
    return v.upper().startswith("Y")


def parse_row(row: dict) -> dict | None:
    """CSV 한 행 → insert 파라미터. 좌표 불량이면 None (거부 계수용)."""
    name = _clean(row.get("시설명"))
    category3 = _clean(row.get("카테고리3"))
    if not name or not category3:
        return None
    try:
        lat = float(row["위도"])
        lng = float(row["경도"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (32.0 <= lat <= 40.0 and 123.0 <= lng <= 133.0):
        return None

    written = None
    raw_written = _clean(row.get("최종작성일"))
    if raw_written:
        try:
            written = date.fromisoformat(raw_written[:10])
        except ValueError:
            written = None

    pet = {
        k: v
        for k, v in {
            "allowed": _clean(row.get("반려동물 동반 가능정보")),
            "exclusive": _clean(row.get("반려동물 전용 정보")),
            "size": _clean(row.get("입장 가능 동물 크기")),
            "restrictions": _clean(row.get("반려동물 제한사항")),
            "extra_fee": _clean(row.get("애견 동반 추가 요금")),
        }.items()
        if v is not None
    }

    return {
        "name": name,
        "kind": KINDS.get(category3, "etc"),
        "category3": category3,
        "sido": _clean(row.get("시도 명칭")),
        "sigungu": _clean(row.get("시군구 명칭")),
        "address": _clean(row.get("도로명주소")) or _clean(row.get("지번주소")),
        "phone": _clean(row.get("전화번호")),
        "homepage": _clean(row.get("홈페이지")),
        "hours_text": _clean(row.get("운영시간")),
        "closed_days": _clean(row.get("휴무일")),
        "parking": _flag(row.get("주차 가능여부")),
        "indoor": _flag(row.get("장소(실내) 여부")),
        "outdoor": _flag(row.get("장소(실외)여부")),
        "pet": json.dumps(pet, ensure_ascii=False),
        "lat": lat,
        "lng": lng,
        "last_written": written,
    }


def load_rows(path: Path) -> tuple[list[dict], int, int]:
    """(적재 행, 거부 수, 중복 수). 중복 키 = (시설명, 위도, 경도) 원문."""
    parsed: list[dict] = []
    rejected = 0
    duplicates = 0
    seen: set[tuple[str, str, str]] = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("시설명", ""), row.get("위도", ""), row.get("경도", ""))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            item = parse_row(row)
            if item is None:
                rejected += 1
                continue
            parsed.append(item)
    return parsed, rejected, duplicates


_INSERT = text("""
INSERT INTO facility (source, name, kind, category3, sido, sigungu, address, phone, homepage,
                      hours_text, closed_days, parking, indoor, outdoor, pet,
                      location, last_written, snapshot)
VALUES ('kcisa', :name, :kind, :category3, :sido, :sigungu, :address, :phone, :homepage,
        :hours_text, :closed_days, :parking, :indoor, :outdoor, CAST(:pet AS jsonb),
        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :last_written, :snapshot)
""")

async def replace_snapshot(session: AsyncSession, rows: list[dict], snapshot: str) -> dict:
    for row in rows:
        row["snapshot"] = snapshot
    await session.execute(text("DELETE FROM facility WHERE source = 'kcisa'"))
    for start in range(0, len(rows), 1000):
        await session.execute(_INSERT, rows[start : start + 1000])
    linked = await rebuild_links(session)
    await session.execute(
        text("""
            INSERT INTO ingest_state (source, watermark, updated_at)
            VALUES (:source, :watermark, now())
            ON CONFLICT (source) DO UPDATE SET watermark = :watermark, updated_at = now()
        """),
        {"source": SOURCE, "watermark": snapshot},
    )
    return {"stored": len(rows), **linked}


async def _run(csv_path: Path, snapshot: str) -> None:
    rows, rejected, duplicates = load_rows(csv_path)
    if not rows:
        raise SystemExit(f"refusing empty snapshot from {csv_path}")
    async with SessionLocal() as session:
        stats = await replace_snapshot(session, rows, snapshot)
        await session.commit()
    print(json.dumps(
        {"source": SOURCE, "snapshot": snapshot, "rejected": rejected,
         "duplicates": duplicates, **stats},
        ensure_ascii=False,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description="KCISA 문화시설 CSV를 facility에 스냅샷 교체 적재")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, help="원천 스냅샷 날짜, 예: 2025-03-24")
    args = parser.parse_args()
    asyncio.run(_run(args.csv, args.snapshot))


if __name__ == "__main__":
    main()
