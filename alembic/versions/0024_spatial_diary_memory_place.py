"""Stable Memory Place identity and explicit Episode Pin membership.

Memory Place는 walk_session의 자식이 아니다. 산책 하나가 삭제돼 membership이 사라져도 장소
identity와 생성 당시 footprint는 남는다. 반대로 membership은 source Pin 삭제를 따라간다.

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geography

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_diary_memory_place",
        sa.Column("place_id", sa.Text(), primary_key=True),
        sa.Column("place_version", sa.Integer(), nullable=False),
        sa.Column("dog_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text()),
        sa.Column("footprint_kind", sa.Text(), nullable=False),
        sa.Column("footprint_centre", Geography("POINT", srid=4326), nullable=False),
        sa.Column("footprint_radius_m", sa.Float(), nullable=False),
        sa.Column("grouping_policy_version", sa.Integer(), nullable=False),
        sa.Column("seed_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("place_version > 0", name="spatial_diary_place_version_positive"),
        sa.CheckConstraint(
            "label IS NULL OR (char_length(label) BETWEEN 1 AND 80)",
            name="spatial_diary_place_label_valid",
        ),
        sa.CheckConstraint(
            "footprint_kind = 'circle' AND footprint_radius_m > 0 AND footprint_radius_m <= 5000",
            name="spatial_diary_place_footprint_valid",
        ),
        sa.CheckConstraint(
            "grouping_policy_version > 0",
            name="spatial_diary_place_grouping_policy_positive",
        ),
        sa.UniqueConstraint(
            "dog_id",
            "seed_fingerprint",
            name="spatial_diary_place_seed_unique",
        ),
    )
    op.create_index(
        "spatial_diary_place_dog_created_idx",
        "spatial_diary_memory_place",
        ["dog_id", "created_at"],
    )
    op.create_index(
        "spatial_diary_place_footprint_idx",
        "spatial_diary_memory_place",
        ["footprint_centre"],
        postgresql_using="gist",
    )

    op.create_table(
        "spatial_diary_memory_place_membership",
        sa.Column(
            "place_id",
            sa.Text(),
            sa.ForeignKey("spatial_diary_memory_place.place_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "pin_id",
            sa.Text(),
            sa.ForeignKey("spatial_diary_episode_pin.pin_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("pin_id", name="spatial_diary_place_pin_unique"),
        sa.CheckConstraint(
            "membership_version > 0",
            name="spatial_diary_place_membership_version_positive",
        ),
        sa.CheckConstraint(
            "origin IN ('seed', 'user_linked')",
            name="spatial_diary_place_membership_origin_known",
        ),
    )
    op.create_index(
        "spatial_diary_place_membership_place_time_idx",
        "spatial_diary_memory_place_membership",
        ["place_id", "linked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "spatial_diary_place_membership_place_time_idx",
        table_name="spatial_diary_memory_place_membership",
    )
    op.drop_table("spatial_diary_memory_place_membership")
    op.drop_index("spatial_diary_place_footprint_idx", table_name="spatial_diary_memory_place")
    op.drop_index("spatial_diary_place_dog_created_idx", table_name="spatial_diary_memory_place")
    op.drop_table("spatial_diary_memory_place")
