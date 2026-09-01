"""Require an assessed not-suspected drift result for negative spatial claims.

Existing receipts remain ``not_assessed`` and therefore cannot support
``not_observed``. A future drift screen may write ``not_suspected`` only with
an assessment method, preserving the existing provenance invariant.

Revision ID: 0029
Revises: 0028
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "walk_measurement_drift_known",
        "walk_measurement_receipt",
        type_="check",
    )
    op.create_check_constraint(
        "walk_measurement_drift_known_v2",
        "walk_measurement_receipt",
        sa.text(
            "drift_assessment IN "
            "('not_assessed', 'insufficient_evidence', 'not_suspected', 'suspected')"
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE walk_measurement_receipt "
            "SET drift_assessment = 'insufficient_evidence' "
            "WHERE drift_assessment = 'not_suspected'"
        )
    )
    op.drop_constraint(
        "walk_measurement_drift_known_v2",
        "walk_measurement_receipt",
        type_="check",
    )
    op.create_check_constraint(
        "walk_measurement_drift_known",
        "walk_measurement_receipt",
        sa.text(
            "drift_assessment IN ('not_assessed', 'insufficient_evidence', 'suspected')"
        ),
    )
