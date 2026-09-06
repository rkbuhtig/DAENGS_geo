"""Explicit persistence codec for trusted core values; no dynamic object imports."""

import json
from dataclasses import asdict

from .sessions import SessionSource
from .territory import HoldingPeriod, InitialOwner, TerritoryStatEvent
from .walk import AnalysisVersions, WalkContribution, WalkMetrics, WalkSelection, WalkStatSource


def encode(value):
    return json.dumps(asdict(value), default=lambda v: sorted(v), sort_keys=True)


def session_source(value):
    return SessionSource(**value)


def walk_source(value):
    return WalkStatSource(
        **{
            **value,
            "session": session_source(value["session"]),
            "versions": AnalysisVersions(**value["versions"]),
            "metrics": WalkMetrics(**value["metrics"]) if value["metrics"] is not None else None,
        }
    )


def selection(value):
    return WalkSelection(
        **{
            **value,
            "source": walk_source(value["source"]) if value["source"] is not None else None,
        }
    )


def contribution(value):
    return WalkContribution(**{**value, "source": walk_source(value["source"])})


def event(value):
    return TerritoryStatEvent(
        **{
            **value,
            "initial_owners": tuple(InitialOwner(**v) for v in value["initial_owners"]),
        }
    )


def period(value):
    return HoldingPeriod(**{**value, "period_id": tuple(value["period_id"])})
