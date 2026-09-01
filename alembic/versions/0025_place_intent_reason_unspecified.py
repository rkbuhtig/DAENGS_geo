"""provider가 세부 abstention reason을 지정하지 않은 상태를 보존한다.

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "place_intent_lab_attempt_reason_known",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_reason_known_v2",
        "place_intent_lab_attempt",
        "proposer_reason IS NULL OR proposer_reason IN "
        "('unspecified', 'insufficient_target', 'multiple_plausible_readings', "
        "'unsupported_language', 'unsafe_to_guess')",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE place_intent_lab_attempt
        SET proposer_disposition = NULL, proposer_reason = NULL
        WHERE proposer_reason = 'unspecified'
        """
    )
    op.drop_constraint(
        "place_intent_lab_attempt_reason_known_v2",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_reason_known",
        "place_intent_lab_attempt",
        "proposer_reason IS NULL OR proposer_reason IN "
        "('insufficient_target', 'multiple_plausible_readings', "
        "'unsupported_language', 'unsafe_to_guess')",
    )
