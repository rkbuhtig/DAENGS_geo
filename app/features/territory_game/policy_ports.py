"""Storage ports to implement with DEV's existing async SQLAlchemy transaction.

All methods share the caller's transaction/connection; none may commit independently.
Missing schema is an unavailable adapter, never a reason to fall back to a fake or
skip scoring. The test adapter demonstrates the protocol, not PostgreSQL lock behavior.
"""

from typing import Protocol

from app.features.territory_game.policy import (
    Account,
    BonusKey,
    FinalizationPlan,
    OwnershipPlan,
    Receipt,
    Score,
    SeasonContext,
    SiteSnapshot,
)


class PolicyTransaction(Protocol):
    async def lock_season(self, season_id: str) -> SeasonContext:
        """Exclusive season barrier, acquired before claim session/site/score locks.

        A caller already holding a photo lock may acquire it here. Finalization never
        locks photos or claim sessions, preventing an inversion with photo callbacks.
        A caller pre-acquiring this same lock may safely invoke this method again.
        """
        ...

    async def lock_site(self, season_id: str, site_id: str) -> SiteSnapshot: ...

    async def lock_scores(self, season_id: str, pet_ids: tuple[str, ...]) -> dict[str, Score]:
        """Sorted pet IDs, authoritative counts, zero-init only for genuinely new accounts."""
        ...

    async def now_ms(self) -> int:
        """Trusted processing clock sampled AFTER locks; no client or capture timestamps."""
        ...

    async def get_receipt(self, season_id: str, event_id: str) -> Receipt | None: ...

    async def bonus_paid(self, key: BonusKey) -> bool: ...

    async def save_site(self, before: SiteSnapshot, after: SiteSnapshot) -> None:
        """Update #260 ownership and version with a compare-and-swap guard; 0 rows fails."""
        ...

    async def save_scores(self, season_id: str, accounts: tuple[Account, ...]) -> None: ...

    async def reserve_bonus(self, key: BonusKey) -> None:
        """UNIQUE(season, pet, site, day); conflict rolls back, then retry the transaction."""
        ...

    async def append_event(self, plan: OwnershipPlan) -> None: ...

    async def save_receipt(self, receipt: Receipt) -> None:
        """UNIQUE(season,event_id), includes immutable candidate and applied result."""
        ...

    async def all_scores(self, season_id: str) -> dict[str, Score]:
        """Complete season accounts under the exclusive season barrier; no paging gaps."""
        ...

    async def get_finalization(self, season_id: str) -> FinalizationPlan | None: ...

    async def finalize(self, plan: FinalizationPlan) -> None:
        """Atomically seal results/rules, reset current scores' counts, neutralize that
        season's sites and mark FINALIZED. No photo/session locks or history deletion.
        All claim admission checks reject the closed season even for pending photos.
        """
        ...
