"""선호 부스트가 `/facility/search` 순서를 어떻게 바꾸나.

부스트 규칙 자체(밴드 안에서만 역전)는 `geo/ranking.py` 가 병원에서 이미 고정한다.
여기서 지키는 것은 시설 표면에 붙이면서 생기는 세 가지다:

1. 밴드 안에서는 부스트가 이기고, 밴드를 넘으면 거리가 이긴다
2. 부스트는 **병합된** 값에서 나온다 — 빌려온 주차장도 세어야 한다
3. 자르기가 필터가 되지 않는다 — 선호가 켜지면 limit 보다 넉넉히 받는다
"""

from app.api.facility import FacilityParams, facility_search
from tests.conftest import TEST_ORIGIN, db_session
from tests.facility.test_pet_filter import _clean, _link, _seed, facility_row

SOURCES = ("test:pet_base", "test:pet_newer")   # test_pet_filter 와 같은 원천을 쓴다


PREFIX = "랭크_"          # 원점 반경 안에 실제 시설이 있어서 내가 심은 행만 본다


async def _ranked(session, **params) -> list[str]:
    """순서를 유지한 채 이 테스트가 심은 행만. limit 은 실행 전에 넉넉히 잡는다."""
    out = await facility_search(
        FacilityParams(lat=TEST_ORIGIN[0], lng=TEST_ORIGIN[1], radius_m=2000, **params),
        session,
    )
    return [r.name for r in out.results if r.name.startswith(PREFIX)]


async def test_boost_wins_inside_a_band_and_distance_wins_across_bands():
    async with db_session() as session:
        await _clean(session)
        try:
            await _seed(session, [
                facility_row("랭크_가까움_주차없음", east_m=300),
                facility_row("랭크_같은밴드_주차", east_m=450, parking=True),
                facility_row("랭크_다음밴드_주차", east_m=900, parking=True),
            ])
            assert await _ranked(session) == [
                "랭크_가까움_주차없음", "랭크_같은밴드_주차", "랭크_다음밴드_주차",
            ], "선호가 꺼져 있으면 순서는 거리뿐이어야 한다"

            ranked = await _ranked(session, parking=True)
            assert ranked[0] == "랭크_같은밴드_주차", "밴드 안에서는 부스트가 이겨야 한다"
            assert ranked[1] == "랭크_가까움_주차없음"
            assert ranked[2] == "랭크_다음밴드_주차", "밴드를 넘는 역전은 없어야 한다"
        finally:
            await _clean(session)


async def test_borrowed_parking_also_earns_the_boost():
    """`parking` 은 빌려올 수 있는 필드다. 병합 전 자기 컬럼만 보면 순위가 표시와 갈린다."""
    async with db_session() as session:
        await _clean(session)
        try:
            await _seed(session, [facility_row("랭크_빌려주는쪽", east_m=450, parking=True)])
            await _seed(session, [facility_row("랭크_빌리는쪽", east_m=450)], source=SOURCES[1])
            await _link(session)
            await _seed(session, [facility_row("랭크_가까움_주차없음", east_m=300)])

            ranked = await _ranked(session, parking=True)
            assert "랭크_빌려주는쪽" not in ranked, "링크의 ref 쪽은 노출 행에서 빠진다"
            assert ranked[0] == "랭크_빌리는쪽", "빌려온 주차장이 부스트에 안 세어졌다"
        finally:
            await _clean(session)


async def test_widened_fetch_keeps_truncation_from_acting_as_a_filter():
    """limit 이 작아도 밴드 안 부스트가 작동해야 한다 — SQL 이 거리로 먼저 잘라버리면 안 된다."""
    async with db_session() as session:
        await _clean(session)
        try:
            await _seed(session, [
                facility_row("랭크_가까움_주차없음", east_m=300),
                facility_row("랭크_같은밴드_주차", east_m=450, parking=True),
            ])
            assert await _ranked(session, parking=True, limit=1) == ["랭크_같은밴드_주차"]
        finally:
            await _clean(session)
