"""Separate certification protection from acquisition time."""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE territory_policy_site ADD COLUMN certified_ms bigint")
    op.execute(
        "UPDATE territory_policy_site SET certified_ms=occupied_ms WHERE certification='VERIFIED'"
    )


def downgrade():
    op.execute("ALTER TABLE territory_policy_site DROP COLUMN certified_ms")
