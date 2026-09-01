"""dev intent lab의 검색 시도와 명시적 사용자 행동을 append-only로 보존한다.

제품 검색 로그가 아니라 `DAENGS_DEV_CONSOLE` 뒤의 검증 표면 전용이다. 발화 원문을 저장하는
이유도 실패한 모델 해석을 재현하기 위해서이며, 운영 검색에 이 테이블을 자동 연결하지 않는다.

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "place_intent_lab_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "previous_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("place_intent_lab_attempt.id", ondelete="SET NULL"),
        ),
        sa.Column("utterance", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lng", sa.Double(), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_code", sa.Text()),
        sa.Column("interpretation_count", sa.Integer(), nullable=False),
        sa.Column("target_lens_count", sa.Integer(), nullable=False),
        sa.Column("executable_lens_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'needs_clarification', 'failed')",
            name="place_intent_lab_attempt_status_known",
        ),
        sa.CheckConstraint("radius_m BETWEEN 100 AND 20000"),
        sa.CheckConstraint(
            "interpretation_count >= 0 AND target_lens_count >= 0 "
            "AND executable_lens_count >= 0 AND result_count >= 0",
            name="place_intent_lab_attempt_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND failure_code IS NULL) OR "
            "(status <> 'completed' AND failure_code IS NOT NULL)",
            name="place_intent_lab_attempt_failure_matches_status",
        ),
    )
    op.create_index(
        "place_intent_lab_attempt_created_idx",
        "place_intent_lab_attempt",
        ["created_at"],
    )
    op.create_index(
        "place_intent_lab_attempt_failure_idx",
        "place_intent_lab_attempt",
        ["created_at"],
        postgresql_where=sa.text("failure_code IS NOT NULL"),
    )

    op.create_table(
        "place_intent_lab_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("place_intent_lab_attempt.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("lens_id", sa.Text()),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('search_completed', 'search_failed', 'search_revised', "
            "'lens_selected', 'facet_selected', 'lens_confirmed', 'search_reset')",
            name="place_intent_lab_event_type_known",
        ),
    )
    op.create_index(
        "place_intent_lab_event_attempt_idx",
        "place_intent_lab_event",
        ["attempt_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("place_intent_lab_event_attempt_idx", table_name="place_intent_lab_event")
    op.drop_table("place_intent_lab_event")
    op.drop_index("place_intent_lab_attempt_failure_idx", table_name="place_intent_lab_attempt")
    op.drop_index("place_intent_lab_attempt_created_idx", table_name="place_intent_lab_attempt")
    op.drop_table("place_intent_lab_attempt")
