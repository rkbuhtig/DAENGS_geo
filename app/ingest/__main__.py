"""`python -m app.ingest {full|incremental}` 실행점."""

import argparse
import asyncio
import json

from app.core.config import settings
from app.core.db import SessionLocal
from app.ingest.mois import SOURCES, MoisClient
from app.ingest.mois_store import MoisStore
from app.ingest.mois_sync import SyncMode, sync_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="행안부 동물병원/약국 데이터를 PostGIS에 동기화")
    parser.add_argument("mode", choices=("full", "incremental"))
    parser.add_argument("--kind", choices=("all", "hospital", "pharmacy"), default="all")
    return parser


async def _run(mode: SyncMode, kind: str) -> None:
    selected = list(SOURCES.values()) if kind == "all" else [SOURCES[kind]]
    async with MoisClient(
        settings.data_go_kr_service_key,
        page_size=settings.mois_page_size,
    ) as client:
        for source in selected:
            async with SessionLocal() as session:
                stats = await sync_source(
                    client,
                    MoisStore(session),
                    source,
                    mode=mode,
                    overlap_days=settings.mois_sync_overlap_days,
                )
                print(json.dumps(stats.to_dict(), ensure_ascii=False))


def main() -> None:
    args = _parser().parse_args()
    if not settings.data_go_kr_service_key:
        raise SystemExit("DAENGS_DATA_GO_KR_SERVICE_KEY is required")
    asyncio.run(_run(args.mode, args.kind))


if __name__ == "__main__":
    main()
