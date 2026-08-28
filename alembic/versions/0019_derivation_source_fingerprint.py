"""파생값이 어느 입력에서 나왔는지 기록한다 — 원천이 바뀌면 스스로 낡았다고 말하게.

리비전 0018 은 `restriction_semantics_version` 으로 **규칙이 바뀐 것**은 잡았지만
**입력이 바뀐 것**은 못 잡는다. 재적재가 `facility.pet` 을 덮어써도 파생 컬럼은
그대로라, 배치의 미처리 조건(`state IS NULL OR 버전 불일치`)에 걸리지 않는다.

실증(2026-08-28): `pet.restrictions` 를 `목줄` → `대형견 입장 불가` 로 바꾸고 배치를
돌리면 **0행을 훑고 지나간다.** 그 행은 대형견 배제를 원문에 갖고도 `require:leash`
술어를 계속 내보낸다.

    fresh = (같은 규칙 버전) AND (같은 입력)

두 축이 다 맞아야 파생값이 유효하다. 이 리비전은 두 번째 축을 만든다 —
`*_source_fp` 에 입력의 지문(md5)을 넣고, 배치가 그것까지 비교한다.

## `pet_axes` 도 같은 결함을 갖고 있다

`app/ingest/pet_axes.py` 의 미처리 조건은 "축 컬럼이 비어 있는 행" 뿐이라, 같은
재적재에서 축도 낡은 채 남는다. **패턴의 결함이지 한 축의 버그가 아니므로** 두
파생층에 같은 컬럼을 만든다. 다음 파생 축(태그)도 이 규약을 따른다.

## 왜 해시인가 — 타임스탬프가 아니라

`facility.synced_at` 과 비교하는 방법도 있지만, 재적재가 값을 안 바꿔도 타임스탬프는
갱신되므로 33,611행을 매번 다시 판다. 지문은 **값이 실제로 바뀐 행만** 고른다.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "facility",
        sa.Column("restriction_source_fp", sa.Text(), nullable=True),
    )
    op.add_column(
        "facility",
        sa.Column("pet_axes_source_fp", sa.Text(), nullable=True),
    )
    # 지문 없는 파생값은 입력이 바뀌었는지 말할 수 없다. 기존 행은 NULL 로 남고
    # 배치가 미처리로 잡아 다시 판다 — 그게 이 리비전이 원하는 동작이다.
    op.create_check_constraint(
        "facility_restriction_fp_with_state",
        "facility",
        "restriction_state IS NULL OR restriction_source_fp IS NOT NULL "
        "OR restriction_semantics_version IS NOT NULL",
    )
    # "아직 지문이 없는 행" 조회. 0018 의 pending 인덱스와 같은 이유로 부분 인덱스다.
    op.create_index(
        "facility_restriction_fp_pending_idx",
        "facility",
        ["id"],
        postgresql_where=sa.text("restriction_source_fp IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("facility_restriction_fp_pending_idx", table_name="facility")
    op.drop_constraint("facility_restriction_fp_with_state", "facility", type_="check")
    op.drop_column("facility", "pet_axes_source_fp")
    op.drop_column("facility", "restriction_source_fp")
