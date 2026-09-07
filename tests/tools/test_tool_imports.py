"""Discover Python review adapters so moving them out of scripts keeps import coverage."""

import importlib
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _modules() -> list[str]:
    return [
        ".".join(path.relative_to(TOOLS.parent).with_suffix("").parts)
        for path in sorted(TOOLS.rglob("*.py"))
        if path.name != "__init__.py"
        and "__pycache__" not in path.parts
        and all(part.isidentifier() for part in path.relative_to(TOOLS).with_suffix("").parts)
    ]


def test_discovers_review_adapters():
    found = _modules()
    assert "tools.walk_trace.lab" in found
    assert "tools.territory_game.season_lab" in found
    assert "tools.lab_server" in found


@pytest.mark.parametrize("module", _modules())
def test_tool_imports(module: str):
    importlib.import_module(module)
