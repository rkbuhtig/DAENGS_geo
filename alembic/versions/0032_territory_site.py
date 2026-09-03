"""점령 게임의 중립 지점을 Territory Site 어휘로 옮긴다.

`anchor`는 행동 책갈피와도 충돌하고 HTTP 자원의 역할도 설명하지 못했다. 아직 점령 이력이
없을 때 저장 이름과 안정 ID를 함께 바꾼다. 원천 보안등과 게임 셀은 여전히 한 행이다.

Revision ID: 0032
Revises: 0031
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("anchor", "territory_site")
    op.alter_column("territory_site", "cell", new_column_name="site_id")
    op.execute(
        "UPDATE territory_site "
        "SET site_id = regexp_replace(site_id, '^anchor-hex:', 'territory-site:hex-v1:') "
        "WHERE site_id LIKE 'anchor-hex:%'"
    )

    op.drop_constraint("anchor_source_cell_key", "territory_site", type_="unique")
    op.create_unique_constraint(
        "territory_site_site_id_key",
        "territory_site",
        ["site_id"],
    )
    op.execute("ALTER TABLE territory_site RENAME CONSTRAINT anchor_pkey TO territory_site_pkey")
    op.execute("ALTER INDEX anchor_gix RENAME TO territory_site_gix")
    op.execute("ALTER INDEX anchor_kind_idx RENAME TO territory_site_kind_idx")
    op.execute("ALTER SEQUENCE anchor_id_seq RENAME TO territory_site_id_seq")


def downgrade() -> None:
    op.execute("ALTER SEQUENCE territory_site_id_seq RENAME TO anchor_id_seq")
    op.execute("ALTER INDEX territory_site_kind_idx RENAME TO anchor_kind_idx")
    op.execute("ALTER INDEX territory_site_gix RENAME TO anchor_gix")
    op.execute("ALTER TABLE territory_site RENAME CONSTRAINT territory_site_pkey TO anchor_pkey")
    op.drop_constraint("territory_site_site_id_key", "territory_site", type_="unique")
    op.create_unique_constraint(
        "anchor_source_cell_key",
        "territory_site",
        ["source", "site_id"],
    )

    op.execute(
        "UPDATE territory_site "
        "SET site_id = regexp_replace(site_id, '^territory-site:hex-v1:', 'anchor-hex:') "
        "WHERE site_id LIKE 'territory-site:hex-v1:%'"
    )
    op.alter_column("territory_site", "site_id", new_column_name="cell")
    op.rename_table("territory_site", "anchor")
