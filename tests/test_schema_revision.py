"""도입 전 DB 의 적용 지점 판별. DB 불필요 — 지표 존재 여부를 함수로 주입한다.

이 판별이 틀리면 뒤처진 스키마를 최신으로 위장하게 되므로, 무엇보다 **모르면 멈추는** 쪽을
지킨다 (`out_of_order`).
"""

import re
from pathlib import Path

from app.core.schema_revision import HEAD, LEGACY_MARKERS, LegacyMarker, detect

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def up_to(revision: str):
    """`revision` 까지 적용된 DB 를 흉내낸다."""
    limit = [m.revision for m in LEGACY_MARKERS].index(revision)
    return lambda marker: [m.revision for m in LEGACY_MARKERS].index(marker.revision) <= limit


def test_empty_database_has_nothing_to_stamp():
    detection = detect(lambda _: False)

    assert detection.stamp_at is None
    assert detection.safe
    assert len(detection.missing) == len(LEGACY_MARKERS)


def test_current_database_stamps_at_head():
    detection = detect(lambda _: True)

    assert detection.stamp_at == HEAD
    assert detection.up_to_date
    assert detection.missing == ()


def test_database_stopped_at_009_stamps_there_and_upgrades_the_rest():
    detection = detect(up_to("0009"))

    assert detection.stamp_at == "0009"
    assert not detection.up_to_date
    assert detection.safe
    # 리뷰에서 지적된 바로 그 케이스: 이것들이 upgrade 로 실제 적용돼야 한다.
    assert [m.revision for m in detection.missing] == ["0010", "0011", "0012", "0013", "0014"]


def test_database_missing_only_anchor_is_consistent():
    """PR #46 전에 최신이던 DB. 011 두 개의 순서를 파일명이 아니라 실제 도착 순으로 둔 이유다."""
    detection = detect(up_to("0011"))

    assert detection.stamp_at == "0011"
    assert detection.safe
    assert [m.source for m in detection.missing] == [
        "011_anchor.sql", "0013_facility_pet_axes.py",
        "0014_encounter_bands_10_15_20.py",
    ]


def test_a_hole_in_the_chain_refuses_to_stamp():
    """007 은 없는데 009 가 있는 DB. 틀린 stamp 는 stamp 를 안 한 것보다 나쁘다."""
    missing_007 = {"0007", "0008"}

    detection = detect(lambda marker: marker.revision not in missing_007)

    assert not detection.safe
    assert detection.stamp_at == "0006"
    assert [m.revision for m in detection.out_of_order] == [
        "0009", "0010", "0011", "0012", "0013", "0014",
    ]


def test_markers_match_the_revision_chain_in_order():
    """리비전을 추가하면서 지표를 안 넣으면 판별이 조용히 뒤처진다. 여기서 깨뜨린다."""
    chain: dict[str, str | None] = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision: str = "([^"]+)"', text, re.MULTILINE).group(1)
        down = re.search(r"^down_revision: str \| None = (.+)$", text, re.MULTILINE).group(1).strip()
        chain[revision] = None if down == "None" else down.strip('"')

    ordered: list[str] = []
    current = next(rev for rev, down in chain.items() if down is None)
    while current is not None:
        ordered.append(current)
        current = next((rev for rev, down in chain.items() if down == current), None)

    assert ordered == [m.revision for m in LEGACY_MARKERS]
    assert ordered[-1] == HEAD


def test_markers_are_one_per_revision_and_unique():
    assert len({m.revision for m in LEGACY_MARKERS}) == len(LEGACY_MARKERS)
    assert len({(m.table, m.column) for m in LEGACY_MARKERS}) == len(LEGACY_MARKERS)
    assert all(isinstance(m, LegacyMarker) for m in LEGACY_MARKERS)
