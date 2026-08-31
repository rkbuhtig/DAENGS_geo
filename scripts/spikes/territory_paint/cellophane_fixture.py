"""PR3 검증 화면용 결정론적 Cellophane GeoJSON fixture.

기존 산책 관통 fixture를 그대로 canonical facts → Paint v2 → GeoJSON 경로에 넣는다. 따라서
pause 전후 두 continuity chain과 서버 육각 셀, 질량 진단을 화면 하나에서 함께 확인할 수 있다.

    uv run python -m scripts.spikes.territory_paint.cellophane_fixture --out cellophane.json
    DAENGS_DEV_CONSOLE=true uv run uvicorn app.main:app --reload
    # http://127.0.0.1:8000/cellophane
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.features.territory.geojson import (
    cellophane_feature_collection,
    dumps_cellophane_geojson,
)
from app.features.territory.paint import NARROW_STEP, paint_sheet
from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix
from scripts.verify.walk_fixture import route

START = datetime(2026, 8, 31, 9, tzinfo=UTC)
SESSION_ID = "cellophane-fixture"
RADIUS_U = 8.0


def fixture_parts(radius_u: float = RADIUS_U):
    fixes = [
        WalkFix(
            client_seq=row["client_seq"],
            chain_index=row["chain_index"],
            at=START + timedelta(seconds=row["offset_s"]),
            lat=row["lat"],
            lng=row["lng"],
            accuracy_m=row["accuracy_m"],
            is_mock=True,
        )
        for row in route()
    ]
    computed = compute_facts(SESSION_ID, "fixture-dog", START, fixes[-1].at, fixes)
    sheet = paint_sheet(SESSION_ID, START, computed.segments, radius_u, NARROW_STEP)
    return sheet, computed.segments


def build_fixture(radius_u: float = RADIUS_U) -> dict[str, object]:
    sheet, segments = fixture_parts(radius_u)
    return cellophane_feature_collection(sheet, segments)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="cellophane.json")
    parser.add_argument("--radius-u", type=float, default=RADIUS_U)
    args = parser.parse_args(argv)

    sheet, segments = fixture_parts(args.radius_u)
    output = Path(args.out)
    output.write_text(dumps_cellophane_geojson(sheet, segments) + "\n", encoding="utf-8")
    meta = cellophane_feature_collection(sheet, segments)["meta"]
    print(
        f"{output}: segment {meta['source_segment_s']:.1f}s · "
        f"painted {meta['occupancy_mass_s']:.1f}s · "
        f"error {meta['mass_error_s']:.4f}s · {meta['cell_count']} cells"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
