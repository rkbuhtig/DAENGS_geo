"""공간 일기 조립과 승격이 여러 SELECT 사이에 DB 시점을 섞지 않게 한다."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SNAPSHOT_TRANSACTION_KEY = "spatial_diary_snapshot_transaction"


class SpatialDiaryTransactionError(RuntimeError):
    pass


async def ensure_repeatable_read_snapshot(db: AsyncSession) -> None:
    """현재 호출이 연 fresh transaction을 repeatable-read snapshot으로 고정한다."""

    transaction = db.sync_session.get_transaction()
    if transaction is not None:
        if db.info.get(_SNAPSHOT_TRANSACTION_KEY) is transaction:
            return
        raise SpatialDiaryTransactionError(
            "Spatial Diary operation requires a fresh session transaction"
        )

    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    db.info[_SNAPSHOT_TRANSACTION_KEY] = db.sync_session.get_transaction()
