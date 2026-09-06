"""Run from geo: uv run python -m scripts.spikes.diary_storyboard --help."""

import argparse
from pathlib import Path

from .contracts import Edit
from .provider import Provider
from .runner import build, decide, initialize, load, review
from .storage import read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "advance", "review", "decide"):
        sub = commands.add_parser(command)
        sub.add_argument("--run", type=Path, required=True)
        if command in ("start", "advance", "decide"):
            sub.add_argument("--env-file", type=Path)
            sub.add_argument("--replay-from", type=Path)
        if command == "start":
            sub.add_argument(
                "--input", type=Path, default=Path(__file__).parent / "fixtures" / "scenario.json"
            )
            sub.add_argument("--model", default="gemini-3.1-flash-lite")
        if command in ("review", "decide"):
            sub.add_argument("--expected-revision", type=int, required=True)
        if command == "review":
            sub.add_argument("--actor", choices=["human", "simulated"], required=True)
            sub.add_argument("--reviewer", required=True)
            sub.add_argument("--edits", type=Path, help="JSON array of scene edits")
        if command == "decide":
            sub.add_argument("--choice", choices=["skip", "generate"], required=True)
    args = parser.parse_args()
    if args.command == "start":
        initialize(args.run, read(args.input), args.model)
    if args.command == "review":
        edits = [Edit.model_validate(e) for e in read(args.edits)] if args.edits else []
        result = review(args.run, args.expected_revision, args.actor, args.reviewer, edits)
        print(f"{result.status}: revision={result.revision}")
        return
    config, _, _ = load(args.run)
    provider = Provider(args.run, config["model"], args.env_file, args.replay_from)
    if args.command == "decide":
        result = decide(args.run, args.expected_revision, args.choice, provider)
        print(f"{result['status']}: reviewed revision={args.expected_revision}")
    else:
        state = build(args.run, provider)
        print(f"{state.status}: revision={state.revision}; no diary generated")


if __name__ == "__main__":
    main()
