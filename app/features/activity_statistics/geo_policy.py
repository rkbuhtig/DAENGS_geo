"""Opt-in Geo policy composition; DEV must supply its own authenticated producers."""

from app.features.territory_game.policy import FinalizationPlan, OwnershipPlan
from app.features.territory_game.policy_service import finalize_in_transaction
from app.features.territory_game.postgres_store import PostgresPolicyTransaction

from .common import require
from .postgres_store import PostgresStatisticsTransaction
from .territory import InitialOwner, TerritoryCoverage, TerritoryStatEvent


class StatisticsPolicyTransaction(PostgresPolicyTransaction):
    """Use exclusively for ownership/finalization after statistics activation."""

    async def append_event(self, plan: OwnershipPlan):
        await super().append_event(plan)
        stats = PostgresStatisticsTransaction(self.session)
        stream = await stats.stream("TERRITORY", plan.candidate.season_id)
        candidate = plan.candidate
        await stats.append_territory(
            TerritoryStatEvent(
                candidate.season_id,
                "policy:" + candidate.event_id,
                stream["revision"] + 1,
                plan.at_ms,
                plan.kind,
                candidate.site_id,
                plan.after.owner.pet_id,
                plan.before.owner.pet_id if plan.before.owner else None,
                candidate.session_id,
                candidate.attempt_id,
                plan.after.owner.certification == "VERIFIED",
            )
        )

    async def finalize(self, plan: FinalizationPlan):
        await super().finalize(plan)
        stats = PostgresStatisticsTransaction(self.session)
        stream = await stats.stream("TERRITORY", plan.season.season_id)
        await stats.append_territory(
            TerritoryStatEvent(
                plan.season.season_id,
                "season-closed",
                stream["revision"] + 1,
                plan.season.ends_ms,
                "SEASON_CLOSED",
            )
        )

    async def activate_statistics(self, season_id, *, coverage_start_ms=None):
        """Explicit complete baseline under the policy barrier, with no invented history.

        Omit coverage_start_ms for a current-state activation. Supplying an earlier
        time is only valid alongside create_season in the same transaction (new season).
        """
        season = await self.lock_season(season_id)
        require(season.status == "ACTIVE", "statistics_requires_active_season")
        if coverage_start_ms is None:
            coverage_start_ms = max(season.starts_ms, await self.now_ms())
        else:
            # Explicit start-time seeding only before the season has any applied events.
            rows = await self._rows(
                "SELECT 1 FROM territory_policy_event WHERE season_id=:sid LIMIT 1",
                {"sid": season_id},
            )
            require(
                rows.first() is None and coverage_start_ms == season.starts_ms,
                "historical_baseline_not_allowed",
            )
        owners = await self._rows(
            """
            SELECT site_id,pet_id,certification FROM territory_policy_site
            WHERE season_id=:sid AND pet_id IS NOT NULL ORDER BY site_id COLLATE "C"
        """,
            {"sid": season_id},
        )
        coverage = TerritoryCoverage(season_id, season.starts_ms, season.ends_ms, coverage_start_ms)
        await PostgresStatisticsTransaction(self.session).initialize_territory(
            coverage,
            TerritoryStatEvent(
                season_id,
                "initialized",
                1,
                coverage_start_ms,
                "INITIALIZED",
                initial_owners=tuple(
                    InitialOwner(r["site_id"], r["pet_id"], r["certification"] == "VERIFIED")
                    for r in owners
                ),
            ),
        )

    async def capture_statistics_cut(self, season_id):
        season = await self.lock_season(season_id)
        now = max(season.starts_ms, await self.now_ms())
        if season.status == "ACTIVE" and now >= season.ends_ms:
            await finalize_in_transaction(self, season_id)
        return await PostgresStatisticsTransaction(self.session).confirm_territory(season_id, now)
