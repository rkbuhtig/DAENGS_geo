"""The design's first vertical slice, in memory; PostgreSQL/restarts are S3."""

import subprocess
import sys
from dataclasses import replace

from app.features.activity_statistics.sessions import resolve_session_links
from app.features.activity_statistics.territory import (
    TerritoryStatEvent,
    project_territory,
    summarize_territory,
)
from app.features.activity_statistics.walk import project_walks, summarize_walks
from app.features.territory_game.policy import (
    OwnershipCandidate,
    Rules,
    Score,
    SeasonContext,
    SiteSnapshot,
    plan_ownership,
)
from tests.activity_statistics.fixtures import (
    CLIENT_W2,
    COVERAGE,
    CUT,
    GENERATION,
    MINUTE,
    VERSIONS,
    selection,
    session,
    territory_events,
)


def test_late_upload_links_to_real_policy_facts_without_replaying_rewards():
    game1, walk1 = session("GAME"), session()
    game2 = replace(
        session("GAME", client=CLIENT_W2, server_id="game-2", pets=("p2",)), started_ms=11 * MINUTE
    )
    assert resolve_session_links([game1])[0].walk is None
    season = SeasonContext("season-1", 0, 30 * MINUTE, Rules())
    site = SiteSnapshot("season-1", "A", 0, None)
    scores = {"p1": Score(), "p2": Score()}
    events = [territory_events()[0]]
    operations = (
        (2, "p1", "game-1", "claim-1", "MARK", "UNVERIFIED"),
        (4, "p1", "game-1", "claim-1", "PHOTO_VERIFIED", "VERIFIED"),
        (12, "p2", "game-2", "claim-2", "PHOTO_VERIFIED", "VERIFIED"),
    )
    for revision, (minute, pet, game, claim, cause, certification) in enumerate(operations, 2):
        command = OwnershipCandidate(
            "season-1",
            f"source-{revision}",
            "A",
            site.version,
            pet,
            game,
            claim,
            certification,
            cause,
        )
        affected = {pet} | ({site.owner.pet_id} if site.owner else set())
        plan = plan_ownership(
            season, site, command, {p: scores[p] for p in affected}, at_ms=minute * MINUTE
        )
        # Test-only normalization of committed plan shape. Production persistence hook is S4.
        events.append(
            TerritoryStatEvent(
                "season-1",
                command.event_id,
                revision,
                plan.at_ms,
                plan.kind,
                "A",
                plan.after.owner.pet_id,
                plan.before.owner.pet_id if plan.before.owner else None,
                command.session_id,
                command.attempt_id,
                plan.after.owner.certification == "VERIFIED",
            )
        )
        site = plan.after
        scores.update({account.pet_id: account.score for account in plan.accounts})
    score_before = dict(scores)
    links = resolve_session_links([game1, game2, walk1, game1, walk1])
    assert [link.status for link in links] == ["LINKED", "WAITING_FOR_WALK"]
    walks = project_walks(
        [selection(), selection()], identity=GENERATION, expected_versions=VERSIONS
    )
    walk = summarize_walks(walks, owner_id="owner-1", from_ms=0, to_ms=20 * MINUTE)
    assert walk.recorded_walk_count == 1 and walk.moving_distance_m == 400
    territory = project_territory(events * 3, identity=GENERATION, coverage=COVERAGE, cut=CUT)
    p1 = summarize_territory(territory, pet_id="p1")
    p2 = summarize_territory(territory, pet_id="p2")
    assert (p1.held_site_ms, p1.verified_held_site_ms, p2.held_site_ms) == (
        10 * MINUTE,
        8 * MINUTE,
        8 * MINUTE,
    )
    assert scores == score_before


def test_core_imports_without_database_web_measurement_or_policy_producers():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
class BlockInfrastructure:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'sqlalchemy', 'pydantic', 'sqlite3'} or any(
            fullname == prefix or fullname.startswith(prefix + '.') for prefix in (
                'app.core', 'app.features.walk', 'app.features.territory',
            )
        ):
            raise RuntimeError('unexpected dependency: ' + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from app.features.activity_statistics.sessions import resolve_session_links
from app.features.activity_statistics.walk import project_walks
from app.features.activity_statistics.territory import project_territory
assert resolve_session_links([]) == ()
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
