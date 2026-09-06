from dataclasses import replace

import pytest

from app.features.activity_statistics.common import StatisticsError
from app.features.activity_statistics.sessions import resolve_session_links
from tests.activity_statistics.fixtures import CLIENT_W2, session


def test_late_walk_upload_and_reverse_arrival_converge_without_fake_walk():
    walk, game = session(), session("GAME")
    (pending,) = resolve_session_links([game])
    assert pending.status == "WAITING_FOR_WALK"
    assert pending.walk is None
    assert resolve_session_links([walk])[0].status == "WALK_ONLY"
    forward = resolve_session_links([game, walk, game, walk])
    assert forward == resolve_session_links([walk, game])
    assert forward[0].status == "LINKED"
    assert forward[0].walk.server_session_id == "walk-1"
    assert forward[0].game.server_session_id == "game-1"


def test_same_client_uuid_across_owners_is_not_a_shared_activity():
    links = resolve_session_links(
        [
            session("GAME"),
            session(owner="owner-2", server_id="walk-2"),
        ]
    )
    assert [link.status for link in links] == ["WAITING_FOR_WALK", "WALK_ONLY"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"started_ms": 1000}, "started_ms_mismatch"),
        ({"pet_ids": frozenset({"p3"})}, "participants_mismatch"),
    ],
)
def test_metadata_disagreement_preserves_both_sources_as_conflict(change, reason):
    walk, game = session(), replace(session("GAME"), **change)
    (link,) = resolve_session_links([walk, game])
    assert link.status == "CONFLICT"
    assert link.conflicts == (reason,)
    assert link.walk == walk and link.game == game


@pytest.mark.parametrize(
    "other,code",
    [
        (session(server_id="walk-2"), "session_link_conflict"),
        (session(client=CLIENT_W2), "session_id_conflict"),
        (session(owner="owner-2"), "session_id_conflict"),
        (session(pets=()), "session_id_conflict"),
    ],
)
def test_conflicting_source_identity_cannot_overwrite_or_cross_link(other, code):
    with pytest.raises(StatisticsError, match=code):
        resolve_session_links([session(), other])


def test_pet_order_and_uuid_notation_are_not_identity_changes():
    source = session(pets=("p2", "p1"))
    alternate = replace(source, client_walk_session_id="{" + source.client_walk_session_id + "}")
    assert resolve_session_links([source, alternate]) == resolve_session_links([source])


def test_invalid_client_uuid_is_rejected():
    with pytest.raises(StatisticsError, match="invalid_client_uuid"):
        session(client="not-a-uuid")
