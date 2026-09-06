"""Executable fake of the transaction port. Never imported by application code.

The coarse lock and copy-on-commit demonstrate atomicity/ordering obligations, not
PostgreSQL's implementation. A production adapter must pass equivalent DB tests.
"""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace

from app.features.territory.game.policy import (
    DAY_MS,
    Rules,
    Score,
    SeasonContext,
    SiteSnapshot,
    require,
)


class MemoryDatabase:
    def __init__(self, rules=None):
        self.data = {
            "seasons": {"s": SeasonContext("s", 0, DAY_MS, rules or Rules())},
            "sites": {("s", site): SiteSnapshot("s", site, 0, None) for site in ["A", "B"]},
            "scores": {("s", pet): Score() for pet in ["p1", "p2", "p3"]},
            "receipts": {},
            "bonuses": set(),
            "events": [],
            "finals": {},
        }
        self.mutex = asyncio.Lock()
        self.now = 0
        self.commits = 0

    @asynccontextmanager
    async def transaction(self, fail_at=None):
        async with self.mutex:
            tx = MemoryTransaction(self, deepcopy(self.data), fail_at)
            yield tx
            self.data = tx.data
            self.commits += 1


class MemoryTransaction:
    def __init__(self, database, data, fail_at):
        self.database, self.data, self.fail_at = database, data, fail_at
        self.trace = []

    async def lock_season(self, season_id):
        self.trace.append("season")
        return self.data["seasons"][season_id]

    async def lock_site(self, season_id, site_id):
        assert "season" in self.trace
        self.trace.append("site")
        return self.data["sites"][(season_id, site_id)]

    async def lock_scores(self, season_id, pet_ids):
        assert "site" in self.trace
        assert tuple(sorted(set(pet_ids))) == pet_ids
        self.trace.append(("scores", pet_ids))
        return {
            p: self.data["scores"][(season_id, p)]
            for p in pet_ids
            if (season_id, p) in self.data["scores"]
        }

    async def now_ms(self):
        self.trace.append("clock")
        return self.database.now

    async def get_receipt(self, season_id, event_id):
        return self.data["receipts"].get((season_id, event_id))

    async def bonus_paid(self, key):
        return key in self.data["bonuses"]

    async def save_site(self, before, after):
        key = (before.season_id, before.site_id)
        require(self.data["sites"][key] == before, "site_changed")
        self.data["sites"][key] = after
        self.trace.append("save_site")
        await asyncio.sleep(0)

    async def save_scores(self, season_id, accounts):
        if self.fail_at == "scores":
            raise RuntimeError("injected_score_write_failure")
        for account in accounts:
            self.data["scores"][(season_id, account.pet_id)] = account.score
        self.trace.append("save_scores")

    async def reserve_bonus(self, key):
        require(key not in self.data["bonuses"], "bonus_conflict")
        self.data["bonuses"].add(key)

    async def append_event(self, plan):
        self.data["events"].append(plan)

    async def save_receipt(self, receipt):
        if self.fail_at == "receipt":
            raise RuntimeError("injected_receipt_write_failure")
        key = (receipt.candidate.season_id, receipt.candidate.event_id)
        require(key not in self.data["receipts"], "event_conflict")
        self.data["receipts"][key] = receipt

    async def all_scores(self, season_id):
        assert "season" in self.trace
        return {p: score for (sid, p), score in self.data["scores"].items() if sid == season_id}

    async def get_finalization(self, season_id):
        return self.data["finals"].get(season_id)

    async def finalize(self, plan):
        sid = plan.season.season_id
        self.data["finals"][sid] = plan
        self.data["seasons"][sid] = plan.season
        for key, site in self.data["sites"].items():
            if key[0] == sid:
                self.data["sites"][key] = replace(
                    site, owner=None, version=site.version + int(site.owner is not None)
                )
        await self.save_scores(sid, plan.accounts)
        if self.fail_at == "finalize":
            raise RuntimeError("injected_finalization_failure")
