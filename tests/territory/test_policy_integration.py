"""Contracts a DEV adapter can exercise before its migration is applied."""

import asyncio
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace

import pytest

from app.features.territory.game.policy import (
    DAY_MS,
    HOUR_MS,
    GameError,
    OwnershipCandidate,
    Rules,
    Score,
    plan_finalization,
    plan_ownership,
)
from app.features.territory.game.policy_service import (
    apply_ownership_in_transaction,
    finalize_in_transaction,
)
from tests.territory.policy_memory_adapter import MemoryDatabase


def test_policy_can_load_without_web_database_or_local_game_dependencies():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
class BlockInfrastructure:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'sqlalchemy', 'sqlite3'} or fullname in {
            'app.core.config', 'app.features.territory.game.season',
            'app.features.territory.game.local_store',
        }:
            raise RuntimeError('policy requires infrastructure: ' + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from app.features.territory.game.policy import Rules
from app.features.territory.game.policy_service import apply_ownership_in_transaction
assert Rules().protection_ms == 600000
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def candidate(event="mark:a1", pet="p1", version=0, site="A", photo=False):
    return OwnershipCandidate(
        "s",
        event,
        site,
        version,
        pet,
        f"session_{pet}",
        f"claim_{event}",
        "VERIFIED" if photo else "UNVERIFIED",
        "PHOTO_VERIFIED" if photo else "MARK",
    )


async def apply(db, command, fail_at=None):
    async with db.transaction(fail_at) as tx:
        receipt = await apply_ownership_in_transaction(tx, command)
    return receipt


async def test_contract_applies_after_locks_and_leaves_commit_to_caller():
    db = MemoryDatabase()
    async with db.transaction() as tx:
        receipt = await apply_ownership_in_transaction(tx, candidate())
        assert tx.trace[:4] == ["season", "site", ("scores", ("p1",)), "clock"]
        assert receipt.bonus == 100
        assert db.data["sites"][("s", "A")].owner is None
        assert db.commits == 0
    assert db.commits == 1
    assert db.data["sites"][("s", "A")].owner.pet_id == "p1"
    assert db.data["scores"][("s", "p1")].bonus == 100


@pytest.mark.parametrize("failure", ["scores", "receipt"])
async def test_partial_adapter_failure_rolls_back_all_writes(failure):
    db = MemoryDatabase(Rules(repeat_bonus="daily_pet_site"))
    before = deepcopy(db.data)
    with pytest.raises(RuntimeError, match="injected"):
        await apply(db, candidate(), failure)
    assert db.data == before
    assert db.commits == 0
    assert (await apply(db, candidate())).bonus == 100


async def test_stable_source_receipt_replays_after_clock_and_ownership_change():
    db = MemoryDatabase()
    first = await apply(db, candidate())
    db.now = HOUR_MS
    await apply(db, candidate("photo:c2", "p2", 1, photo=True))
    before = deepcopy(db.data)
    assert await apply(db, candidate()) == first
    assert db.data == before  # receipt is historical, current owner remains p2
    assert db.data["sites"][("s", "A")].owner.pet_id == "p2"
    with pytest.raises(GameError, match="event_identity_conflict"):
        await apply(db, replace(candidate(), pet_id="p3"))


async def test_duplicate_callbacks_and_two_sites_for_same_dog_are_serialized():
    db = MemoryDatabase()
    receipts = await asyncio.gather(*(apply(db, candidate()) for _ in range(4)))
    assert all(r == receipts[0] for r in receipts)
    assert len(db.data["events"]) == 1
    db.now = HOUR_MS
    await apply(db, candidate("mark:b1", site="B"))
    score = db.data["scores"][("s", "p1")]
    assert score.current_count == 2
    assert score.holding_units == 10 * HOUR_MS * 10_000


async def test_protection_and_missing_counts_fail_before_writes():
    db = MemoryDatabase()
    await apply(db, candidate())
    before = deepcopy(db.data)
    db.now = 599_999
    with pytest.raises(GameError, match="protected"):
        await apply(db, candidate("photo:c2", "p2", 1, photo=True))
    assert before == db.data
    db.now = 600_000
    del db.data["scores"][("s", "p2")]
    with pytest.raises(GameError, match="score_state_missing"):
        await apply(db, candidate("photo:c2", "p2", 1, photo=True))
    assert db.data["sites"][("s", "A")].owner.pet_id == "p1"


async def test_photo_service_can_preserve_verified_visit_on_business_rejection():
    db = MemoryDatabase()
    await apply(db, candidate())
    db.now = 100
    async with db.transaction() as tx:
        tx.data["verified_visits"] = {"photo:c2": "visit:2"}
        try:
            await apply_ownership_in_transaction(tx, candidate("photo:c2", "p2", 1, photo=True))
        except GameError as error:
            if str(error) != "protected":
                raise
            tx.data["photo_resolution"] = "protected"
    assert db.data["verified_visits"] == {"photo:c2": "visit:2"}
    assert db.data["photo_resolution"] == "protected"
    assert db.data["sites"][("s", "A")].owner.pet_id == "p1"
    assert db.data["scores"][("s", "p2")].bonus == 0
    assert len(db.data["events"]) == 1


async def test_photo_strengthening_uses_shared_kernel_and_preserves_protection():
    db = MemoryDatabase(Rules(unverified_scores=False))
    await apply(db, candidate())
    db.now = HOUR_MS
    await apply(db, candidate("photo:c1", version=1, photo=True))
    owner = db.data["sites"][("s", "A")].owner
    assert owner.occupied_ms == 0
    assert owner.attempt_id == candidate().attempt_id
    score = db.data["scores"][("s", "p1")]
    assert (score.bonus, score.claims, score.scoring_count, score.holding_units) == (100, 1, 1, 0)
    receipt = await apply(db, candidate("photo:c1-again", version=2, photo=True))
    assert receipt.kind == "UNCHANGED"
    assert receipt.bonus == 0
    assert len(db.data["events"]) == 2


async def test_takeover_settles_both_accounts_at_old_multipliers():
    db = MemoryDatabase()
    await apply(db, candidate())
    await apply(db, candidate("mark:b1", site="B"))
    db.now = HOUR_MS
    await apply(db, candidate("photo:c2", "p2", 1, photo=True))
    p1 = db.data["scores"][("s", "p1")]
    p2 = db.data["scores"][("s", "p2")]
    assert p1.holding_units == 22 * HOUR_MS * 10_000
    assert (p1.current_count, p2.current_count, p2.holding_units) == (1, 1, 0)


async def test_competing_photo_candidates_only_one_can_change_version():
    db = MemoryDatabase()
    await apply(db, candidate())
    db.now = 600_000
    results = await asyncio.gather(
        apply(db, candidate("photo:c2", "p2", 1, photo=True)),
        apply(db, candidate("photo:c3", "p3", 1, photo=True)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, GameError) for result in results) == 1
    assert [str(result) for result in results if isinstance(result, GameError)] == ["site_changed"]
    assert sum(score.bonus for score in db.data["scores"].values()) == 200


async def test_daily_bonus_key_is_reserved_in_same_transaction():
    db = MemoryDatabase(Rules(repeat_bonus="daily_pet_site"))
    await apply(db, candidate())
    db.now = 600_000
    await apply(db, candidate("photo:c2", "p2", 1, photo=True))
    db.now = 1_200_000
    receipt = await apply(db, candidate("photo:c3", "p1", 2, photo=True))
    assert receipt.bonus == 0
    assert db.data["scores"][("s", "p1")].current_count == 1
    assert len(db.data["bonuses"]) == 2


async def test_close_is_atomic_idempotent_and_orders_against_claims():
    db = MemoryDatabase()
    command = candidate()
    original = await apply(db, command)
    db.now = DAY_MS
    before = deepcopy(db.data)
    with pytest.raises(RuntimeError, match="injected_finalization"):
        async with db.transaction("finalize") as tx:
            await finalize_in_transaction(tx, "s")
    assert db.data == before
    async with db.transaction() as tx:
        final = await finalize_in_transaction(tx, "s")
    assert final.results[0].score.bonus == 100
    assert final.results[0].score.current_count == 1
    assert db.data["sites"][("s", "A")].owner is None
    async with db.transaction() as tx:
        assert await finalize_in_transaction(tx, "s") == final
    assert await apply(db, command) == original
    with pytest.raises(GameError, match="season_ended"):
        await apply(db, candidate("mark:new", site="B"))


def test_portable_policy_rejects_context_mismatch_and_partial_initialization():
    db = MemoryDatabase()
    season = db.data["seasons"]["s"]
    site = db.data["sites"][("s", "A")]
    with pytest.raises(GameError, match="season_mismatch"):
        plan_ownership(
            season, replace(site, season_id="old"), candidate(), {"p1": Score()}, at_ms=0
        )
    with pytest.raises(GameError, match="invalid_claim_decision"):
        replace(candidate(), cause="PHOTO_VERIFIED")
    with pytest.raises(GameError, match="invalid_score_time"):
        plan_ownership(season, site, candidate(), {"p1": Score(last_ms=1)}, at_ms=0)
    with pytest.raises(GameError, match="season_not_ended"):
        plan_finalization(season, {"p1": Score()}, at_ms=DAY_MS - 1)
