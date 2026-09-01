"""Spatial Diary review memory: immutable offers, append-only attestations, stable pins.

Candidate와 ClaimAllowance는 현재 Capsule에서 재계산하므로 저장하지 않는다. 실제 제시본부터
session cascade 아래 영속화한다.

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatial_diary_episode_offer",
        sa.Column("offer_id", sa.Text(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offer_version", sa.Integer(), nullable=False),
        sa.Column("source_observation_ids", postgresql.JSONB(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("representative_location", Geography("POINT", srid=4326), nullable=False),
        sa.Column("footprint_kind", sa.Text(), nullable=False),
        sa.Column("footprint_centre", Geography("POINT", srid=4326), nullable=False),
        sa.Column("footprint_radius_m", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("candidate_policy_version", sa.Integer(), nullable=False),
        sa.Column("claim_policy_version", sa.Integer(), nullable=False),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "session_id",
            "source_observation_ids",
            "candidate_policy_version",
            name="spatial_diary_offer_candidate_unique",
        ),
        sa.CheckConstraint("offer_version > 0", name="spatial_diary_offer_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(source_observation_ids) = 'array' "
            "AND jsonb_array_length(source_observation_ids) > 0",
            name="spatial_diary_offer_sources_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0",
            name="spatial_diary_offer_evidence_array",
        ),
        sa.CheckConstraint(
            "footprint_kind = 'circle' AND footprint_radius_m > 0 "
            "AND footprint_radius_m <= 5000",
            name="spatial_diary_offer_footprint_valid",
        ),
        sa.CheckConstraint(
            "candidate_policy_version > 0 AND claim_policy_version > 0",
            name="spatial_diary_offer_policy_versions_positive",
        ),
    )
    op.create_index(
        "spatial_diary_offer_session_time_idx",
        "spatial_diary_episode_offer",
        ["session_id", "offered_at"],
    )

    op.create_table(
        "spatial_diary_offer_interaction",
        sa.Column("interaction_id", sa.Text(), primary_key=True),
        sa.Column(
            "offer_id",
            sa.Text(),
            sa.ForeignKey("spatial_diary_episode_offer.offer_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interaction_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "offer_id",
            "kind",
            name="spatial_diary_interaction_offer_kind_unique",
        ),
        sa.CheckConstraint(
            "interaction_version > 0",
            name="spatial_diary_interaction_version_positive",
        ),
        sa.CheckConstraint(
            "kind IN ('viewed', 'dismissed', 'expired')",
            name="spatial_diary_interaction_kind_known",
        ),
        sa.CheckConstraint(
            "(kind = 'expired' AND actor = 'system') "
            "OR (kind IN ('viewed', 'dismissed') AND actor = 'user')",
            name="spatial_diary_interaction_actor_matches",
        ),
    )
    op.create_index(
        "spatial_diary_interaction_offer_time_idx",
        "spatial_diary_offer_interaction",
        ["offer_id", "occurred_at"],
    )

    op.create_table(
        "spatial_diary_walk_attestation",
        sa.Column("attestation_id", sa.Text(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "offer_id",
            sa.Text(),
            sa.ForeignKey("spatial_diary_episode_offer.offer_id", ondelete="CASCADE"),
        ),
        sa.Column("attestation_version", sa.Integer(), nullable=False),
        sa.Column("elicitation_mode", sa.Text(), nullable=False),
        sa.Column("review_disposition", sa.Text(), nullable=False),
        sa.Column("claims", postgresql.JSONB(), nullable=False),
        sa.Column("memory_action", sa.Text(), nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "supersedes_attestation_id",
            sa.Text(),
            sa.ForeignKey(
                "spatial_diary_walk_attestation.attestation_id",
                ondelete="SET NULL",
            ),
        ),
        sa.UniqueConstraint(
            "offer_id",
            name="spatial_diary_attestation_offer_unique",
        ),
        sa.CheckConstraint(
            "attestation_version > 0",
            name="spatial_diary_attestation_version_positive",
        ),
        sa.CheckConstraint(
            "elicitation_mode IN "
            "('system_offer', 'in_walk_bookmark', 'post_walk_manual', 'photo_associated')",
            name="spatial_diary_attestation_mode_known",
        ),
        sa.CheckConstraint(
            "(elicitation_mode = 'system_offer') = (offer_id IS NOT NULL)",
            name="spatial_diary_attestation_offer_matches_mode",
        ),
        sa.CheckConstraint(
            "review_disposition IN ('confirmed', 'rejected', 'uncertain')",
            name="spatial_diary_attestation_review_known",
        ),
        sa.CheckConstraint(
            "memory_action IN ('save', 'dismiss')",
            name="spatial_diary_attestation_memory_action_known",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(claims) = 'array'",
            name="spatial_diary_attestation_claims_array",
        ),
        sa.CheckConstraint(
            "review_disposition <> 'confirmed' OR jsonb_array_length(claims) > 0",
            name="spatial_diary_attestation_confirmed_has_claim",
        ),
        sa.CheckConstraint(
            "review_disposition <> 'rejected' OR "
            "(jsonb_array_length(claims) = 0 AND memory_action = 'dismiss')",
            name="spatial_diary_attestation_rejected_not_saved",
        ),
        sa.CheckConstraint(
            "supersedes_attestation_id IS NULL "
            "OR supersedes_attestation_id <> attestation_id",
            name="spatial_diary_attestation_not_self_superseding",
        ),
    )
    op.create_index(
        "spatial_diary_attestation_session_time_idx",
        "spatial_diary_walk_attestation",
        ["session_id", "attested_at"],
    )

    op.create_table(
        "spatial_diary_episode_pin",
        sa.Column("pin_id", sa.Text(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pin_version", sa.Integer(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "source_offer_id",
            sa.Text(),
            sa.ForeignKey("spatial_diary_episode_offer.offer_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "created_by_attestation_id",
            sa.Text(),
            sa.ForeignKey(
                "spatial_diary_walk_attestation.attestation_id",
                ondelete="CASCADE",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("event_at", sa.DateTime(timezone=True)),
        sa.Column("temporal_precision", sa.Text(), nullable=False),
        sa.Column("representative_location", Geography("POINT", srid=4326), nullable=False),
        sa.Column("footprint_kind", sa.Text(), nullable=False),
        sa.Column("footprint_centre", Geography("POINT", srid=4326), nullable=False),
        sa.Column("footprint_radius_m", sa.Float(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pin_version > 0", name="spatial_diary_pin_version_positive"),
        sa.CheckConstraint(
            "origin IN "
            "('system_offer', 'in_walk_bookmark', 'post_walk_manual', 'photo_associated')",
            name="spatial_diary_pin_origin_known",
        ),
        sa.CheckConstraint(
            "(origin = 'system_offer') = (source_offer_id IS NOT NULL)",
            name="spatial_diary_pin_offer_matches_origin",
        ),
        sa.CheckConstraint(
            "temporal_precision IN ('exact', 'approximate', 'unknown')",
            name="spatial_diary_pin_temporal_precision_known",
        ),
        sa.CheckConstraint(
            "(temporal_precision = 'unknown') = (event_at IS NULL)",
            name="spatial_diary_pin_event_time_matches_precision",
        ),
        sa.CheckConstraint(
            "footprint_kind = 'circle' AND footprint_radius_m > 0 "
            "AND footprint_radius_m <= 5000",
            name="spatial_diary_pin_footprint_valid",
        ),
    )
    op.create_index(
        "spatial_diary_pin_session_event_idx",
        "spatial_diary_episode_pin",
        ["session_id", "event_at"],
    )
    op.create_index(
        "spatial_diary_pin_location_idx",
        "spatial_diary_episode_pin",
        ["representative_location"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("spatial_diary_pin_location_idx", table_name="spatial_diary_episode_pin")
    op.drop_index("spatial_diary_pin_session_event_idx", table_name="spatial_diary_episode_pin")
    op.drop_table("spatial_diary_episode_pin")
    op.drop_index(
        "spatial_diary_attestation_session_time_idx",
        table_name="spatial_diary_walk_attestation",
    )
    op.drop_table("spatial_diary_walk_attestation")
    op.drop_index(
        "spatial_diary_interaction_offer_time_idx",
        table_name="spatial_diary_offer_interaction",
    )
    op.drop_table("spatial_diary_offer_interaction")
    op.drop_index(
        "spatial_diary_offer_session_time_idx",
        table_name="spatial_diary_episode_offer",
    )
    op.drop_table("spatial_diary_episode_offer")
