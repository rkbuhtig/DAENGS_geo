"""Compare repeated takeovers and long holds using the lab's actual Python kernel.

uv run python -m scripts.spikes.territory_season.simulate --hours 6
Prints JSON only; no database, external provider or file writes.
"""

import argparse
import json

from app.features.territory.game.season import DAY_MS, HOUR_MS, Game, Rules


def simulate(hours: int, repeat_bonus: str, strategy: str):
    game = Game.create(
        "comparison",
        0,
        max(DAY_MS, hours * HOUR_MS + 1),
        {"p1": "보리", "p2": "두부"},
        ["A", "B", "C"],
        Rules(repeat_bonus=repeat_bonus),
    )

    def apply(action, at, **values):
        nonlocal game
        game, _ = game.transition({"action": action, **values}, at_ms=at)

    steps = hours * 6 if strategy == "ping_pong" else 1
    for index in range(steps):
        at = index * 600_000
        pet, sid = f"p{index % 2 + 1}", f"walk{index}"
        apply("start_session", at, session_id=sid, pet_ids=[pet])
        for site in ["A", "B", "C"] if strategy == "hold_three" else ["A"]:
            aid = f"{sid}_{site}"
            apply("mark", at, session_id=sid, pet_id=pet, site_id=site, attempt_id=aid)
            apply("submit", at, attempt_id=aid, capture_id=aid)
            apply("resolve", at, attempt_id=aid, capture_id=aid, outcome="ACCEPTED")
    apply("advance", hours * HOUR_MS)
    return {
        "strategy": strategy,
        "repeat_bonus": repeat_bonus,
        "hours": hours,
        "rules": game.view()["rules"],
        "standings": game.standings(),
        "ownership_changes": sum(e["kind"] == "OWNERSHIP_CHANGED" for e in game.events),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, choices=range(1, 169), default=6)
    args = parser.parse_args()
    print(
        json.dumps(
            [
                simulate(args.hours, policy, strategy)
                for policy in ["every_change", "daily_pet_site"]
                for strategy in ["hold_one", "hold_three", "ping_pong"]
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
