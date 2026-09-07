"""SQLite adapter for the local game lab; never uses DAENGS_DATABASE_URL.

One BEGIN IMMEDIATE serializes both dogs' scores, ownership, events and request receipt.
Full season snapshots keep this adapter small. DEV promotion needs relational adapters
and the existing authenticated session/photo flow, not this database or HTTP surface.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.features.territory.game.season import Game, GameError, require


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LocalGameStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            require(version in {0, 1}, "unsupported_local_schema")
            if version == 0:
                db.executescript(Path(__file__).with_name("local_schema.sql").read_text("utf-8"))
            yield db
        finally:
            db.close()

    def create(self, game: Game):
        initial = encode(game.serialize())
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                existing = db.execute(
                    "SELECT initial_state FROM seasons WHERE id = ?", (game.season_id,)
                ).fetchone()
                if existing:
                    require(existing[0] == initial, "season_identity_conflict")
                else:
                    require(
                        not db.execute("SELECT 1 FROM seasons WHERE status = 'ACTIVE'").fetchone(),
                        "active_season_exists",
                    )
                    previous = db.execute("SELECT state FROM seasons ORDER BY rowid DESC LIMIT 1")
                    last = previous.fetchone()
                    if last:
                        require(game.starts_ms >= json.loads(last[0])["ends_ms"], "season_overlap")
                    db.execute(
                        "INSERT INTO seasons(id,status,initial_state,state) VALUES (?,?,?,?)",
                        (game.season_id, game.status, initial, initial),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return self.read(game.season_id)

    @staticmethod
    def _load(db, season_id):
        row = db.execute("SELECT state FROM seasons WHERE id = ?", (season_id,)).fetchone()
        if row is None:
            raise GameError("unknown_season")
        return Game.restore(json.loads(row[0]))

    def read(self, season_id):
        with self._db() as db:
            return self._load(db, season_id).view()

    def list_seasons(self):
        with self._db() as db:
            return [
                {"season_id": row["id"], "status": row["status"]}
                for row in db.execute("SELECT id,status FROM seasons ORDER BY rowid DESC")
            ]

    def execute(self, season_id, request_id, command):
        """The lab advances an explicit clock; all other actions use its committed value."""
        fingerprint = encode(command)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                game = self._load(db, season_id)
                receipt = db.execute(
                    "SELECT command,result FROM commands WHERE season_id = ? AND request_id = ?",
                    (season_id, request_id),
                ).fetchone()
                if receipt:
                    require(receipt["command"] == fingerprint, "request_identity_conflict")
                    result = json.loads(receipt["result"])
                else:
                    at_ms = game.now_ms
                    if command["action"] == "advance":
                        delta = command["delta_ms"]
                        require(type(delta) is int and delta > 0, "invalid_time_step")
                        at_ms += delta
                    if command["action"] == "finalize":
                        at_ms = game.ends_ms
                    updated, result = game.transition(command, at_ms=at_ms)
                    self._save(db, updated, game.events, request_id, fingerprint, result)
                    game = updated
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {"result": result, "game": game.view()}

    @staticmethod
    def _save(db, game, old_events, request_id, fingerprint, result):
        db.execute(
            "UPDATE seasons SET state = ?, status = ?, revision = revision + 1 WHERE id = ?",
            (encode(game.serialize()), game.status, game.season_id),
        )
        for event in game.events[len(old_events) :]:
            db.execute(
                "INSERT INTO events(season_id,seq,body) VALUES (?,?,?)",
                (game.season_id, event["seq"], encode(event)),
            )
        db.execute(
            "INSERT INTO commands(season_id,request_id,command,result) VALUES (?,?,?,?)",
            (game.season_id, request_id, fingerprint, encode(result)),
        )
