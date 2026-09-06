"""Real migration and multi-connection tests in a unique disposable PostgreSQL schema.

Set DAENGS_POLICY_TEST_URL to an explicitly selected, migrated test DB. Once set,
connection/migration failures fail the suite; CI always sets it. No app .env fallback.
"""

import asyncio
import importlib.util
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.features.territory.game.policy import (
    DAY_MS,
    HOUR_MS,
    POINT_DENOMINATOR,
    GameError,
    Ownership,
    OwnershipCandidate,
    Rules,
    SeasonContext,
)
from app.features.territory.game.policy_service import (
    apply_ownership_in_transaction,
    finalize_in_transaction,
)
from app.features.territory.game.postgres_store import PostgresPolicyTransaction, create_season

MIGRATION = Path(__file__).resolve().parents[2] / "alembic/versions/0033_territory_policy.py"


def migrate(connection, direction):
    spec = importlib.util.spec_from_file_location("policy_revision", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


class Database:
    def __init__(self, engine):
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def query(self, sql, **params):
        async with self.sessions.begin() as session:
            result = await session.execute(text(sql), params)
            return result.mappings().all() if result.returns_rows else []

    async def seed(self, *, rules=None, initial_owners=None, starts=0, ends=DAY_MS, sid="s"):
        async with self.sessions.begin() as session:
            await create_season(
                session,
                SeasonContext(sid, starts, ends, rules or Rules()),
                "neighborhood",
                ["A", "B"],
                initial_owners=initial_owners,
            )

    async def apply(self, candidate=None, *, at=0, adapter=None):
        async with self.sessions.begin() as session:
            tx = (adapter or ClockedTransaction)(session, at)
            return await apply_ownership_in_transaction(tx, candidate or command())

    async def close(self, *, at=DAY_MS, adapter=None):
        async with self.sessions.begin() as session:
            return await finalize_in_transaction((adapter or ClockedTransaction)(session, at), "s")


class ClockedTransaction(PostgresPolicyTransaction):
    """Only the clock is synthetic; locks, connections and all writes are real SQL."""

    def __init__(self, session, at):
        super().__init__(session)
        self.at = at

    async def now_ms(self):
        return self.at


def command(event="mark:1", pet="p1", version=0, site="A", *, photo=False, attempt=None):
    return OwnershipCandidate(
        "s",
        event,
        site,
        version,
        pet,
        f"session:{pet}",
        attempt or f"claim:{event}",
        "VERIFIED" if photo else "UNVERIFIED",
        "PHOTO_VERIFIED" if photo else "MARK",
    )


@pytest.fixture
async def db():
    url = os.environ.get("DAENGS_POLICY_TEST_URL")
    if not url:
        pytest.skip("Set DAENGS_POLICY_TEST_URL to a migrated disposable PostgreSQL DB")
    schema = "test_territory_policy_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {"search_path": schema, "statement_timeout": "10000"},
        },
    )
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        async with engine.begin() as conn:
            # Copy the actual migrated Geo source shape, not an invented ownership fixture.
            await conn.execute(
                text("CREATE TABLE territory_site (LIKE public.territory_site INCLUDING ALL)")
            )
            await conn.execute(
                text("""
                INSERT INTO territory_site (site_id, source, kind, location)
                VALUES ('A', 'test', 'unknown', public.ST_GeogFromText('POINT(130 37)')),
                       ('B', 'test', 'unknown', public.ST_GeogFromText('POINT(130 38)'))
            """)
            )
            await conn.run_sync(migrate, "upgrade")
        yield Database(engine)
    finally:
        await engine.dispose()
        # Identifier is generated here; never accept a caller's schema for recursive cleanup.
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await admin.dispose()


async def test_migration_upgrade_downgrade_upgrade_preserves_geo_sites(db):
    await db.seed()
    await db.apply()
    async with db.engine.begin() as conn:
        await conn.run_sync(migrate, "downgrade")
        assert (await conn.execute(text("SELECT count(*) FROM territory_site"))).scalar_one() == 2
        await conn.run_sync(migrate, "upgrade")
    assert await db.query("SELECT * FROM territory_policy_season") == []
    await db.seed()
    assert (await db.apply()).bonus == 100


async def test_real_transaction_commit_and_fresh_connection_replay(db):
    await db.seed()
    async with db.sessions.begin() as session:
        receipt = await apply_ownership_in_transaction(ClockedTransaction(session, 0), command())
        rows = await db.query("SELECT pet_id FROM territory_policy_site WHERE site_id='A'")
        assert rows[0]["pet_id"] is None  # no hidden commit
    assert await db.apply(at=HOUR_MS) == receipt
    assert len(await db.query("SELECT * FROM territory_policy_event")) == 1
    assert (await db.query("SELECT bonus FROM territory_policy_account"))[0]["bonus"] == 100


@pytest.mark.parametrize("stage", ["save_scores", "save_receipt"])
async def test_sql_failure_after_partial_writes_rolls_back_everything(db, stage):
    class Failing(ClockedTransaction):
        async def save_scores(self, sid, accounts):
            await super().save_scores(sid, accounts)
            if stage == "save_scores":
                await self.session.execute(text("SELECT 1 / 0"))

        async def save_receipt(self, receipt):
            await super().save_receipt(receipt)
            if stage == "save_receipt":
                await self.session.execute(text("SELECT 1 / 0"))

    await db.seed(rules=Rules(repeat_bonus="daily_pet_site"))
    with pytest.raises(DBAPIError):
        await db.apply(adapter=Failing)
    for table in ["account", "bonus", "event", "receipt", "attempt"]:
        assert await db.query(f"SELECT * FROM territory_policy_{table}") == []
    assert (await db.query("SELECT pet_id FROM territory_policy_site WHERE site_id='A'"))[0][
        "pet_id"
    ] is None
    assert (await db.apply()).bonus == 100


async def test_multi_connection_duplicates_and_competing_takeovers(db):
    await db.seed()
    receipts = await asyncio.wait_for(asyncio.gather(*(db.apply() for _ in range(4))), 8)
    assert all(r == receipts[0] for r in receipts)
    results = await asyncio.wait_for(
        asyncio.gather(
            db.apply(command("photo:2", "p2", 1, photo=True), at=600_000),
            db.apply(command("photo:3", "p3", 1, photo=True), at=600_000),
            return_exceptions=True,
        ),
        8,
    )
    assert [str(r) for r in results if isinstance(r, GameError)] == ["site_changed"]
    assert (await db.query("SELECT sum(bonus) AS total FROM territory_policy_account"))[0][
        "total"
    ] == 200
    assert await db.apply(at=HOUR_MS) == receipts[0]
    assert (await db.query("SELECT pet_id FROM territory_policy_site WHERE site_id='A'"))[0][
        "pet_id"
    ] != "p1"


async def test_same_dog_different_sites_settles_old_multiplier_and_daily_cap(db):
    await db.seed(rules=Rules(repeat_bonus="daily_pet_site"))
    await asyncio.gather(db.apply(), db.apply(command("mark:2", site="B")))
    await db.apply(command("photo:3", "p2", 1, photo=True), at=HOUR_MS)
    receipt = await db.apply(command("photo:4", "p1", 2, photo=True), at=2 * HOUR_MS)
    assert receipt.bonus == 0
    score = (await db.query("SELECT * FROM territory_policy_account WHERE pet_id='p1'"))[0]
    assert int(score["holding_units"]) == 32 * POINT_DENOMINATOR
    assert score["current_count"] == 2


async def test_protected_photo_has_no_policy_writes_and_can_preserve_host_evidence(db):
    await db.seed()
    await db.apply()
    async with db.sessions.begin() as session:
        await session.execute(text("CREATE TABLE verified_visit (photo_id text PRIMARY KEY)"))
    async with db.sessions.begin() as session:
        await session.execute(text("INSERT INTO verified_visit VALUES ('photo:2')"))
        with pytest.raises(GameError, match="protected"):
            await apply_ownership_in_transaction(
                ClockedTransaction(session, 599_999), command("photo:2", "p2", 1, photo=True)
            )
    assert len(await db.query("SELECT * FROM verified_visit")) == 1
    assert len(await db.query("SELECT * FROM territory_policy_account")) == 1
    assert (await db.apply(command("photo:2", "p2", 1, photo=True), at=600_000)).bonus == 100


async def test_backfill_initial_counts_original_time_and_certification(db):
    await db.seed(
        rules=Rules(unverified_scores=False),
        starts=1000,
        initial_owners={
            "A": Ownership("p1", "walk:old", "claim:old", "UNVERIFIED", 1),
            "B": Ownership("p1", "walk:old", "claim:other", "VERIFIED", 2),
        },
    )
    rows = await db.query("SELECT * FROM territory_policy_site ORDER BY site_id")
    assert [r["imported_occupied_ms"] for r in rows] == [1, 2]
    assert [r["occupied_ms"] for r in rows] == [1000, 1000]
    c = command("photo:proof", version=1, photo=True, attempt="claim:old")
    c = replace(c, session_id="walk:old")
    assert (await db.apply(c, at=1000 + HOUR_MS)).bonus == 0
    score = (await db.query("SELECT * FROM territory_policy_account"))[0]
    assert (score["bonus"], score["claims"], score["current_count"], score["scoring_count"]) == (
        0,
        0,
        2,
        2,
    )
    assert int(score["holding_units"]) == 10 * POINT_DENOMINATOR
    assert (await db.query("SELECT occupied_ms FROM territory_policy_site WHERE site_id='A'"))[0][
        "occupied_ms"
    ] == 1000


async def test_finalize_rollback_history_immutability_and_late_callback(db):
    class Failing(ClockedTransaction):
        async def finalize(self, plan):
            await super().finalize(plan)
            await self.session.execute(text("SELECT 1 / 0"))

    await db.seed()
    original = await db.apply()
    async with db.sessions.begin() as session:
        tx = ClockedTransaction(session, 0)
        await tx.lock_season("s")
        await tx.register_attempt("s", "A", "p2", "session:p2", "claim:pending")
    with pytest.raises(DBAPIError):
        await db.close(adapter=Failing)
    assert await db.query("SELECT * FROM territory_policy_result") == []
    final, repeated = await asyncio.gather(db.close(), db.close())
    assert final == repeated
    assert final.results[0].score.current_count == 1
    assert final.results[0].total_units == 340 * POINT_DENOMINATOR
    assert all(
        r["pet_id"] is None for r in await db.query("SELECT pet_id FROM territory_policy_site")
    )
    assert await db.apply(at=DAY_MS + 1) == original
    with pytest.raises(GameError, match="season_ended"):
        await db.apply(
            command("photo:late", "p2", 1, photo=True, attempt="claim:pending"), at=DAY_MS
        )
    await db.seed(starts=DAY_MS, ends=2 * DAY_MS, sid="next")
    with pytest.raises(GameError, match="attempt_identity_conflict"):
        await db.apply(
            replace(
                command("photo:late", "p2", photo=True, attempt="claim:pending"), season_id="next"
            ),
            at=DAY_MS,
        )
    for statement in [
        "UPDATE territory_policy_result SET rank=2 WHERE season_id='s'",
        "DELETE FROM territory_policy_receipt WHERE season_id='s'",
        "UPDATE territory_policy_season SET rules='{}'::jsonb WHERE season_id='s'",
    ]:
        with pytest.raises(DBAPIError):
            await db.query(statement)
    assert await db.close() == final


async def test_database_constraints_cas_and_inconsistent_counts_fail_closed(db):
    await db.seed()
    await db.apply()
    with pytest.raises(IntegrityError):
        await db.query("UPDATE territory_policy_account SET scoring_count=2 WHERE pet_id='p1'")
    async with db.sessions.begin() as session:
        tx = ClockedTransaction(session, 0)
        await tx.lock_season("s")
        site = await tx.lock_site("s", "A")
        with pytest.raises(GameError, match="site_changed"):
            await tx.save_site(replace(site, version=0), replace(site, version=1))
    await db.query(
        "UPDATE territory_policy_account SET current_count=0, scoring_count=0 WHERE pet_id='p1'"
    )
    with pytest.raises(GameError, match="score_state_inconsistent"):
        await db.apply(command("photo:2", "p2", 1, photo=True), at=HOUR_MS)
    with pytest.raises(GameError, match="score_state_inconsistent"):
        await db.close()


async def test_clock_is_sampled_after_waiting_for_real_season_lock(db):
    await db.seed()
    entered = asyncio.Event()
    async with db.sessions.begin() as first:
        tx = PostgresPolicyTransaction(first)
        await tx.lock_season("s")

        async def waiting():
            async with db.sessions.begin() as second:
                other = PostgresPolicyTransaction(second)
                pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                entered.pid = pid
                entered.set()
                await other.lock_season("s")
                return await other.now_ms()

        task = asyncio.create_task(waiting())
        await entered.wait()

        async def wait_for_db_lock():
            while True:
                row = (
                    await db.query(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid",
                        pid=entered.pid,
                    )
                )[0]
                if row["wait_event_type"] == "Lock":
                    return
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_db_lock(), 4)
        release_ms = await tx.now_ms()
        assert not task.done()
    assert await asyncio.wait_for(task, 4) >= release_ms


async def test_projection_does_not_write_and_adapter_cannot_outlive_transaction(db):
    await db.seed()
    await db.apply()
    async with db.sessions.begin() as session:
        tx = ClockedTransaction(session, HOUR_MS)
        scores = await tx.projected_scores("s")
        assert scores["p1"].holding_units == 10 * POINT_DENOMINATOR
    assert (await db.query("SELECT holding_units FROM territory_policy_account"))[0][
        "holding_units"
    ] == 0
    with pytest.raises(GameError, match="policy_transaction_changed"):
        await tx.lock_season("s")


async def test_active_scope_and_site_overlap_are_rejected_atomically(db):
    await db.seed()
    with pytest.raises(GameError, match="site_in_active_season"):
        async with db.sessions.begin() as session:
            await create_season(
                session, SeasonContext("other", 0, DAY_MS, Rules()), "different", ["A"]
            )
    assert len(await db.query("SELECT * FROM territory_policy_season")) == 1


async def test_missing_migration_raises_instead_of_using_public_schema_or_fake(db):
    async with db.engine.begin() as conn:
        await conn.run_sync(migrate, "downgrade")
    with pytest.raises(DBAPIError):
        await db.apply()


async def test_finalize_racing_boundary_claim_never_grants_points(db):
    await db.seed()
    await db.apply()
    results = await asyncio.wait_for(
        asyncio.gather(
            db.close(),
            db.apply(command("mark:boundary", site="B"), at=DAY_MS),
            return_exceptions=True,
        ),
        8,
    )
    assert isinstance(results[1], GameError) and str(results[1]) == "season_ended"
    assert len(await db.query("SELECT * FROM territory_policy_receipt")) == 1
    assert (await db.query("SELECT status FROM territory_policy_season"))[0][
        "status"
    ] == "FINALIZED"


async def test_tied_results_replay_in_kernel_order_independent_of_database_collation(db):
    await db.seed(
        initial_owners={
            "A": Ownership("Z", "walk:Z", "claim:Z", "VERIFIED", 0),
            "B": Ownership("a", "walk:a", "claim:a", "VERIFIED", 0),
        }
    )
    final = await db.close()
    assert [r.pet_id for r in final.results] == ["Z", "a"]
    assert [r.rank for r in final.results] == [1, 1]
    assert await db.close() == final


async def test_imported_owner_account_survives_loss_without_original_capture_receipt(db):
    await db.seed(
        initial_owners={
            "A": Ownership("p1", "walk:old", "claim:old", "VERIFIED", 0),
        }
    )
    await db.apply(command("photo:2", "p2", 1, photo=True), at=HOUR_MS)
    with pytest.raises(DBAPIError):
        await db.query("DELETE FROM territory_policy_account WHERE pet_id='p1'")
    score = (await db.query("SELECT * FROM territory_policy_account WHERE pet_id='p1'"))[0]
    assert (score["current_count"], score["holding_units"]) == (0, 10 * POINT_DENOMINATOR)
