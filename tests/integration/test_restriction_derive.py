"""제약 파생 배치가 실DB에서 계약을 지키는가.

Decision: #70

단위 테스트(`tests/place/test_restriction_derive.py`)는 `derive()` 하나를 본다. 여기서는
배치가 **행을 어떻게 다루는지**를 본다 — 그건 SQL 과 CHECK 제약이 함께 결정하므로
DB 없이는 잴 수 없다.

  멱등      같은 배치를 두 번 돌려도 두 번째는 0행이다 (커서·미처리 조건이 맞물리는가)
  버전 감지  표를 고치면 `--all` 없이도 옛 행을 다시 판다 — 안 그러면 옛 규칙 행이
            스스로 낡았다고 말하지 못한 채 남는다
  제약      `unknown` 행은 `parse_state` 가 비어야 한다. 이 규칙은 리비전 0018 의
            CHECK 와 `derive()` 양쪽에 있고, 둘이 어긋나면 배치가 중간에 죽는다
"""

from sqlalchemy import text

from app.ingest.freshness import EMPTY_INPUT
from app.ingest.restrictions import derive_all
from app.place.restriction_map import RESTRICTION_SEMANTICS_VERSION
from tests.conftest import TEST_ORIGIN, db_session

# 동해 한복판 — 다른 통합 테스트와 같은 격리 전략(좌표 + 전용 source)을 쓴다.
SOURCE = "test:restrictions"

_INSERT = text("""
INSERT INTO facility
    (name, kind, category3, address, source, source_ref, pet, location, snapshot)
VALUES (:name, 'cafe', 'cafe', '테스트', :source, :ref, CAST(:pet AS jsonb),
        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, 'test')
""")

_FETCH = text("""
SELECT name, restriction_state, restriction_parse_state,
       restriction_predicates, restriction_semantics_version
FROM facility WHERE source = :s
""")

_DELETE = text("DELETE FROM facility WHERE source = :s")


async def _seed(session, rows: list[tuple[str, str | None]]) -> None:
    """(이름, restrictions 원문). 원문이 `None` 이면 `pet` 봉투 자체가 없는 행이다."""
    await session.execute(_DELETE, {"s": SOURCE})
    for index, (name, restrictions) in enumerate(rows):
        pet = None if restrictions is None else f'{{"restrictions": "{restrictions}"}}'
        await session.execute(
            _INSERT,
            {
                "name": name,
                "source": SOURCE,
                "ref": f"{SOURCE}:{index}",
                "pet": pet,
                "lat": TEST_ORIGIN[0],
                "lng": TEST_ORIGIN[1] + index / 91_000.0,
            },
        )
    await session.commit()


async def _fetch(session) -> dict[str, dict]:
    result = await session.execute(_FETCH, {"s": SOURCE})
    return {row.name: dict(row._mapping) for row in result}


async def test_three_zero_tag_states_are_distinguishable():
    """칩이 0개인 세 행이 DB 에서 서로 다른 값을 갖는다."""
    async with db_session() as session:
        await _seed(
            session,
            [
                ("모름", None),
                ("제한없음확인", "제한사항 없음"),
                ("못읽음", "표에 없는 새 문장"),
            ],
        )
        await derive_all(session, sources=(SOURCE,))
        rows = await _fetch(session)

        assert rows["모름"]["restriction_state"] == "unknown"
        assert rows["모름"]["restriction_parse_state"] is None

        assert rows["제한없음확인"]["restriction_state"] == "none_confirmed"
        assert rows["제한없음확인"]["restriction_parse_state"] == "mapped"

        assert rows["못읽음"]["restriction_state"] == "restricted"
        assert rows["못읽음"]["restriction_parse_state"] == "raw_only"

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_conditional_subject_reaches_the_database():
    """`applies_to` 가 JSONB 까지 살아남아야 PR 4 가 개별 개에 맞춰 거를 수 있다."""
    async with db_session() as session:
        await _seed(session, [("조건부", "대형견 입마개, 목줄")])
        await derive_all(session, sources=(SOURCE,))
        predicates = (await _fetch(session))["조건부"]["restriction_predicates"]

        assert {
            "code": "require:muzzle", "applies_to": "size:large",
            "params": {}, "certainty": "firm",
        } in predicates
        assert {
            "code": "require:leash", "applies_to": "all",
            "params": {}, "certainty": "firm",
        } in predicates

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_second_run_touches_nothing():
    """멱등. 커서와 미처리 조건이 어긋나면 여기서 무한 반복이 드러난다."""
    async with db_session() as session:
        await _seed(session, [("가", "목줄"), ("나", None), ("다", "제한사항 없음")])
        first = await derive_all(session, sources=(SOURCE,))
        second = await derive_all(session, sources=(SOURCE,))

        assert first.updated == 3
        assert second.scanned == 0

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_stale_version_is_repicked_without_the_all_flag():
    """표를 고치고 `--all` 을 깜빡해도 옛 규칙 행이 남지 않는다."""
    async with db_session() as session:
        await _seed(session, [("가", "목줄")])
        await derive_all(session, sources=(SOURCE,))
        await session.execute(
            text("""
            UPDATE facility SET restriction_semantics_version = 'kcisa-restrictions/0'
            WHERE source = :s
            """),
            {"s": SOURCE},
        )
        await session.commit()

        stats = await derive_all(session, sources=(SOURCE,))
        rows = await _fetch(session)

        assert stats.updated == 1
        assert rows["가"]["restriction_semantics_version"] == RESTRICTION_SEMANTICS_VERSION

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_redo_repicks_everything():
    async with db_session() as session:
        await _seed(session, [("가", "목줄"), ("나", "케이지 이용")])
        await derive_all(session, sources=(SOURCE,))
        stats = await derive_all(session, redo=True, sources=(SOURCE,))

        assert stats.updated == 2

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_changed_source_text_is_repicked():
    """**리뷰 지적 ①.** 재적재가 원문을 덮어쓰면 파생값도 따라와야 한다.

    버전만 보던 때는 이 배치가 0행을 훑고 지나갔고, 그 행은 바뀐 원문 위에
    옛 술어를 계속 들고 있었다.
    """
    async with db_session() as session:
        await _seed(session, [("가", "목줄")])
        await derive_all(session, sources=(SOURCE,))
        assert (await _fetch(session))["가"]["restriction_predicates"][0]["code"] == (
            "require:leash"
        )

        # 재적재가 원문만 덮어쓴 상황 — 파생 컬럼은 그대로다.
        await session.execute(
            text("""
            UPDATE facility SET pet = jsonb_set(pet, '{restrictions}', '"대형견 입장 불가"')
            WHERE source = :s
            """),
            {"s": SOURCE},
        )
        await session.commit()

        stats = await derive_all(session, sources=(SOURCE,))
        rows = await _fetch(session)

        assert stats.updated == 1, "바뀐 원문을 미처리로 못 잡았다"
        assert rows["가"]["restriction_predicates"][0]["code"] == "deny:size"

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_unchanged_rows_are_not_repicked_after_a_neighbour_changes():
    """지문은 **바뀐 행만** 고른다 — 타임스탬프 비교와 갈리는 지점이다."""
    async with db_session() as session:
        await _seed(session, [("가", "목줄"), ("나", "케이지 이용")])
        await derive_all(session, sources=(SOURCE,))

        await session.execute(
            text("""
            UPDATE facility SET pet = jsonb_set(pet, '{restrictions}', '"안고 있어야 함"')
            WHERE source = :s AND name = '가'
            """),
            {"s": SOURCE},
        )
        await session.commit()

        stats = await derive_all(session, sources=(SOURCE,))
        assert stats.updated == 1, "안 바뀐 행까지 다시 팠다"

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()


async def test_sql_and_python_agree_on_the_fingerprint():
    """둘이 어긋나면 배치가 **같은 행을 영원히 다시 판다.**

    미처리 조건은 SQL 이 계산하고 저장값은 파이썬이 만든다. 한쪽만 바꾸면
    실행할 때마다 전 행이 미처리로 잡히고, 그 사실이 조용히 지나간다.
    """
    async with db_session() as session:
        await _seed(session, [("가", "목줄"), ("나", None)])
        await derive_all(session, sources=(SOURCE,))

        result = await session.execute(
            text("""
            SELECT restriction_source_fp = md5(COALESCE(pet->>'restrictions', :empty)) AS agrees
            FROM facility WHERE source = :s
            """),
            {"s": SOURCE, "empty": EMPTY_INPUT},
        )
        assert all(row.agrees for row in result), "SQL 해시와 파이썬 지문이 다르다"

        await session.execute(_DELETE, {"s": SOURCE})
        await session.commit()
