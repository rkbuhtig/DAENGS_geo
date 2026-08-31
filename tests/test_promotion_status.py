from pathlib import Path

import pytest

from scripts.promotion_status import (
    LedgerError,
    SurfaceStatus,
    load_surfaces,
    report,
)


def test_repository_ledger_has_the_expected_surfaces():
    """일반 pytest checkout은 shallow다. 과거 commit 검증은 fetch-depth: 0인 승격 CI가 맡는다."""
    surfaces = load_surfaces()
    assert {surface.id for surface in surfaces} == {
        "place-search",
        "journey-service",
        "android-place",
        "android-walk",
    }


def test_ledger_rejects_parent_traversal(tmp_path: Path):
    ledger = tmp_path / "ledger.toml"
    ledger.write_text(
        """
version = 1
[[surface]]
id = "bad"
title = "bad"
source_commit = "abc"
target_repo = "owner/repo"
target_branch = "dev"
target_path = "path/"
target_commit = "def"
paths = ["../outside"]
""",
        encoding="utf-8",
    )
    with pytest.raises(LedgerError, match="저장소 상대 경로"):
        load_surfaces(ledger)


def test_report_calls_pending_a_review_marker_not_an_error():
    surface = load_surfaces()[0]
    text = report((SurfaceStatus(surface, 2, ("app/place/search.py",), ()),))
    assert "[PENDING]" in text
    assert "자동 이관 지시가 아니라" in text
    assert "2 commits / 1 files" in text
