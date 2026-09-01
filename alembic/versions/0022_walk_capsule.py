"""Walk Capsule Core: macro sheet, raw receipt, trail context, seal manifest.

Manifest는 자식 payload를 복제하지 않는다. 같은 session_id의 필수 자식이 모두 쓰인 뒤 마지막에
생성되고, 그 뒤에만 walk_fix를 purge한다. 모든 테이블은 walk_session cascade를 상속한다.

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "walk_cellophane_sheet",
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("paint_version", sa.Integer(), nullable=False),
        sa.Column("grid_version", sa.Text(), nullable=False),
        sa.Column("radius_u", sa.Float(), nullable=False),
        sa.Column("profile_name", sa.Text(), nullable=False),
        sa.Column("profile_fp", sa.Text(), nullable=False),
        sa.Column("sample_step_m", sa.Float(), nullable=False),
        sa.Column("paint_fp", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("paint_version > 0", name="walk_cellophane_paint_version_positive"),
        sa.CheckConstraint("radius_u > 0", name="walk_cellophane_radius_positive"),
        sa.CheckConstraint("sample_step_m > 0", name="walk_cellophane_step_positive"),
    )
    op.create_index("walk_cellophane_paint_fp_idx", "walk_cellophane_sheet", ["paint_fp"])

    op.create_table(
        "walk_cellophane_cell",
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_cellophane_sheet.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("q", sa.Integer(), primary_key=True),
        sa.Column("r", sa.Integer(), primary_key=True),
        sa.Column("occupancy_s", sa.Float(), nullable=False),
        sa.Column("peak", sa.Float(), nullable=False),
        sa.CheckConstraint("occupancy_s >= 0", name="walk_cellophane_occupancy_nonnegative"),
        sa.CheckConstraint("peak >= 0 AND peak <= 1", name="walk_cellophane_peak_unit"),
    )

    op.create_table(
        "walk_measurement_receipt",
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("receipt_version", sa.Integer(), nullable=False),
        sa.Column("evidence_origin", sa.Text(), nullable=False),
        sa.Column("received_fix_count", sa.Integer(), nullable=False),
        sa.Column("accepted_fix_count", sa.Integer(), nullable=False),
        sa.Column("rejected_low_accuracy_count", sa.Integer(), nullable=False),
        sa.Column("rejected_out_of_order_count", sa.Integer(), nullable=False),
        sa.Column("rejected_before_start_count", sa.Integer(), nullable=False),
        sa.Column("rejected_after_end_count", sa.Integer(), nullable=False),
        sa.Column("unknown_accuracy_count", sa.Integer(), nullable=False),
        sa.Column("jump_break_count", sa.Integer(), nullable=False),
        sa.Column("gap_break_count", sa.Integer(), nullable=False),
        sa.Column("explicit_break_count", sa.Integer(), nullable=False),
        sa.Column("dropped_at_capacity_count", sa.Integer(), nullable=False),
        sa.Column("mock_fix_count", sa.Integer(), nullable=False),
        sa.Column("session_wall_time_s", sa.Float(), nullable=False),
        sa.Column("canonical_segment_time_s", sa.Float(), nullable=False),
        sa.Column("gap_elapsed_s", sa.Float(), nullable=False),
        sa.Column("reported_accuracy_count", sa.Integer(), nullable=False),
        sa.Column("reported_accuracy_p50_m", sa.Float()),
        sa.Column("reported_accuracy_p90_m", sa.Float()),
        sa.Column("accepted_accuracy_count", sa.Integer(), nullable=False),
        sa.Column("accepted_accuracy_p50_m", sa.Float()),
        sa.Column("accepted_accuracy_p90_m", sa.Float()),
        sa.Column("drift_assessment", sa.Text(), nullable=False),
        sa.Column("drift_assessment_method", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "evidence_origin IN ('device', 'mock', 'mixed', 'unknown')",
            name="walk_measurement_origin_known",
        ),
        sa.CheckConstraint(
            "received_fix_count >= 0 AND accepted_fix_count >= 0 "
            "AND accepted_fix_count <= received_fix_count",
            name="walk_measurement_fix_counts_valid",
        ),
        sa.CheckConstraint(
            "rejected_low_accuracy_count >= 0 AND rejected_out_of_order_count >= 0 "
            "AND rejected_before_start_count >= 0 AND rejected_after_end_count >= 0 "
            "AND jump_break_count >= 0 AND gap_break_count >= 0 "
            "AND explicit_break_count >= 0 AND dropped_at_capacity_count >= 0 "
            "AND mock_fix_count >= 0 AND mock_fix_count <= received_fix_count",
            name="walk_measurement_quality_counts_valid",
        ),
        sa.CheckConstraint(
            "unknown_accuracy_count >= 0 AND unknown_accuracy_count <= accepted_fix_count",
            name="walk_measurement_unknown_accuracy_valid",
        ),
        sa.CheckConstraint(
            "reported_accuracy_count >= 0 AND reported_accuracy_count <= received_fix_count "
            "AND accepted_accuracy_count >= 0 AND accepted_accuracy_count <= accepted_fix_count",
            name="walk_measurement_accuracy_counts_valid",
        ),
        sa.CheckConstraint(
            "session_wall_time_s >= 0 AND canonical_segment_time_s >= 0 "
            "AND canonical_segment_time_s <= session_wall_time_s "
            "AND gap_elapsed_s >= 0 AND gap_elapsed_s <= session_wall_time_s",
            name="walk_measurement_times_valid",
        ),
        sa.CheckConstraint(
            "((reported_accuracy_count = 0 AND reported_accuracy_p50_m IS NULL "
            "AND reported_accuracy_p90_m IS NULL) OR "
            "(reported_accuracy_count > 0 AND reported_accuracy_p50_m IS NOT NULL "
            "AND reported_accuracy_p90_m IS NOT NULL "
            "AND reported_accuracy_p50_m >= 0 "
            "AND reported_accuracy_p50_m <= reported_accuracy_p90_m)) "
            "AND ((accepted_accuracy_count = 0 AND accepted_accuracy_p50_m IS NULL "
            "AND accepted_accuracy_p90_m IS NULL) OR "
            "(accepted_accuracy_count > 0 AND accepted_accuracy_p50_m IS NOT NULL "
            "AND accepted_accuracy_p90_m IS NOT NULL "
            "AND accepted_accuracy_p50_m >= 0 "
            "AND accepted_accuracy_p50_m <= accepted_accuracy_p90_m))",
            name="walk_measurement_accuracy_percentiles_paired",
        ),
        sa.CheckConstraint(
            "drift_assessment IN ('not_assessed', 'insufficient_evidence', 'suspected')",
            name="walk_measurement_drift_known",
        ),
        sa.CheckConstraint(
            "(drift_assessment = 'not_assessed') = (drift_assessment_method IS NULL)",
            name="walk_measurement_drift_method_matches",
        ),
    )

    op.create_table(
        "walk_trail_context",
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("walked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_observed_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.Text()),
        sa.Column("precipitation_mm", sa.Float()),
        sa.Column("temperature_c", sa.Float()),
        sa.Column("humidity_pct", sa.Float()),
        sa.Column("sun_elevation_deg", sa.Float()),
        sa.Column("failure_reason", sa.Text()),
        sa.CheckConstraint(
            "status IN ('captured', 'partial', 'unknown', 'failed')",
            name="walk_trail_context_status_known",
        ),
        sa.CheckConstraint(
            "status NOT IN ('captured', 'partial') OR "
            "(provider IS NOT NULL AND (precipitation_mm IS NOT NULL "
            "OR temperature_c IS NOT NULL OR humidity_pct IS NOT NULL "
            "OR sun_elevation_deg IS NOT NULL))",
            name="walk_trail_context_observed_payload",
        ),
        sa.CheckConstraint(
            "status NOT IN ('unknown', 'failed') OR "
            "(precipitation_mm IS NULL AND temperature_c IS NULL "
            "AND humidity_pct IS NULL AND sun_elevation_deg IS NULL)",
            name="walk_trail_context_unobserved_payload",
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR failure_reason IS NOT NULL",
            name="walk_trail_context_failure_reason",
        ),
        sa.CheckConstraint(
            "precipitation_mm IS NULL OR precipitation_mm >= 0",
            name="walk_trail_context_precipitation_valid",
        ),
        sa.CheckConstraint(
            "temperature_c IS NULL OR temperature_c BETWEEN -100 AND 100",
            name="walk_trail_context_temperature_valid",
        ),
        sa.CheckConstraint(
            "humidity_pct IS NULL OR humidity_pct BETWEEN 0 AND 100",
            name="walk_trail_context_humidity_valid",
        ),
        sa.CheckConstraint(
            "sun_elevation_deg IS NULL OR sun_elevation_deg BETWEEN -90 AND 90",
            name="walk_trail_context_sun_elevation_valid",
        ),
    )

    op.create_table(
        "walk_capsule_manifest",
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("walk_session.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("capsule_version", sa.Integer(), nullable=False),
        sa.Column("dog_id", sa.Text(), nullable=False),
        sa.Column("walk_record_version", sa.Integer(), nullable=False),
        sa.Column("walk_calculation_version", sa.Integer(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capsule_version > 0", name="walk_capsule_version_positive"),
        sa.CheckConstraint(
            "walk_record_version > 0 AND walk_calculation_version > 0",
            name="walk_capsule_walk_versions_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capabilities) = 'array'",
            name="walk_capsule_capabilities_array",
        ),
    )
    op.create_index("walk_capsule_dog_sealed_idx", "walk_capsule_manifest", ["dog_id", "sealed_at"])


def downgrade() -> None:
    op.drop_index("walk_capsule_dog_sealed_idx", table_name="walk_capsule_manifest")
    op.drop_table("walk_capsule_manifest")
    op.drop_table("walk_trail_context")
    op.drop_table("walk_measurement_receipt")
    op.drop_table("walk_cellophane_cell")
    op.drop_index("walk_cellophane_paint_fp_idx", table_name="walk_cellophane_sheet")
    op.drop_table("walk_cellophane_sheet")
