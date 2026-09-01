"""place intent 관측에 proposer 원인과 제품 응답 형태를 분리한다.

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("place_intent_lab_attempt", sa.Column("proposer_disposition", sa.Text()))
    op.add_column("place_intent_lab_attempt", sa.Column("proposer_reason", sa.Text()))
    op.add_column(
        "place_intent_lab_attempt",
        sa.Column("response_mode", sa.Text(), nullable=False, server_default="clarification"),
    )
    op.add_column("place_intent_lab_attempt", sa.Column("fallback_policy_id", sa.Text()))
    op.add_column("place_intent_lab_attempt", sa.Column("fallback_policy_version", sa.Text()))
    op.execute(
        """
        UPDATE place_intent_lab_attempt
        SET response_mode = CASE
            WHEN status = 'completed' THEN 'direct_results'
            WHEN status = 'failed' THEN 'provider_failure'
            ELSE 'clarification'
        END
        """
    )
    op.alter_column("place_intent_lab_attempt", "response_mode", server_default=None)
    op.create_check_constraint(
        "place_intent_lab_attempt_disposition_known",
        "place_intent_lab_attempt",
        "proposer_disposition IS NULL OR "
        "proposer_disposition IN ('proposed', 'ambiguous', 'abstained')",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_reason_known",
        "place_intent_lab_attempt",
        "proposer_reason IS NULL OR proposer_reason IN "
        "('insufficient_target', 'multiple_plausible_readings', "
        "'unsupported_language', 'unsafe_to_guess')",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_proposer_shape",
        "place_intent_lab_attempt",
        "(proposer_disposition IS NULL AND proposer_reason IS NULL) OR "
        "(proposer_disposition = 'proposed' AND proposer_reason IS NULL) OR "
        "(proposer_disposition = 'ambiguous' AND "
        "proposer_reason = 'multiple_plausible_readings') OR "
        "(proposer_disposition = 'abstained' AND proposer_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_response_mode_known",
        "place_intent_lab_attempt",
        "response_mode IN ('direct_results', 'exploratory_results', 'clarification', "
        "'unsupported', 'provider_failure')",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_fallback_policy_paired",
        "place_intent_lab_attempt",
        "(fallback_policy_id IS NULL) = (fallback_policy_version IS NULL)",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_response_matches_status",
        "place_intent_lab_attempt",
        "(status = 'completed' AND response_mode IN "
        "('direct_results', 'exploratory_results')) OR "
        "(status = 'needs_clarification' AND response_mode IN "
        "('clarification', 'unsupported')) OR "
        "(status = 'failed' AND response_mode = 'provider_failure')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "place_intent_lab_attempt_fallback_policy_paired",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_constraint(
        "place_intent_lab_attempt_response_mode_known",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_constraint(
        "place_intent_lab_attempt_reason_known",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_constraint(
        "place_intent_lab_attempt_disposition_known",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_column("place_intent_lab_attempt", "fallback_policy_version")
    op.drop_column("place_intent_lab_attempt", "fallback_policy_id")
    op.drop_column("place_intent_lab_attempt", "response_mode")
    op.drop_column("place_intent_lab_attempt", "proposer_reason")
    op.drop_column("place_intent_lab_attempt", "proposer_disposition")
