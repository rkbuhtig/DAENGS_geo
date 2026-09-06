"""Behavioral contracts for the same kernel used by the durable local lab."""

import csv
from pathlib import Path

import pytest

from app.features.territory.game.season import (
    DAY_MS,
    HOUR_MS,
    POINT_DENOMINATOR,
    Game,
    GameError,
    Rules,
)


def game(rules=None):
    return Game.create(
        "season", 0, 7 * DAY_MS, {"p1": "보리", "p2": "두부", "p3": "콩이"}, ["A", "B", "C"], rules
    )


def act(g, action, at=None, **values):
    return g.transition({"action": action, **values}, at_ms=g.now_ms if at is None else at)[0]


def start(g, sid="s1", pets=None):
    return act(g, "start_session", session_id=sid, pet_ids=pets or ["p1"])


def mark(g, sid="s1", pet="p1", site="A", aid="a1", at=None, **contact):
    return act(
        g, "mark", at=at, session_id=sid, pet_id=pet, site_id=site, attempt_id=aid, **contact
    )


def certify(g, aid="a1", capture="c1", at=None):
    g = act(g, "submit", attempt_id=aid, capture_id=capture)
    return act(g, "resolve", at=at, attempt_id=aid, capture_id=capture, outcome="ACCEPTED")


def standing(g, pet="p1"):
    return next(s for s in g.view()["standings"] if s["pet_id"] == pet)


def test_ten_minute_boundary_and_strengthening_preserves_acquisition():
    original = start(game())
    g = mark(original)
    assert original.sites["A"]["owner"] is None
    g = certify(g, at=120_000)
    assert g.sites["A"]["owner"]["occupied_ms"] == 0
    assert standing(g)["bonus"] == 100
    assert standing(g)["claims"] == 1
    g = start(g, "s2", ["p2"])
    before = g.serialize()
    with pytest.raises(GameError, match="protected"):
        mark(g, "s2", "p2", aid="a2", at=599_999)
    assert before == g.serialize()
    g = mark(g, "s2", "p2", aid="a2", at=600_000)
    g = certify(g, "a2", "c2")
    assert g.sites["A"]["owner"]["pet_id"] == "p2"
    assert g.view()["sites"]["A"]["protected_until_ms"] == 1_200_000
    assert standing(g, "p2")["takeovers"] == 1


def test_query_frequency_and_time_splitting_do_not_change_exact_score():
    g = mark(start(game()))
    single = act(g, "advance", at=HOUR_MS)
    split = g
    for t in [1, 17, 321, 12345, 871234, HOUR_MS]:
        split = act(split, "advance", at=t)
        for _ in range(3):
            split.view()
    assert single.serialize() == split.serialize()
    assert standing(single)["points"] == 110
    assert standing(single)["total_units"] == str(110 * POINT_DENOMINATOR)


def test_both_dogs_settle_using_old_counts_on_takeover():
    g = mark(start(game()))
    g = mark(g, site="B", aid="b1", at=HOUR_MS)
    g = start(g, "s2", ["p2"])
    g = mark(g, "s2", "p2", aid="a2", at=2 * HOUR_MS)
    g = certify(g, "a2", "c2")
    g = act(g, "advance", at=3 * HOUR_MS)
    assert standing(g)["holding_points"] == 42  # 1h*10 + 1h*2*11 + 1h*10
    assert standing(g, "p2")["holding_points"] == 10
    assert standing(g)["peak"] == 2
    assert standing(g)["held_site_ms"] == 4 * HOUR_MS


def test_same_pet_new_session_certification_never_pays_or_restarts_protection():
    g = mark(start(game()))
    g = start(g, "s2")
    g = mark(g, "s2", aid="a2", at=50_000)
    g = certify(g, "a2", "c2")
    assert g.sites["A"]["owner"]["attempt_id"] == "a1"
    assert g.sites["A"]["owner"]["occupied_ms"] == 0
    assert standing(g)["bonus"] == 100


def test_one_site_attempt_per_session_including_participant_switch():
    g = start(game(), pets=["p1", "p2"])
    g = mark(g)
    repeated = mark(g, aid="unused")
    assert repeated.serialize() == g.serialize()
    with pytest.raises(GameError, match="attempt_identity_conflict"):
        mark(g, pet="p2", aid="other")
    with pytest.raises(GameError, match="session_identity_conflict"):
        start(g, pets=["p2"])


@pytest.mark.parametrize(
    "contact,code",
    [
        ({"distance_m": 16, "accuracy_m": 5}, "site_not_ready"),
        ({"trusted": False}, "untrusted_contact"),
        ({"contact_age_ms": 30_001}, "untrusted_contact"),
        ({"accuracy_m": float("nan")}, "invalid_contact"),
        ({"distance_m": -1}, "invalid_contact"),
    ],
)
def test_contact_rejected_without_consuming_attempt(contact, code):
    g = start(game())
    with pytest.raises(GameError, match=code):
        mark(g, **contact)
    assert not g.attempts


def test_photo_retries_unique_capture_and_late_callback():
    g = mark(start(game()))
    g = act(g, "submit", attempt_id="a1", capture_id="c1")
    g = act(g, "resolve", attempt_id="a1", capture_id="c1", outcome="REJECTED")
    g = act(g, "submit", attempt_id="a1", capture_id="c2")
    with pytest.raises(GameError, match="stale_capture"):
        act(g, "resolve", attempt_id="a1", capture_id="c1", outcome="ACCEPTED")
    g = act(g, "resolve", attempt_id="a1", capture_id="c2", outcome="RETRYABLE_FAILURE")
    g = act(g, "phase", session_id="s1", phase="ENDED")
    g = act(g, "submit", attempt_id="a1", capture_id="c2")
    g = act(g, "resolve", attempt_id="a1", capture_id="c2", outcome="ACCEPTED")
    duplicate = act(g, "resolve", attempt_id="a1", capture_id="c2", outcome="ACCEPTED")
    assert duplicate.serialize() == g.serialize()
    g = start(g, "s2")
    g = mark(g, "s2", site="B", aid="b1")
    with pytest.raises(GameError, match="capture_reused"):
        act(g, "submit", attempt_id="b1", capture_id="c1")


def test_pending_rivals_first_committed_photo_wins_without_retroactive_credit():
    g = certify(mark(start(game())))
    g = start(g, "s2", ["p2"])
    g = start(g, "s3", ["p3"])
    g = mark(g, "s2", "p2", aid="a2", at=600_000)
    g = mark(g, "s3", "p3", aid="a3")
    g = act(g, "submit", attempt_id="a2", capture_id="c2")
    g = act(g, "submit", attempt_id="a3", capture_id="c3")
    g = act(g, "resolve", at=HOUR_MS, attempt_id="a3", capture_id="c3", outcome="ACCEPTED")
    g = act(g, "resolve", attempt_id="a2", capture_id="c2", outcome="ACCEPTED")
    assert g.attempts["a2"]["photo"] == "VERIFIED"
    assert g.attempts["a2"]["resolution_code"] == "site_changed"
    assert standing(g, "p2")["bonus"] == 0
    assert standing(g, "p3")["holding_points"] == 0
    assert standing(g)["holding_points"] == 10
    assert g.sites["A"]["owner"]["pet_id"] == "p3"


def test_unverified_exclusion_starts_scoring_at_certification_only():
    g = mark(start(game(Rules(unverified_scores=False))))
    g = certify(g, at=HOUR_MS)
    g = act(g, "advance", at=2 * HOUR_MS)
    assert standing(g)["holding_points"] == 10
    assert standing(g)["held_site_ms"] == 2 * HOUR_MS


@pytest.mark.parametrize("policy,expected", [("every_change", 200), ("daily_pet_site", 100)])
def test_repeat_bonus_configuration_does_not_block_actual_takeover(policy, expected):
    g = mark(start(game(Rules(repeat_bonus=policy))))
    g = start(g, "s2", ["p2"])
    g = certify(mark(g, "s2", "p2", aid="a2", at=600_000), "a2", "c2")
    g = start(g, "s3")
    g = certify(mark(g, "s3", aid="a3", at=1_200_000), "a3", "c3")
    assert g.sites["A"]["owner"]["pet_id"] == "p1"
    assert standing(g)["claims"] == 2
    assert standing(g)["bonus"] == expected


def test_season_end_caps_accrual_seals_results_and_neutralizes_sites():
    g = mark(start(game()))
    g = act(g, "submit", attempt_id="a1", capture_id="c1")
    g = act(g, "advance", at=8 * DAY_MS)
    assert g.now_ms == 7 * DAY_MS
    assert standing(g)["points"] == 100 + 7 * 24 * 10
    assert g.results[0]["current_count"] == 1
    assert g.sites["A"]["owner"] is None
    assert g.attempts["a1"]["resolution_code"] == "season_ended"
    assert Game.restore(g.serialize()).view() == g.view()
    with pytest.raises(GameError, match="season_ended"):
        act(g, "resolve", attempt_id="a1", capture_id="c1", outcome="ACCEPTED")


def test_finalization_boundary_and_clock_reversal():
    g = act(game(), "advance", at=100)
    with pytest.raises(GameError, match="time_reversed"):
        act(g, "advance", at=99)
    with pytest.raises(GameError, match="season_not_ended"):
        act(g, "finalize")
    with pytest.raises(GameError, match="season_ended"):
        act(g, "start_session", at=g.ends_ms, session_id="s1", pet_ids=["p1"])


def test_equal_scores_share_rank_and_cap_does_not_cap_site_count():
    assert [r["rank"] for r in game().standings()] == [1, 1, 1]
    rules = Rules()
    assert rules.multiplier(11) == rules.multiplier(20) == 20_000
    with pytest.raises(GameError):
        Rules(hourly_points=-1)


def test_daily_bonus_resets_at_utc_day_boundary():
    g = mark(start(game(Rules(repeat_bonus="daily_pet_site"))))
    g = start(g, "s2", ["p2"])
    g = certify(mark(g, "s2", "p2", aid="a2", at=600_000), "a2", "c2")
    g = start(g, "s3")
    g = certify(mark(g, "s3", aid="a3", at=DAY_MS), "a3", "c3")
    assert standing(g)["bonus"] == 200


def test_view_cannot_mutate_game_or_archived_results():
    g = mark(start(game()))
    view = g.view()
    view["pets"]["p1"] = "changed"
    view["sites"]["A"]["owner"]["pet_id"] = "p2"
    assert g.pets["p1"] == "보리"
    assert g.sites["A"]["owner"]["pet_id"] == "p1"
    g = act(g, "finalize", at=g.ends_ms)
    g.view()["standings"][0]["points"] = -1
    assert g.view()["standings"][0]["points"] > 0


def test_original_shared_claim_scenarios_with_protection_time_elapsed():
    """Keep the APP/DEV shared fixture intact; only insert the new ten-minute waits."""
    fixture = Path(__file__).resolve().parents[2] / (
        "scripts/spikes/territory_production_plan/territory-claim-scenarios.tsv"
    )
    g = game()
    with fixture.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            sid, pet, site = row["session"], row["pet"], row["site"]
            aid = sid + "_" + site
            if sid not in g.sessions:
                g = start(g, sid, [pet])
            if row["action"] == "mark":
                owner = g.sites[site]["owner"]
                if owner and owner["pet_id"] != pet:
                    g = act(g, "advance", at=max(g.now_ms, owner["occupied_ms"] + 600_000))
                g = mark(g, sid, pet, site, aid)
            elif row["action"] in {"submit", "resume"}:
                g = act(g, "submit", attempt_id=aid, capture_id=row["capture"])
            else:
                g = act(
                    g, "resolve", attempt_id=aid, capture_id=row["capture"], outcome=row["outcome"]
                )
            owner, attempt = g.sites[site]["owner"], g.attempts[aid]
            assert (
                owner["pet_id"],
                owner["certification"],
                attempt["disposition"],
                attempt["photo"],
            ) == (row["owner"], row["certification"], row["disposition"], row["photo"]), row["step"]
