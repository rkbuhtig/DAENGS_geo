"""New seasons use certification priority; stored legacy rules remain immutable."""

import pytest

from app.features.territory_game.policy import GameError, Rules
from tests.territory_game.test_season_game import act, certify, game, mark, standing, start


def test_unverified_can_be_stolen_immediately_then_same_walk_can_retake():
    g = mark(start(game(Rules())))
    assert g.view()["sites"]["A"]["protected_until_ms"] is None
    g = mark(start(g, "s2", ["p2"]), "s2", "p2", aid="a2", at=1)
    g = certify(g, "a2", "c2")
    assert g.view()["sites"]["A"]["protected_until_ms"] == 600001
    with pytest.raises(GameError, match="protected"):
        act(g, "submit", attempt_id="a1", capture_id="c3", at=600000)
    g = act(g, "advance", at=600001)
    g = certify(g, "a1", "c3")
    assert g.sites["A"]["owner"]["pet_id"] == "p1"
    assert standing(g)["bonus"] == 200


def test_upgrade_starts_clock_at_certification_and_cannot_extend_it():
    g = mark(start(game(Rules())))
    g = certify(g, at=120000)
    assert g.sites["A"]["owner"]["occupied_ms"] == 0
    assert g.sites["A"]["owner"]["certified_ms"] == 120000
    assert g.view()["sites"]["A"]["protected_until_ms"] == 720000
    assert standing(g)["bonus"] == 100
    with pytest.raises(GameError, match="already_certified"):
        act(g, "submit", attempt_id="a1", capture_id="renew", at=720000)


def test_new_capture_recovers_race_without_reusing_old_evidence():
    g = mark(start(game(Rules())))
    g = mark(start(g, "s2", ["p2"]), "s2", "p2", aid="a2")
    g = act(g, "submit", attempt_id="a1", capture_id="losing")
    g = certify(g, "a2", "winning")
    g = act(g, "resolve", attempt_id="a1", capture_id="losing", outcome="ACCEPTED")
    assert g.attempts["a1"]["resolution_code"] == "site_changed"
    g = act(g, "advance", at=600000)
    g = certify(g, "a1", "retry")
    assert g.attempts["a1"]["resolution_code"] is None
    with pytest.raises(GameError, match="stale_capture"):
        act(g, "resolve", attempt_id="a1", capture_id="losing", outcome="ACCEPTED")


def test_unknown_rule_version_cannot_silently_select_legacy_policy():
    with pytest.raises(GameError, match="unsupported_policy_version"):
        Rules(version="typo")
