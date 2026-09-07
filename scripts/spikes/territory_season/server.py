"""Run the durable, synthetic game lab without the main app's PostGIS configuration."""

import argparse
from pathlib import Path


def main():
    import uvicorn

    from tools.territory_game.season_lab import build_app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".local/territory-season.sqlite3"))
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    uvicorn.run(build_app(args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
