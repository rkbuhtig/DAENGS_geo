"""Private immutable PublishedJournalSnapshot for one sealed walk.

The snapshot freezes user-authored title and summary plus an ordered selection of
existing Episode Pin ids. It is private in v0 and follows the source capsule's
deletion lifecycle.

Revision ID: 0028
Revises: 0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_diary_published_journal",
        sa.Column("snapshot_id", sa.Text(), primary_key=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_capsule_manifest.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("selected_pin_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_projection_version", sa.Integer(), nullable=False),
        sa.Column("source_narration_policy_version", sa.Integer(), nullable=False),
        sa.Column("source_context_policy_version", sa.Integer(), nullable=False),
        sa.Column("source_capsule_version", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "snapshot_version > 0",
            name="spatial_diary_published_journal_version_positive",
        ),
        sa.CheckConstraint(
            "visibility = 'private'",
            name="spatial_diary_published_journal_private_v0",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200 AND btrim(title) <> ''",
            name="spatial_diary_published_journal_title_valid",
        ),
        sa.CheckConstraint(
            "char_length(summary) BETWEEN 1 AND 5000 AND btrim(summary) <> ''",
            name="spatial_diary_published_journal_summary_valid",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selected_pin_ids) = 'array' "
            "AND jsonb_array_length(selected_pin_ids) <= 100",
            name="spatial_diary_published_journal_pins_valid",
        ),
        sa.CheckConstraint(
            "source_projection_version > 0 "
            "AND source_narration_policy_version > 0 "
            "AND source_context_policy_version > 0 "
            "AND source_capsule_version > 0",
            name="spatial_diary_published_journal_source_versions_positive",
        ),
    )
    op.create_index(
        "spatial_diary_published_journal_walk_time_idx",
        "spatial_diary_published_journal",
        ["session_id", "published_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "spatial_diary_published_journal_walk_time_idx",
        table_name="spatial_diary_published_journal",
    )
    op.drop_table("spatial_diary_published_journal")
