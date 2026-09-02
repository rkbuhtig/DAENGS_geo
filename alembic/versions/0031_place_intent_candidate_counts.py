"""검색 후보 공급량과 화면 노출량을 분리해 관측한다.

기존 result_count는 화면 미리보기 개수였지만 이름만으로는 전체 후보 수처럼 읽혔다. 과거 행은
원래 후보 수를 복원할 수 없으므로 새 컬럼을 nullable로 추가하고, 신규 기록부터 세 값을 모두
채운다.

Revision ID: 0031
Revises: 0030
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "place_intent_lab_attempt",
        sa.Column("initial_candidate_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "place_intent_lab_attempt",
        sa.Column("eligible_candidate_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "place_intent_lab_attempt",
        sa.Column("displayed_result_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "place_intent_lab_attempt",
        sa.Column("initial_candidate_count_truncated", sa.Boolean(), nullable=True),
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_candidate_counts_nonnegative",
        "place_intent_lab_attempt",
        "(initial_candidate_count IS NULL OR initial_candidate_count >= 0) AND "
        "(eligible_candidate_count IS NULL OR eligible_candidate_count >= 0) AND "
        "(displayed_result_count IS NULL OR displayed_result_count >= 0)",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_displayed_alias_matches",
        "place_intent_lab_attempt",
        "displayed_result_count IS NULL OR result_count = displayed_result_count",
    )
    op.create_check_constraint(
        "place_intent_lab_attempt_candidate_counts_complete",
        "place_intent_lab_attempt",
        "(initial_candidate_count IS NULL AND eligible_candidate_count IS NULL AND "
        "displayed_result_count IS NULL AND initial_candidate_count_truncated IS NULL) OR "
        "(initial_candidate_count IS NOT NULL AND eligible_candidate_count IS NOT NULL AND "
        "displayed_result_count IS NOT NULL AND "
        "initial_candidate_count_truncated IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "place_intent_lab_attempt_candidate_counts_complete",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_constraint(
        "place_intent_lab_attempt_displayed_alias_matches",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_constraint(
        "place_intent_lab_attempt_candidate_counts_nonnegative",
        "place_intent_lab_attempt",
        type_="check",
    )
    op.drop_column("place_intent_lab_attempt", "initial_candidate_count_truncated")
    op.drop_column("place_intent_lab_attempt", "displayed_result_count")
    op.drop_column("place_intent_lab_attempt", "eligible_candidate_count")
    op.drop_column("place_intent_lab_attempt", "initial_candidate_count")
