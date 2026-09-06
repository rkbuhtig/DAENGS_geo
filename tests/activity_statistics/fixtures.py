"""Normalized trusted-source fixtures, including DEV's multi-pet walk shape."""

from app.features.activity_statistics.common import ProjectionIdentity
from app.features.activity_statistics.sessions import SessionSource
from app.features.activity_statistics.territory import (
    ConfirmedCut,
    TerritoryCoverage,
    TerritoryStatEvent,
)
from app.features.activity_statistics.walk import (
    AnalysisVersions,
    WalkMetrics,
    WalkSelection,
    WalkStatSource,
)

MINUTE = 60_000
CLIENT_W1 = "00000000-0000-4000-8000-000000000001"
CLIENT_W2 = "00000000-0000-4000-8000-000000000002"
GENERATION = ProjectionIdentity("fixture-generation-1")
VERSIONS = AnalysisVersions(4, 4, 1, 1)
COVERAGE = TerritoryCoverage("season-1", 0, 30 * MINUTE, 0)
CUT = ConfirmedCut("season-1", 4, 20 * MINUTE)


def session(kind="WALK", *, owner="owner-1", server_id=None, client=CLIENT_W1, pets=("p1", "p2")):
    return SessionSource(kind, owner, client, server_id or f"{kind.lower()}-1", 0, frozenset(pets))


def walk_source():
    return WalkStatSource(
        session(),
        10 * MINUTE,
        "analysis-1",
        "fingerprint-1",
        VERSIONS,
        "receipt-1",
        "device",
        WalkMetrics(400, 480, 1, 120),
    )


def selection(source=None, revision=1):
    source = source or walk_source()
    return WalkSelection(
        source.session.owner_id, source.session.server_session_id, revision, source
    )


def ownership_event(
    revision, minute, *, pet="p1", previous=None, site="A", verified=False, kind="OWNERSHIP_CHANGED"
):
    return TerritoryStatEvent(
        "season-1",
        f"event-{revision}",
        revision,
        minute * MINUTE,
        kind,
        site,
        pet,
        previous,
        f"game-{pet}",
        f"claim-{revision}",
        verified,
    )


def territory_events():
    return (
        TerritoryStatEvent("season-1", "init", 1, 0, "INITIALIZED"),
        ownership_event(2, 2),
        ownership_event(3, 4, previous="p1", verified=True, kind="CERTIFIED"),
        ownership_event(4, 12, pet="p2", previous="p1", verified=True),
    )
