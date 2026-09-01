"""Attach append-only correction attestations to stable Episode Pins.

The creating attestation remains the Pin's immutable origin. A correction points
to the same Pin, supersedes exactly one current head, and is resolved only by
derived readers such as Journal and Memory Place biography.

Revision ID: 0030
Revises: 0029
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "spatial_diary_walk_attestation",
        sa.Column("pin_id", sa.Text()),
    )
    op.create_foreign_key(
        "spatial_diary_attestation_pin_fk",
        "spatial_diary_walk_attestation",
        "spatial_diary_episode_pin",
        ["pin_id"],
        ["pin_id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "spatial_diary_attestation_mode_known",
        "spatial_diary_walk_attestation",
        type_="check",
    )
    op.create_check_constraint(
        "spatial_diary_attestation_mode_known_v2",
        "spatial_diary_walk_attestation",
        sa.text(
            "elicitation_mode IN "
            "('system_offer', 'in_walk_bookmark', 'post_walk_manual', "
            "'photo_associated', 'pin_correction')"
        ),
    )
    op.create_check_constraint(
        "spatial_diary_attestation_correction_shape",
        "spatial_diary_walk_attestation",
        sa.text(
            "(elicitation_mode = 'pin_correction') = "
            "(supersedes_attestation_id IS NOT NULL) "
            "AND (elicitation_mode = 'pin_correction') = (pin_id IS NOT NULL) "
            "AND (elicitation_mode <> 'pin_correction' OR "
            "(offer_id IS NULL AND memory_action = 'save'))"
        ),
    )
    op.create_unique_constraint(
        "spatial_diary_attestation_supersedes_unique",
        "spatial_diary_walk_attestation",
        ["supersedes_attestation_id"],
    )
    op.create_index(
        "spatial_diary_attestation_pin_time_idx",
        "spatial_diary_walk_attestation",
        ["pin_id", "attested_at", "attestation_id"],
    )


def downgrade() -> None:
    # The former schema cannot represent corrections. Removing only correction
    # rows restores each Pin's immutable creating attestation as the effective one.
    op.execute(sa.text("""
        DELETE FROM spatial_diary_walk_attestation
        WHERE elicitation_mode = 'pin_correction'
    """))
    op.drop_index(
        "spatial_diary_attestation_pin_time_idx",
        table_name="spatial_diary_walk_attestation",
    )
    op.drop_constraint(
        "spatial_diary_attestation_supersedes_unique",
        "spatial_diary_walk_attestation",
        type_="unique",
    )
    op.drop_constraint(
        "spatial_diary_attestation_correction_shape",
        "spatial_diary_walk_attestation",
        type_="check",
    )
    op.drop_constraint(
        "spatial_diary_attestation_mode_known_v2",
        "spatial_diary_walk_attestation",
        type_="check",
    )
    op.create_check_constraint(
        "spatial_diary_attestation_mode_known",
        "spatial_diary_walk_attestation",
        sa.text(
            "elicitation_mode IN "
            "('system_offer', 'in_walk_bookmark', 'post_walk_manual', 'photo_associated')"
        ),
    )
    op.drop_constraint(
        "spatial_diary_attestation_pin_fk",
        "spatial_diary_walk_attestation",
        type_="foreignkey",
    )
    op.drop_column("spatial_diary_walk_attestation", "pin_id")
