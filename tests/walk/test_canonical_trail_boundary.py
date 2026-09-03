"""CanonicalTrail과 receipt 원본의 노출 경계. Decision: #84."""

import ast
from dataclasses import fields
from pathlib import Path

from app.features.walk.facts import CanonicalTrail

APP_ROOT = Path(__file__).parents[2] / "app"


def _attribute_users(attribute: str) -> set[str]:
    users: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.Attribute) and node.attr == attribute
            for node in ast.walk(tree)
        ):
            users.add(path.relative_to(APP_ROOT).as_posix())
    return users


def test_raw_fix_collections_are_not_part_of_canonical_trail():
    trail_fields = {item.name for item in fields(CanonicalTrail)}
    assert trail_fields.isdisjoint({"accepted_fixes", "received_fixes", "receipt_input"})


def test_receipt_input_only_flows_through_the_producer_orchestrator_and_receipt_builder():
    allowed = {
        "features/walk/facts.py",
        "features/walk/api.py",
        "features/walk/capsule.py",
    }
    assert _attribute_users("receipt_input") <= allowed
    assert _attribute_users("accepted_fixes") <= allowed


def test_midpoint_sample_is_only_read_by_trail_context_capture():
    assert _attribute_users("midpoint_sample") <= {
        "features/walk/facts.py",
        "features/walk/capsule.py",
    }
