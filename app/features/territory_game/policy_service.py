"""Ready-to-wire transactional use cases. Caller owns begin/commit/rollback.

Never catch database errors and continue the ownership write. Business rejections
(protected/site_changed/season_ended) happen before writes and may be recorded by
the photo service without undoing verified-visit evidence in its outer transaction.
"""

from app.features.territory_game.policy import (
    FinalizationPlan,
    OwnershipCandidate,
    Receipt,
    bonus_key,
    plan_finalization,
    plan_ownership,
    require,
    validate_context,
)
from app.features.territory_game.policy_ports import PolicyTransaction


async def apply_ownership_in_transaction(
    tx: PolicyTransaction,
    candidate: OwnershipCandidate,
) -> Receipt:
    season = await tx.lock_season(candidate.season_id)
    receipt = await tx.get_receipt(candidate.season_id, candidate.event_id)
    if receipt is not None:
        require(receipt.candidate == candidate, "event_identity_conflict")
        return receipt
    site = await tx.lock_site(candidate.season_id, candidate.site_id)
    pets = tuple(sorted({candidate.pet_id} | ({site.owner.pet_id} if site.owner else set())))
    scores = await tx.lock_scores(candidate.season_id, pets)
    at_ms = await tx.now_ms()
    validate_context(season, site, candidate, at_ms)
    key = bonus_key(candidate, at_ms, season.rules)
    paid = await tx.bonus_paid(key) if key is not None else False
    plan = plan_ownership(season, site, candidate, scores, at_ms=at_ms, bonus_already_paid=paid)
    receipt = Receipt(candidate, at_ms, plan.after.version, plan.bonus, plan.kind)
    if plan.kind != "UNCHANGED":
        await tx.save_site(plan.before, plan.after)
        await tx.save_scores(candidate.season_id, plan.accounts)
        if plan.bonus_key is not None:
            await tx.reserve_bonus(plan.bonus_key)
        await tx.append_event(plan)
    await tx.save_receipt(receipt)
    return receipt


async def finalize_in_transaction(tx: PolicyTransaction, season_id: str) -> FinalizationPlan:
    season = await tx.lock_season(season_id)
    existing = await tx.get_finalization(season_id)
    if existing is not None:
        return existing
    scores = await tx.all_scores(season_id)
    plan = plan_finalization(season, scores, at_ms=await tx.now_ms())
    await tx.finalize(plan)
    return plan
