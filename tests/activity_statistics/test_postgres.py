"""Actual PostgreSQL transactions in the existing explicitly selected test DB.

No local application DB fallback. CI sets DAENGS_POLICY_TEST_URL and runs every case.
"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.features.activity_statistics.common import ProjectionIdentity, StatisticsError
from app.features.activity_statistics.geo_policy import StatisticsPolicyTransaction
from app.features.activity_statistics.postgres_store import (
    PostgresStatisticsTransaction,
    run_pending,
)
from app.features.activity_statistics.territory import summarize_territory
from app.features.activity_statistics.walk import WalkMetrics, WalkSelection, summarize_walks
from app.features.territory.game.policy import Ownership
from app.features.territory.game.policy_service import apply_ownership_in_transaction
from tests.activity_statistics.fixtures import GENERATION, MINUTE, VERSIONS, selection, session
from tests.territory import test_policy_postgres as policy_tests

policy_database = policy_tests.db
command = policy_tests.command

MIGRATION = Path(__file__).resolve().parents[2] / "alembic/versions/0034_activity_statistics.py"
GID = GENERATION.generation_id


def migrate(connection, direction):
    spec = importlib.util.spec_from_file_location("statistics_revision", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


class ClockedPolicy(StatisticsPolicyTransaction):
    def __init__(self, session, at):
        super().__init__(session)
        self.at = at

    async def now_ms(self):
        return self.at


@pytest.fixture
async def stats_db(policy_database):
    db = policy_database
    async with db.engine.begin() as connection:
        await connection.run_sync(migrate, "upgrade")
    async with db.sessions.begin() as connection:
        await PostgresStatisticsTransaction(connection).register_generation(GENERATION, VERSIONS)
    return db


async def seed(db, owners=None):
    await db.seed(ends=30 * MINUTE, initial_owners=owners)
    async with db.sessions.begin() as connection:
        await ClockedPolicy(connection, 0).activate_statistics("s", coverage_start_ms=0)


async def apply(db, candidate=None, at=2 * MINUTE, adapter=ClockedPolicy):
    return await db.apply(candidate or command(), at=at, adapter=adapter)


async def capture(db, at=20 * MINUTE):
    async with db.sessions.begin() as connection:
        return await ClockedPolicy(connection, at).capture_statistics_cut("s")


async def read(db, kind="TERRITORY", scope="s", gid=GID):
    async with db.sessions.begin() as connection:
        return await PostgresStatisticsTransaction(connection).read(gid, kind, scope)


async def test_migration_roundtrip_preserves_policy_and_geo_sources(stats_db):
    await stats_db.seed()
    async with stats_db.engine.begin() as connection:
        await connection.run_sync(migrate, "downgrade")
        assert (
            await connection.execute(text("SELECT count(*) FROM territory_policy_season"))
        ).scalar() == 1
        assert (await connection.execute(text("SELECT count(*) FROM territory_site"))).scalar() == 2
        await connection.run_sync(migrate, "upgrade")


async def test_late_upload_full_flow_and_fresh_process_read(stats_db):
    db = stats_db
    await seed(db)
    async with db.sessions.begin() as connection:
        await PostgresStatisticsTransaction(connection).record_session(session("GAME"))
    await apply(db)
    await apply(db, command("photo:1", version=1, photo=True, attempt="claim:mark:1"), 4 * MINUTE)
    await apply(db, command("photo:2", pet="p2", version=2, photo=True), 12 * MINUTE)
    async with db.sessions.begin() as connection:
        tx = PostgresStatisticsTransaction(connection)
        await tx.append_walk(selection())
        await tx.append_walk(selection())
        assert (await tx.links("owner-1"))[0].status == "LINKED"
    await capture(db)
    async with db.sessions.begin() as connection:
        assert (await PostgresStatisticsTransaction(connection).progress(GID, "TERRITORY", "s"))[
            "status"
        ] == "PENDING"
    assert await run_pending(db.sessions, GID) == 2
    assert await run_pending(db.sessions, GID) == 0
    async with db.sessions.begin() as connection:
        assert (await PostgresStatisticsTransaction(connection).progress(GID, "TERRITORY", "s"))[
            "status"
        ] == "READY"
    before = await read(db)
    p1 = summarize_territory(before, pet_id="p1")
    p2 = summarize_territory(before, pet_id="p2")
    assert (p1.held_site_ms, p1.verified_held_site_ms, p2.held_site_ms) == (
        10 * MINUTE,
        8 * MINUTE,
        8 * MINUTE,
    )
    walk = summarize_walks(
        await read(db, "WALK", "walk-1"), owner_id="owner-1", from_ms=0, to_ms=20 * MINUTE
    )
    assert walk.recorded_walk_count == 1 and walk.moving_distance_m == 400
    assert len(await db.query("SELECT * FROM activity_stat_applied")) == 5
    schema = (await db.query("SELECT current_schema() AS schema"))[0]["schema"]
    script = """
import asyncio,json,os
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool
from app.features.activity_statistics.postgres_store import PostgresStatisticsTransaction
from app.features.activity_statistics.territory import summarize_territory
async def main():
    engine=create_async_engine(os.environ['DAENGS_POLICY_TEST_URL'],poolclass=NullPool,
        connect_args={'server_settings':{'search_path':os.environ['STATISTICS_TEST_SCHEMA']}})
    async with async_sessionmaker(engine).begin() as session:
        result=await PostgresStatisticsTransaction(session).read('fixture-generation-1','TERRITORY','s')
        summary=summarize_territory(result,pet_id='p1')
        print(json.dumps([summary.held_site_ms,summary.verified_held_site_ms,len(result.periods)]))
    await engine.dispose()
asyncio.run(main())
"""
    env = {**os.environ, "STATISTICS_TEST_SCHEMA": schema}
    process = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == [10 * MINUTE, 8 * MINUTE, 2]


async def test_worker_failure_rolls_back_result_receipts_and_checkpoint(stats_db):
    db = stats_db
    await seed(db)
    await apply(db)
    await capture(db, 5 * MINUTE)
    await run_pending(db.sessions, GID)
    old = await read(db)
    await capture(db, 8 * MINUTE)

    class FailingWorker(PostgresStatisticsTransaction):
        async def _mark_applied(self, params, revision):
            await super()._mark_applied(params, revision)
            raise RuntimeError("simulated worker crash")

    with pytest.raises(RuntimeError, match="simulated worker crash"):
        async with db.sessions.begin() as connection:
            await FailingWorker(connection).refresh(GID, "TERRITORY", "s")
    assert await read(db) == old
    assert await run_pending(db.sessions, GID) == 1
    assert summarize_territory(await read(db), pet_id="p1").held_site_ms == 6 * MINUTE


async def test_failed_source_transaction_rolls_back_ownership_and_change(stats_db):
    db = stats_db
    await seed(db)

    class FailingPolicy(ClockedPolicy):
        async def append_event(self, plan):
            await super().append_event(plan)
            raise RuntimeError("simulated producer crash")

    with pytest.raises(RuntimeError, match="simulated producer crash"):
        await apply(db, adapter=FailingPolicy)
    assert (await db.query("SELECT pet_id FROM territory_policy_site WHERE site_id='A'"))[0][
        "pet_id"
    ] is None
    assert len(await db.query("SELECT * FROM activity_stat_change")) == 1
    assert await db.query("SELECT * FROM territory_policy_receipt") == []
    await apply(db)
    assert len(await db.query("SELECT * FROM activity_stat_change")) == 2


async def test_activated_season_rejects_writer_that_omits_statistics(stats_db):
    await seed(stats_db)
    with pytest.raises(DBAPIError, match="missing activity ownership change"):
        await stats_db.apply(at=2 * MINUTE)  # original non-statistics writer
    assert len(await stats_db.query("SELECT * FROM activity_stat_change")) == 1


async def test_two_connections_retry_same_claim_and_workers_without_double_credit(stats_db):
    db = stats_db
    await seed(db)
    first, second = await asyncio.gather(apply(db), apply(db))
    assert first == second
    await capture(db)
    counts = await asyncio.gather(run_pending(db.sessions, GID), run_pending(db.sessions, GID))
    assert sum(counts) == 1
    result = summarize_territory(await read(db), pet_id="p1")
    assert result.acquisition_count == 1 and result.held_site_ms == 18 * MINUTE
    assert len(await db.query("SELECT * FROM activity_stat_applied")) == 2


async def test_lagged_output_does_not_extend_previous_owner_to_new_cut(stats_db):
    db = stats_db
    await seed(db)
    await apply(db)
    await capture(db, 10 * MINUTE)
    await run_pending(db.sessions, GID)
    await apply(db, command("photo:2", pet="p2", version=1, photo=True), 12 * MINUTE)
    await capture(db)
    stale = summarize_territory(await read(db), pet_id="p1")
    async with db.sessions.begin() as connection:
        assert (await PostgresStatisticsTransaction(connection).progress(GID, "TERRITORY", "s"))[
            "status"
        ] == "STALE"
    assert stale.confirmed_through_ms == 10 * MINUTE and stale.held_site_ms == 8 * MINUTE
    await run_pending(db.sessions, GID)
    assert summarize_territory(await read(db), pet_id="p1").held_site_ms == 10 * MINUTE


async def test_baseline_and_season_close_persist_without_capture_bonus(stats_db):
    db = stats_db
    await seed(db, {"A": Ownership("p1", "import-session", "import-claim", "VERIFIED", 0)})
    await capture(db, 35 * MINUTE)  # finalizes inside the same policy transaction
    await run_pending(db.sessions, GID)
    result = summarize_territory(await read(db), pet_id="p1")
    assert result.acquisition_count == result.takeover_count == result.owned_site_count == 0
    assert result.held_site_ms == result.verified_held_site_ms == 30 * MINUTE
    assert (await db.query("SELECT bonus FROM territory_policy_account"))[0]["bonus"] == 0
    await capture(db, 40 * MINUTE)
    await run_pending(db.sessions, GID)
    assert summarize_territory(await read(db), pet_id="p1").held_site_ms == 30 * MINUTE


async def test_generation_rebuild_is_identical_without_rescoring_and_config_is_immutable(stats_db):
    db = stats_db
    await seed(db)
    await apply(db)
    await capture(db)
    await run_pending(db.sessions, GID)
    accounts = await db.query("SELECT * FROM territory_policy_account")
    generation2 = ProjectionIdentity("rebuild-2")
    async with db.sessions.begin() as connection:
        await PostgresStatisticsTransaction(connection).register_generation(generation2, VERSIONS)
    await run_pending(db.sessions, "rebuild-2")
    assert (await read(db, gid="rebuild-2")).periods == (await read(db)).periods
    assert await db.query("SELECT * FROM territory_policy_account") == accounts
    with pytest.raises(StatisticsError, match="generation_config_conflict"):
        async with db.sessions.begin() as connection:
            await PostgresStatisticsTransaction(connection).register_generation(
                GENERATION,
                replace(VERSIONS, calculation=5),
            )


async def test_walk_analysis_replacement_participant_correction_and_withdrawal(stats_db):
    db = stats_db
    first = selection()
    source = replace(
        first.source,
        analysis_id="new-analysis",
        metrics=WalkMetrics(500, 480, 1, 120),
        session=session(pets=("p2",)),
    )
    async with db.sessions.begin() as connection:
        tx = PostgresStatisticsTransaction(connection)
        await tx.append_walk(first)
        await tx.append_walk(selection(source, revision=2))
        await tx.append_walk(first)  # does not restore old session participant snapshot
    await run_pending(db.sessions, GID)
    result = await read(db, "WALK", "walk-1")
    assert result.contributions[0].source == source
    async with db.sessions.begin() as connection:
        tx = PostgresStatisticsTransaction(connection)
        assert (await tx.links("owner-1"))[0].walk.pet_ids == frozenset({"p2"})
        await tx.append_walk(WalkSelection("owner-1", "walk-1", 3, None))
        await tx.append_walk(first)
    await run_pending(db.sessions, GID)
    assert (await read(db, "WALK", "walk-1")).contributions == ()
    assert len(await db.query("SELECT * FROM activity_stat_applied")) == 3


async def test_concurrent_late_link_arrival_converges_and_owner_isolation(stats_db):
    async def record(source):
        async with stats_db.sessions.begin() as connection:
            await PostgresStatisticsTransaction(connection).record_session(source)

    await asyncio.gather(record(session()), record(session("GAME")), record(session()))
    await record(session(owner="owner-2", server_id="walk-2"))
    async with stats_db.sessions.begin() as connection:
        tx = PostgresStatisticsTransaction(connection)
        assert (await tx.links("owner-1"))[0].status == "LINKED"
        assert (await tx.links("owner-2"))[0].status == "WALK_ONLY"
    with pytest.raises(DBAPIError):
        await record(session(owner="owner-3"))  # server ID is globally unique per kind


async def test_uncommitted_new_stream_is_not_skipped_by_pending_runner(stats_db):
    db = stats_db
    ready, release = asyncio.Event(), asyncio.Event()

    async def delayed_producer():
        async with db.sessions.begin() as connection:
            await PostgresStatisticsTransaction(connection).append_walk(selection())
            ready.set()
            await release.wait()

    task = asyncio.create_task(delayed_producer())
    try:
        await asyncio.wait_for(ready.wait(), 5)
        assert await run_pending(db.sessions, GID) == 0
    finally:
        release.set()
        await task
    assert await run_pending(db.sessions, GID) == 1


async def test_source_mutation_and_revision_gap_are_rejected(stats_db):
    async with stats_db.sessions.begin() as connection:
        await PostgresStatisticsTransaction(connection).append_walk(selection())
    with pytest.raises(DBAPIError, match="immutable source"):
        await stats_db.query("UPDATE activity_stat_change SET event_id='different'")
    with pytest.raises(StatisticsError, match="selection_gap"):
        async with stats_db.sessions.begin() as connection:
            await PostgresStatisticsTransaction(connection).append_walk(selection(revision=3))
    assert len(await stats_db.query("SELECT * FROM activity_stat_change")) == 1


async def test_cut_waits_for_inflight_policy_transaction(stats_db):
    db = stats_db
    await seed(db)
    written, release, capturing = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def producer():
        async with db.sessions.begin() as connection:
            await apply_ownership_in_transaction(ClockedPolicy(connection, 2 * MINUTE), command())
            written.set()
            await release.wait()

    async def reader():
        await written.wait()
        capturing.set()
        return await capture(db, 3 * MINUTE)

    producing = asyncio.create_task(producer())
    reading = asyncio.create_task(reader())
    try:
        await asyncio.wait_for(capturing.wait(), 5)
        # Reader must not see an old revision paired with a time after the pending acquisition.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(reading), 0.05)
    finally:
        release.set()
        await producing
    cut = await asyncio.wait_for(reading, 5)
    assert cut.revision == 2 and cut.through_ms == 3 * MINUTE
    await run_pending(db.sessions, GID)
    assert summarize_territory(await read(db), pet_id="p1").held_site_ms == MINUTE
