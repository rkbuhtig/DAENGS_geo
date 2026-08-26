"""canonical `/v2/places/search`의 후보군·resolver·정렬 계약."""

import json
import math
from datetime import UTC, datetime

from sqlalchemy import text

from app.ingest.facility_store import upsert_rows
from app.ingest.kcisa import KINDS as KCISA_KINDS
from app.ingest.kto import KINDS as KTO_KINDS
from app.ingest.mois import SOURCES as MOIS_SOURCES
from app.place.search import PlaceKind, PlaceSearchRequest, search_place_groups
from tests.conftest import TEST_ORIGIN, db_session

_MEDICAL_SOURCE = "public:mois:animal_hospital"
_MEDICAL_REF = "test:v2:medical:hospital"
_DEV_MEDICAL_REF = "test:v2:dev:hospital"
_NULL_REF_FACILITY_NAME = "V2계약식별자없는카페"
_FACILITY_REFS = ("test:v2:kcisa:cafe-near", "test:v2:kcisa:cafe-far", "test:v2:kto:shop")


def _lng_at(east_m: int) -> float:
    return TEST_ORIGIN[1] + east_m / (
        111_320 * math.cos(math.radians(TEST_ORIGIN[0]))
    )


def _facility_row(
    ref: str,
    name: str,
    kind: str,
    category3: str,
    east_m: int,
    *,
    raw: dict | None = None,
) -> dict:
    return {
        "source_ref": ref,
        "name": name,
        "kind": kind,
        "category3": category3,
        "sido": None,
        "sigungu": None,
        "address": "테스트",
        "phone": None,
        "homepage": None,
        "hours_text": None,
        "closed_days": None,
        "parking": None,
        "indoor": None,
        "outdoor": None,
        "pet": "{}",
        "lat": TEST_ORIGIN[0],
        "lng": _lng_at(east_m),
        "last_written": None,
        "raw": json.dumps(raw or {}),
    }


async def _delete_owned_rows(session) -> None:
    await session.execute(text(
        "DELETE FROM place WHERE source_id = ANY(:refs)"
    ), {"refs": [_MEDICAL_REF, _DEV_MEDICAL_REF]})
    await session.execute(text(
        "DELETE FROM facility WHERE source_ref = ANY(:refs)"
    ), {"refs": list(_FACILITY_REFS)})
    await session.execute(text(
        "DELETE FROM facility WHERE source = 'kcisa' AND source_ref IS NULL AND name = :name"
    ), {"name": _NULL_REF_FACILITY_NAME})


def test_place_kind_exactly_matches_all_resolver_vocabularies():
    resolver_kinds = {
        *KCISA_KINDS.values(),
        *KTO_KINDS.values(),
        *(source.kind for source in MOIS_SOURCES.values()),
        "etc",
    }
    assert {kind.value for kind in PlaceKind} == resolver_kinds


def test_default_group_limit_stays_inside_the_total_budget():
    request = PlaceSearchRequest(
        lat=37.5,
        lng=127.0,
        kinds=["hospital", "cafe", "shopping"],
    )
    assert request.effective_limit_per_kind == 1666
    assert request.effective_limit_per_kind * len(request.kinds) <= 5000


async def test_v2_groups_kinds_and_sorts_only_inside_each_candidate_set():
    """의료/시설을 한 전역 순위로 섞지 않고 요청 kind 순서의 독립 그룹으로 돌려준다."""
    async with db_session() as session:
        await _delete_owned_rows(session)
        await session.commit()
        try:
            now = datetime.now(UTC)
            await session.execute(text("""
                INSERT INTO place (
                    kind, name, address, phone, location, is_night, is_24h, hours, tags,
                    source, source_id, source_updated_at, license_status_code,
                    license_status_name, active
                ) VALUES (
                    'hospital', 'V2계약동물병원', '테스트', '02-0',
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    false, false, NULL, ARRAY[]::text[], :source, :ref, :updated,
                    '01', '영업/정상', true
                ), (
                    'hospital', 'V2제외개발병원', '테스트', '02-1',
                    ST_SetSRID(ST_MakePoint(:dev_lng, :lat), 4326)::geography,
                    false, false, NULL, ARRAY[]::text[], 'dev', :dev_ref, :updated,
                    '01', '영업/정상', true
                )
            """), {
                "lat": TEST_ORIGIN[0],
                "lng": _lng_at(300),
                "dev_lng": _lng_at(50),
                "source": _MEDICAL_SOURCE,
                "ref": _MEDICAL_REF,
                "dev_ref": _DEV_MEDICAL_REF,
                "updated": now,
            })
            await upsert_rows(session, "kcisa", [
                _facility_row(_FACILITY_REFS[1], "먼카페", "cafe", "카페", 400),
                _facility_row(_FACILITY_REFS[0], "가까운카페", "cafe", "카페", 100),
            ], "2026-08-26", now)
            await upsert_rows(session, "kto", [
                _facility_row(
                    _FACILITY_REFS[2], "명시한쇼핑", "shopping", "SH040300", 200,
                    raw={"contenttypeid": "38", "lclsSystm3": "SH040300"},
                ),
            ], "2026-08-26", now)
            await session.execute(text("""
                INSERT INTO facility (
                    source, source_ref, name, kind, category3, location, snapshot, pet
                ) VALUES (
                    'kcisa', NULL, :name, 'cafe', '카페',
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    'legacy-null-ref', '{}'::jsonb
                )
            """), {
                "name": _NULL_REF_FACILITY_NAME,
                "lat": TEST_ORIGIN[0],
                "lng": _lng_at(25),
            })
            await session.commit()

            response = await search_place_groups(session, PlaceSearchRequest(
                lat=TEST_ORIGIN[0],
                lng=TEST_ORIGIN[1],
                radius_m=1000,
                kinds=["shopping", "hospital", "cafe"],
                limit_per_kind=2,
            ))

            assert [group.kind for group in response.groups] == [
                "shopping", "hospital", "cafe",
            ]
            assert [[item.name for item in group.results] for group in response.groups] == [
                ["명시한쇼핑"], ["V2계약동물병원"], ["가까운카페", "먼카페"],
            ]
            assert all(group.sort.type == "distance" for group in response.groups)
            assert all(group.limit == 2 for group in response.groups)
            assert response.groups[0].results[0].key.source == "kto"
            assert response.groups[1].results[0].key.source == _MEDICAL_SOURCE
            assert "V2제외개발병원" not in {
                item.name for item in response.groups[1].results
            }
            assert _NULL_REF_FACILITY_NAME not in {
                item.name for item in response.groups[2].results
            }
            assert response.groups[2].results[0].facts.parking is None

            cut = await search_place_groups(session, PlaceSearchRequest(
                lat=TEST_ORIGIN[0],
                lng=TEST_ORIGIN[1],
                radius_m=1000,
                kinds=["cafe"],
                limit_per_kind=1,
            ))
            assert [item.name for item in cut.groups[0].results] == ["가까운카페"]
            assert cut.groups[0].truncated is True
        finally:
            await session.rollback()
            await _delete_owned_rows(session)
            await session.commit()
