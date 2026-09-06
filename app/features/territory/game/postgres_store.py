"""Geo PostgreSQL implementation of PolicyTransaction; the caller owns the transaction.

Use one instance per AsyncSession transaction. No engine/global settings, implicit
commit, migration, fallback or public authentication endpoint lives in this adapter.
DEV promotion maps the site/attempt operations to #260's authoritative tables.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, replace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.territory.game.policy import (
    CONTRACT_VERSION,
    Account,
    BonusKey,
    FinalizationPlan,
    FinalStanding,
    Ownership,
    OwnershipCandidate,
    OwnershipPlan,
    Receipt,
    Rules,
    Score,
    SeasonContext,
    SiteSnapshot,
    require,
    settle,
)

SCORE_FIELDS = tuple(f.name for f in fields(Score))


def _score(row) -> Score:
    return Score(**{key: int(row[key]) for key in SCORE_FIELDS})


def _season(row) -> SeasonContext:
    require(row["contract_version"] == CONTRACT_VERSION, "unsupported_policy_contract")
    return SeasonContext(
        row["season_id"], row["starts_ms"], row["ends_ms"], Rules(**row["rules"]), row["status"]
    )


def _site(row) -> SiteSnapshot:
    owner = None
    if row["pet_id"] is not None:
        owner = Ownership(**{f.name: row[f.name] for f in fields(Ownership)})
    return SiteSnapshot(row["season_id"], row["site_id"], row["version"], owner)


class PostgresPolicyTransaction:
    def __init__(self, session: AsyncSession):
        require(session.in_transaction(), "policy_transaction_required")
        self.session = session
        self._transaction = session.get_transaction()
        self._season: SeasonContext | None = None

    def _active(self):
        require(
            self.session.in_transaction() and self.session.get_transaction() is self._transaction,
            "policy_transaction_changed",
        )

    def _locked(self, season_id: str):
        self._active()
        require(
            self._season is not None and self._season.season_id == season_id, "season_not_locked"
        )

    async def _rows(self, sql, params=None):
        self._active()
        return (await self.session.execute(text(sql), params or {})).mappings()

    async def lock_season(self, season_id: str) -> SeasonContext:
        require(
            self._season is None or self._season.season_id == season_id,
            "one_season_per_transaction",
        )
        row = (
            await self._rows(
                "SELECT * FROM territory_policy_season WHERE season_id=:sid FOR UPDATE",
                {"sid": season_id},
            )
        ).one_or_none()
        require(row is not None, "unknown_season")
        self._season = _season(row)
        return self._season

    async def lock_site(self, season_id: str, site_id: str) -> SiteSnapshot:
        self._locked(season_id)
        row = (
            await self._rows(
                "SELECT * FROM territory_policy_site WHERE season_id=:sid AND site_id=:site FOR UPDATE",
                {"sid": season_id, "site": site_id},
            )
        ).one_or_none()
        require(row is not None, "unknown_site")
        return _site(row)

    async def _counts(self, season_id: str) -> dict[str, tuple[int, int]]:
        rows = await self._rows(
            """
            SELECT pet_id, count(*) AS owned,
                count(*) FILTER (WHERE certification='VERIFIED' OR :unverified) AS scoring
            FROM territory_policy_site WHERE season_id=:sid AND pet_id IS NOT NULL GROUP BY pet_id
        """,
            {"sid": season_id, "unverified": self._season.rules.unverified_scores},
        )
        return {r["pet_id"]: (r["owned"], r["scoring"]) for r in rows}

    async def lock_scores(self, season_id: str, pet_ids: tuple[str, ...]) -> dict[str, Score]:
        self._locked(season_id)
        require(pet_ids == tuple(sorted(set(pet_ids))), "unsorted_score_locks")
        rows = await self._rows(
            """
            SELECT * FROM territory_policy_account
            WHERE season_id=:sid AND pet_id=ANY(CAST(:pets AS text[]))
            ORDER BY pet_id COLLATE "C" FOR UPDATE
        """,
            {"sid": season_id, "pets": list(pet_ids)},
        )
        accounts = {r["pet_id"]: _score(r) for r in rows}
        counts = await self._counts(season_id)
        now = await self.now_ms()
        for pet in pet_ids:
            actual = counts.get(pet, (0, 0))
            if pet not in accounts:
                require(actual == (0, 0), "score_state_missing")
                # No writes before business validation. The successful plan inserts it.
                accounts[pet] = Score(last_ms=now)
            score = accounts[pet]
            require(
                (score.current_count, score.scoring_count) == actual, "score_state_inconsistent"
            )
        return accounts

    async def now_ms(self) -> int:
        row = (
            await self._rows(
                "SELECT floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint AS ms"
            )
        ).one()
        return row["ms"]

    async def get_receipt(self, season_id: str, event_id: str) -> Receipt | None:
        self._locked(season_id)
        row = (
            await self._rows(
                "SELECT payload FROM territory_policy_receipt WHERE season_id=:sid AND event_id=:event",
                {"sid": season_id, "event": event_id},
            )
        ).one_or_none()
        if row is None:
            return None
        data = dict(row["payload"])
        require(data["contract_version"] == CONTRACT_VERSION, "unsupported_policy_contract")
        data["candidate"] = OwnershipCandidate(**data["candidate"])
        return Receipt(**data)

    async def bonus_paid(self, key: BonusKey) -> bool:
        self._locked(key.season_id)
        return (
            await self._rows(
                """
            SELECT 1 FROM territory_policy_bonus WHERE season_id=:season_id
            AND pet_id=:pet_id AND site_id=:site_id AND utc_day=:utc_day
        """,
                asdict(key),
            )
        ).first() is not None

    async def save_site(self, before: SiteSnapshot, after: SiteSnapshot) -> None:
        self._locked(before.season_id)
        require(
            (before.season_id, before.site_id) == (after.season_id, after.site_id)
            and after.version == before.version + 1,
            "invalid_site_update",
        )
        owner = asdict(after.owner) if after.owner else {f.name: None for f in fields(Ownership)}
        result = await self.session.execute(
            text("""
            UPDATE territory_policy_site SET version=:version, pet_id=:pet_id,
                session_id=:session_id, attempt_id=:attempt_id, certification=:certification,
                occupied_ms=:occupied_ms
            WHERE season_id=:sid AND site_id=:site AND version=:expected
        """),
            {
                **owner,
                "sid": before.season_id,
                "site": before.site_id,
                "version": after.version,
                "expected": before.version,
            },
        )
        require(result.rowcount == 1, "site_changed")

    async def save_scores(self, season_id: str, accounts: tuple[Account, ...]) -> None:
        self._locked(season_id)
        columns = ", ".join(SCORE_FIELDS)
        params = ", ".join(f":{key}" for key in SCORE_FIELDS)
        assignments = ", ".join(f"{key}=EXCLUDED.{key}" for key in SCORE_FIELDS)
        for account in accounts:
            await self.session.execute(
                text(f"""
                INSERT INTO territory_policy_account (season_id, pet_id, {columns})
                VALUES (:sid, :pet, {params}) ON CONFLICT (season_id, pet_id)
                DO UPDATE SET {assignments}
            """),
                {"sid": season_id, "pet": account.pet_id, **asdict(account.score)},
            )

    async def reserve_bonus(self, key: BonusKey) -> None:
        self._locked(key.season_id)
        await self._rows(
            """
            INSERT INTO territory_policy_bonus (season_id, pet_id, site_id, utc_day)
            VALUES (:season_id, :pet_id, :site_id, :utc_day) RETURNING 1
        """,
            asdict(key),
        )

    async def append_event(self, plan: OwnershipPlan) -> None:
        self._locked(plan.candidate.season_id)
        await self._rows(
            """
            INSERT INTO territory_policy_event (season_id, event_id, payload)
            VALUES (:sid, :event, CAST(:payload AS jsonb)) RETURNING 1
        """,
            {
                "sid": plan.candidate.season_id,
                "event": plan.candidate.event_id,
                "payload": json.dumps(asdict(plan)),
            },
        )

    async def register_attempt(
        self,
        season_id: str,
        site_id: str,
        pet_id: str,
        session_id: str,
        attempt_id: str,
    ) -> None:
        """Host calls this on authenticated admission, including pending photo attempts.

        Global attempt identity prevents a late callback being reassigned to a new season.
        Receipt persistence also verifies it, so conflicting identities roll back all writes.
        """
        self._locked(season_id)
        require(self._season.status == "ACTIVE", "season_ended")
        values = {
            "season_id": season_id,
            "site_id": site_id,
            "pet_id": pet_id,
            "session_id": session_id,
            "attempt_id": attempt_id,
        }
        await self._rows(
            """
            INSERT INTO territory_policy_attempt (season_id, site_id, pet_id, session_id, attempt_id)
            VALUES (:season_id, :site_id, :pet_id, :session_id, :attempt_id)
            ON CONFLICT (attempt_id) DO NOTHING RETURNING 1
        """,
            values,
        )
        row = (
            await self._rows(
                "SELECT * FROM territory_policy_attempt WHERE attempt_id=:attempt_id", values
            )
        ).one()
        require(dict(row) == values, "attempt_identity_conflict")

    async def save_receipt(self, receipt: Receipt) -> None:
        c = receipt.candidate
        self._locked(c.season_id)
        await self.register_attempt(c.season_id, c.site_id, c.pet_id, c.session_id, c.attempt_id)
        await self._rows(
            """
            INSERT INTO territory_policy_receipt
                (season_id, event_id, site_id, pet_id, attempt_id, payload)
            VALUES (:sid, :event, :site, :pet, :attempt, CAST(:payload AS jsonb)) RETURNING 1
        """,
            {
                "sid": c.season_id,
                "event": c.event_id,
                "site": c.site_id,
                "pet": c.pet_id,
                "attempt": c.attempt_id,
                "payload": json.dumps(asdict(receipt)),
            },
        )

    async def all_scores(self, season_id: str) -> dict[str, Score]:
        self._locked(season_id)
        rows = await self._rows(
            """
            SELECT * FROM territory_policy_account WHERE season_id=:sid
            ORDER BY pet_id COLLATE "C" FOR UPDATE
        """,
            {"sid": season_id},
        )
        scores = {r["pet_id"]: _score(r) for r in rows}
        counts = await self._counts(season_id)
        require(set(counts) <= set(scores), "score_state_missing")
        for pet, score in scores.items():
            require(
                (score.current_count, score.scoring_count) == counts.get(pet, (0, 0)),
                "score_state_inconsistent",
            )
        return scores

    async def get_finalization(self, season_id: str) -> FinalizationPlan | None:
        self._locked(season_id)
        if self._season.status != "FINALIZED":
            return None
        rows = await self._rows(
            """
            SELECT * FROM territory_policy_result WHERE season_id=:sid
            ORDER BY rank, pet_id COLLATE "C"
        """,
            {"sid": season_id},
        )
        results = tuple(
            FinalStanding(r["pet_id"], _score(r["score"]), int(r["total_units"]), r["rank"])
            for r in rows
        )
        accounts = tuple(
            Account(r.pet_id, replace(r.score, current_count=0, scoring_count=0))
            for r in sorted(results, key=lambda r: r.pet_id)
        )
        return FinalizationPlan(self._season, results, accounts)

    async def finalize(self, plan: FinalizationPlan) -> None:
        sid = plan.season.season_id
        self._locked(sid)
        require(self._season.status == "ACTIVE", "season_ended")
        for result in plan.results:
            await self._rows(
                """
                INSERT INTO territory_policy_result (season_id, pet_id, rank, total_units, score)
                VALUES (:sid, :pet, :rank, :total, CAST(:score AS jsonb)) RETURNING 1
            """,
                {
                    "sid": sid,
                    "pet": result.pet_id,
                    "rank": result.rank,
                    "total": result.total_units,
                    "score": json.dumps(asdict(result.score)),
                },
            )
        await self.save_scores(sid, plan.accounts)
        await self._rows(
            """
            UPDATE territory_policy_site SET version=version+1, pet_id=NULL, session_id=NULL,
                attempt_id=NULL, certification=NULL, occupied_ms=NULL
            WHERE season_id=:sid AND pet_id IS NOT NULL RETURNING 1
        """,
            {"sid": sid},
        )
        await self._rows(
            """
            UPDATE territory_policy_season SET status='FINALIZED'
            WHERE season_id=:sid AND status='ACTIVE' RETURNING 1
        """,
            {"sid": sid},
        )
        self._season = plan.season

    async def projected_scores(self, season_id: str) -> dict[str, Score]:
        """Consistent read under the season barrier; never persists elapsed time."""
        season = await self.lock_season(season_id)
        final = await self.get_finalization(season_id)
        if final is not None:
            return {r.pet_id: r.score for r in final.results}
        scores = await self.all_scores(season_id)
        at_ms = max(season.starts_ms, min(await self.now_ms(), season.ends_ms))
        return {pet: settle(score, at_ms, season.rules) for pet, score in scores.items()}


async def create_season(
    session: AsyncSession,
    season: SeasonContext,
    scope_id: str,
    site_ids: Sequence[str],
    *,
    initial_owners: Mapping[str, Ownership] | None = None,
) -> None:
    """Explicit initialization/backfill, atomic in the caller's transaction.

    Existing Geo territory_site rows are required. Imported ownership begins scoring
    at season.starts_ms with no retroactive bonus; original acquisition is retained.
    Active scopes cannot share a site. No existing game state is silently replaced.
    """
    tx = PostgresPolicyTransaction(session)
    require(season.status == "ACTIVE" and season.starts_ms < season.ends_ms, "invalid_season")
    require(bool(scope_id.strip()), "empty_scope")
    require(bool(site_ids) and len(set(site_ids)) == len(site_ids), "invalid_season_sites")
    owners = dict(initial_owners or {})
    require(set(owners) <= set(site_ids), "unknown_import_site")
    # Serialize admission of scopes and overlapping site sets across all season creators.
    await tx._rows("SELECT pg_advisory_xact_lock(260, 33)")
    overlap = (
        await tx._rows(
            """
        SELECT 1 FROM territory_policy_site p JOIN territory_policy_season s USING(season_id)
        WHERE s.status='ACTIVE' AND p.site_id=ANY(CAST(:sites AS text[])) LIMIT 1
    """,
            {"sites": list(site_ids)},
        )
    ).first()
    require(overlap is None, "site_in_active_season")
    previous = (
        await tx._rows(
            """
        SELECT max(ends_ms) AS ends FROM territory_policy_season WHERE scope_id=:scope
    """,
            {"scope": scope_id},
        )
    ).one()["ends"]
    require(previous is None or season.starts_ms >= previous, "season_overlap")
    await tx._rows(
        """
        INSERT INTO territory_policy_season
            (season_id, scope_id, starts_ms, ends_ms, status, contract_version, rules)
        VALUES (:season_id, :scope, :starts_ms, :ends_ms, :status, :contract, CAST(:rules AS jsonb))
        RETURNING 1
    """,
        {
            **asdict(season),
            "scope": scope_id,
            "contract": CONTRACT_VERSION,
            "rules": json.dumps(asdict(season.rules)),
        },
    )
    await tx.lock_season(season.season_id)
    counts, scoring = Counter(), Counter()
    for site_id in sorted(site_ids):
        owner = owners.get(site_id)
        if owner:
            require(owner.occupied_ms <= season.starts_ms, "invalid_import_time")
            counts[owner.pet_id] += 1
            scoring[owner.pet_id] += int(
                season.rules.unverified_scores or owner.certification == "VERIFIED"
            )
        values = asdict(owner) if owner else {f.name: None for f in fields(Ownership)}
        await tx._rows(
            """
            INSERT INTO territory_policy_site
                (season_id, site_id, version, pet_id, session_id, attempt_id,
                 certification, occupied_ms, imported_occupied_ms)
            VALUES (:sid, :site, :version, :pet_id, :session_id, :attempt_id,
                    :certification, :occupied_ms, :original) RETURNING 1
        """,
            {
                **values,
                "sid": season.season_id,
                "site": site_id,
                "version": int(owner is not None),
                "occupied_ms": season.starts_ms if owner else None,
                "original": owner.occupied_ms if owner else None,
            },
        )
        if owner:
            await tx.register_attempt(
                season.season_id, site_id, owner.pet_id, owner.session_id, owner.attempt_id
            )
    await tx.save_scores(
        season.season_id,
        tuple(
            Account(
                pet,
                Score(
                    current_count=count,
                    scoring_count=scoring[pet],
                    peak=count,
                    last_ms=season.starts_ms,
                ),
            )
            for pet, count in sorted(counts.items())
        ),
    )
