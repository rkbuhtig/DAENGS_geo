"""한국관광공사 반려동물 동반여행 (KorPetTourService2) → facility 기반층 두 번째 원천.

`python -m app.ingest.kto --snapshot 2026-08-24`

areaBasedList2 전량(~9,700건, 100건×97페이지)을 받아 source='kto'로 통째 교체한다.
detailPetTour2(시설별 동반 상세)는 건당 1호출 = 전량 ~9,700호출이라 개발계정
일일 트래픽을 넘본다 — 기본은 안 받고, `--details N`으로 상한을 정해 받는다.
받은 만큼만 pet 에 채워지고 나머지는 raw의 목록 필드로만 남는다.

MOIS와 같은 원칙: 사용자 검색 시 호출 없음, 배치 전용. 좌표는 원천이 WGS84.
"""

import argparse
import asyncio
import json
from datetime import date

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal
from app.ingest.linking import rebuild_links

SOURCE = "public:kto:pet_tour"
BASE_URL = "https://apis.data.go.kr/B551011/KorPetTourService2"

# contenttypeid → kind. KCISA와 다른 분류 체계라 겹치는 슬러그만 겹치게 맞춘다.
KINDS = {
    "12": "travel",
    "14": "culture",
    "28": "leisure",
    "32": "stay",
    "38": "goods",
    "39": "restaurant",
}


class KtoApiError(RuntimeError):
    pass


def _params(**extra: str) -> dict:
    from urllib.parse import unquote

    return {
        "serviceKey": unquote(settings.kto_service_key.strip()),
        "MobileOS": "ETC",
        "MobileApp": "daengs",
        "_type": "json",
        **extra,
    }


def _body(payload: dict) -> dict:
    try:
        response = payload["response"]
        if str(response["header"]["resultCode"]) not in ("0", "00", "0000"):
            raise KtoApiError(response["header"].get("resultMsg", "unknown"))
        return response["body"]
    except (KeyError, TypeError) as exc:
        # 인증·트래픽 오류는 response 봉투가 아니라 OpenAPI_ServiceResponse로 온다
        raise KtoApiError(f"invalid KTO envelope: {str(payload)[:200]}") from exc


async def fetch_all(client: httpx.AsyncClient) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        r = await client.get(
            f"{BASE_URL}/areaBasedList2",
            params=_params(numOfRows=str(settings.kto_page_size), pageNo=str(page)),
        )
        r.raise_for_status()
        body = _body(r.json())
        chunk = (body.get("items") or {}).get("item") or []
        if isinstance(chunk, dict):
            chunk = [chunk]
        items.extend(chunk)
        total = int(body["totalCount"])
        if page * settings.kto_page_size >= total:
            if len(items) < total:
                raise KtoApiError(f"received {len(items)} before totalCount={total}")
            return items
        page += 1


async def fetch_pet_detail(client: httpx.AsyncClient, content_id: str) -> dict | None:
    """429(트래픽 제한)는 백오프 후 재시도, 그래도 안 되면 포기하고 None.

    상세는 보강이지 본체가 아니다 — 상세 실패로 적재 전체가 죽으면 안 된다.
    """
    for attempt in range(4):
        r = await client.get(
            f"{BASE_URL}/detailPetTour2", params=_params(contentId=content_id)
        )
        if r.status_code == 429:
            await asyncio.sleep(1.0 * (2**attempt))
            continue
        r.raise_for_status()
        break
    else:
        return None
    item = (_body(r.json()).get("items") or {}).get("item") or []
    if isinstance(item, dict):
        item = [item]
    if not item:
        return None
    detail = {k: v for k, v in item[0].items() if v not in ("", None) and k != "contentid"}
    return detail or None


def parse_item(item: dict) -> dict | None:
    name = (item.get("title") or "").strip()
    cid = (item.get("contentid") or "").strip()
    try:
        lat, lng = float(item["mapy"]), float(item["mapx"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (name and cid and 32.0 <= lat <= 40.0 and 123.0 <= lng <= 133.0):
        return None
    modified = (item.get("modifiedtime") or "")[:8]
    written = None
    if len(modified) == 8 and modified.isdigit():
        written = date(int(modified[:4]), int(modified[4:6]), int(modified[6:8]))
    return {
        "name": name,
        "kind": KINDS.get(str(item.get("contenttypeid")), "etc"),
        "category3": str(item.get("lclsSystm3") or item.get("contenttypeid") or ""),
        "sido": None,
        "sigungu": None,
        "address": (item.get("addr1") or "").strip() or None,
        "phone": (item.get("tel") or "").strip() or None,
        "homepage": None,                    # detailCommon2에만 있음 — 상세 미수집이면 없음
        "hours_text": None,                  # detailIntro2에만 있음 — 동일
        "closed_days": None,
        "parking": None,
        "indoor": None,
        "outdoor": None,
        "pet": json.dumps({}, ensure_ascii=False),
        "lat": lat,
        "lng": lng,
        "last_written": written,
        "content_id": cid,
        "raw": json.dumps(item, ensure_ascii=False),
    }


_INSERT = text("""
INSERT INTO facility (source, name, kind, category3, sido, sigungu, address, phone, homepage,
                      hours_text, closed_days, parking, indoor, outdoor, pet,
                      location, last_written, snapshot, raw)
VALUES ('kto', :name, :kind, :category3, :sido, :sigungu, :address, :phone, :homepage,
        :hours_text, :closed_days, :parking, :indoor, :outdoor, CAST(:pet AS jsonb),
        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :last_written, :snapshot,
        CAST(:raw AS jsonb))
""")


async def replace_snapshot(session: AsyncSession, rows: list[dict], snapshot: str) -> dict:
    for row in rows:
        row["snapshot"] = snapshot
        row.pop("content_id", None)
    await session.execute(text("DELETE FROM facility WHERE source = 'kto'"))
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


async def _run(snapshot: str, details: int) -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        items = await fetch_all(client)
        rows = [r for r in (parse_item(x) for x in items) if r is not None]
        if not rows:
            raise SystemExit("refusing empty KTO snapshot")

        # 직렬 + 간격. 병렬 5개는 429가 확인됐다(2026-08-24). 상세 실패는 건너뛴다.
        fetched_details = 0
        if details > 0:
            for row in rows[:details]:
                try:
                    pet = await fetch_pet_detail(client, row["content_id"])
                except (httpx.HTTPError, KtoApiError):
                    continue
                if pet:
                    row["pet"] = json.dumps(pet, ensure_ascii=False)
                    fetched_details += 1
                await asyncio.sleep(0.15)

    async with SessionLocal() as session:
        stats = await replace_snapshot(session, rows, snapshot)
        await session.commit()
    print(json.dumps(
        {"source": SOURCE, "snapshot": snapshot, "received": len(items),
         "rejected": len(items) - len(rows), "pet_details": fetched_details, **stats},
        ensure_ascii=False,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description="관광공사 반려동물 동반여행을 facility에 교체 적재")
    parser.add_argument("--snapshot", required=True, help="적재 기준일, 예: 2026-08-24")
    parser.add_argument("--details", type=int, default=0,
                        help="detailPetTour2 수집 상한 (건당 1호출 — 일일 트래픽 주의)")
    args = parser.parse_args()
    if not settings.kto_service_key:
        raise SystemExit("DAENGS_KTO_SERVICE_KEY is required")
    asyncio.run(_run(args.snapshot, args.details))


if __name__ == "__main__":
    main()
