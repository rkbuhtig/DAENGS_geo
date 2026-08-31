"""결정론적 산책 시나리오를 만들고 기존 canonical 계산까지 관통한다.

    uv run python -m scripts.sim.walk.cli \
      --behavior exploratory --route s-curve --length-m 600 --seed 48123 \
      --chain-break-m 360 --out C:/dev/walk-sim/exploratory-48123
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.sim.walk.bundle import build_scenario, write_scenario


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--behavior",
        choices=("steady", "exploratory", "fatigued", "stop-heavy"),
        default="exploratory",
    )
    parser.add_argument(
        "--route", choices=("straight", "s-curve", "loop", "out-and-back"),
        default="s-curve",
    )
    parser.add_argument("--length-m", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=48123)
    parser.add_argument("--sample-interval-s", type=float, default=5.0)
    parser.add_argument("--chain-break-m", type=float, action="append", default=[])
    parser.add_argument("--session-id")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        artifacts = build_scenario(
            behavior_name=args.behavior,
            route_name=args.route,
            length_m=args.length_m,
            seed=args.seed,
            sample_interval_s=args.sample_interval_s,
            chain_breaks_m=tuple(sorted(args.chain_break_m)),
            session_id=args.session_id,
        )
        write_scenario(args.out.resolve(), artifacts)
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))

    facts = artifacts.computed.facts
    print(
        f"{args.behavior} × {args.route} · seed {args.seed} · "
        f"fix {facts.fix_count} · {facts.duration_s}s · {facts.moving_distance_m}m · "
        f"stop {facts.stop_count} · accepted {artifacts.derived['accepted_segment_s']:.1f}s"
    )
    print(f"written to {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
