from uuid import uuid4

from sqlalchemy import text

from app.discovery.place_intent.contract import ProposalDisposition, ProposalReason
from app.discovery.place_intent.observability import (
    AttemptStatus,
    SearchAttemptRecord,
    SearchEventType,
    SearchResponseMode,
    list_attempts,
    record_attempt,
    record_event,
)
from tests.conftest import db_session


async def test_failed_attempt_and_explicit_action_are_queryable() -> None:
    attempt_id = uuid4()
    async with db_session() as db:
        try:
            await record_attempt(
                db,
                SearchAttemptRecord(
                    attempt_id=attempt_id,
                    utterance="테스트 실패 검색",
                    model="gemini-test",
                    lat=37.5,
                    lng=126.9,
                    radius_m=3000,
                    status=AttemptStatus.NEEDS_CLARIFICATION,
                    failure_code="facet_selection_required",
                    proposer_disposition=ProposalDisposition.ABSTAINED,
                    proposer_reason=ProposalReason.UNSPECIFIED,
                    response_mode=SearchResponseMode.CLARIFICATION,
                    interpretation_count=1,
                    target_lens_count=2,
                    executable_lens_count=0,
                    initial_candidate_count=12,
                    eligible_candidate_count=0,
                    displayed_result_count=0,
                    initial_candidate_count_truncated=False,
                    result_count=0,
                    snapshot={"lenses": []},
                ),
            )
            await record_event(
                db,
                attempt_id=attempt_id,
                event_type=SearchEventType.SEARCH_FAILED,
                details={"failure_code": "facet_selection_required"},
            )

            observed = await list_attempts(db, limit=100, failures_only=True)

            row = next(item for item in observed if item.attempt_id == attempt_id)
            assert row.utterance == "테스트 실패 검색"
            assert row.failure_code == "facet_selection_required"
            assert row.proposer_disposition is ProposalDisposition.ABSTAINED
            assert row.proposer_reason is ProposalReason.UNSPECIFIED
            assert row.response_mode is SearchResponseMode.CLARIFICATION
            assert row.fallback_policy_id is None
            assert row.fallback_policy_version is None
            assert row.target_lens_count == 2
            assert row.initial_candidate_count == 12
            assert row.eligible_candidate_count == 0
            assert row.displayed_result_count == 0
            assert row.initial_candidate_count_truncated is False
        finally:
            await db.execute(
                text("DELETE FROM place_intent_lab_attempt WHERE id = :id"),
                {"id": attempt_id},
            )
            await db.commit()
