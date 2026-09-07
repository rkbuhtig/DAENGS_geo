import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.features.territory.game.local_store import LocalGameStore
from app.features.territory.game.season import DAY_MS, Game, GameError
from app.features.territory.game.season_lab import build_app


def seed(store):
    g = Game.create("s", 0, DAY_MS, {"p1": "보리", "p2": "두부"}, ["A", "B"])
    store.create(g)
    store.execute("s", "start1", {"action": "start_session", "session_id": "w1", "pet_ids": ["p1"]})
    store.execute("s", "start2", {"action": "start_session", "session_id": "w2", "pet_ids": ["p2"]})
    return g


def mark(pet="p1", session="w1", attempt="a1"):
    return {
        "action": "mark",
        "pet_id": pet,
        "session_id": session,
        "attempt_id": attempt,
        "site_id": "A",
    }


def test_restart_receipts_and_conflicting_retries(tmp_path):
    path = tmp_path / "game.sqlite3"
    store = LocalGameStore(path)
    seed(store)
    result = store.execute("s", "r1", mark())
    restarted = LocalGameStore(path)
    assert restarted.execute("s", "r1", mark()) == result
    restarted.execute("s", "advance", {"action": "advance", "delta_ms": 3_600_000})
    retry = restarted.execute("s", "r1", mark())
    assert retry["result"] == result["result"]
    assert retry["game"]["standings"][0]["points"] == 110
    with pytest.raises(GameError, match="request_identity_conflict"):
        restarted.execute("s", "r1", mark(attempt="a2"))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_storage_failure_rolls_back_owner_scores_events_and_receipt(tmp_path):
    path = tmp_path / "game.sqlite3"
    store = LocalGameStore(path)
    seed(store)
    before = store.read("s")

    class BrokenStore(LocalGameStore):
        @staticmethod
        def _save(*args):
            LocalGameStore._save(*args)
            raise RuntimeError("injected failure after all writes")

    with pytest.raises(RuntimeError, match="injected"):
        BrokenStore(path).execute("s", "r1", mark())
    assert store.read("s") == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM commands WHERE request_id = 'r1'").fetchone()[0] == 0
        )
    assert store.execute("s", "r1", mark())["game"]["standings"][0]["bonus"] == 100


def test_concurrent_ownership_requests_and_duplicate_delivery(tmp_path):
    path = tmp_path / "game.sqlite3"
    store = LocalGameStore(path)
    seed(store)

    def submit(args):
        request, command = args
        try:
            return LocalGameStore(path).execute("s", request, command)["result"]["disposition"]
        except GameError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, [("r1", mark())] * 4))
    assert results == ["GRANTED"] * 4
    # An opposing dog cannot enter the new owner's ten-minute protection window.
    assert submit(("r2", mark("p2", "w2", "a2"))) == "protected"
    assert len(store.read("s")["events"]) == 1


def test_two_rival_marks_are_serialized_with_one_bonus(tmp_path):
    path = tmp_path / "game.sqlite3"
    store = LocalGameStore(path)
    seed(store)

    # Both dogs request a neutral site through serialized mark; the first wins immediately.
    def compete(index):
        try:
            return LocalGameStore(path).execute(
                "s", f"r{index}", mark(f"p{index}", f"w{index}", f"a{index}")
            )["result"]
        except GameError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, [1, 2]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(r["bonus"] for r in store.read("s")["standings"]) == 100


def test_season_rollover_preserves_result_and_isolates_old_requests(tmp_path):
    store = LocalGameStore(tmp_path / "game.sqlite3")
    initial = seed(store)
    store.execute("s", "r1", mark())
    final = store.execute("s", "end", {"action": "finalize"})["game"]
    assert store.execute("s", "end", {"action": "finalize"})["game"] == final
    next_game = Game.create("s2", DAY_MS, 2 * DAY_MS, initial.pets, list(initial.sites))
    store.create(next_game)
    assert store.read("s2")["standings"][0]["points"] == 0
    assert store.read("s2")["sites"]["A"]["owner"] is None
    assert store.read("s") == final
    with pytest.raises(GameError, match="season_ended"):
        store.execute("s", "late", {"action": "submit", "attempt_id": "a1", "capture_id": "c1"})
    # Idempotent creation returns the existing final state, never overwriting it.
    assert store.create(initial) == final
    assert store.read("s2")["events"] == []


def test_local_schema_initialization_is_repeatable_and_future_versions_fail(tmp_path):
    path = tmp_path / "game.sqlite3"
    store = LocalGameStore(path)
    seed(store)
    with sqlite3.connect(path) as db:
        sql = Path(__file__).resolve().parents[2] / ("app/features/territory/game/local_schema.sql")
        db.executescript(sql.read_text("utf-8"))
        assert json.loads(db.execute("SELECT state FROM seasons").fetchone()[0])["season_id"] == "s"
        db.execute("PRAGMA user_version=999")
    with pytest.raises(GameError, match="unsupported_local_schema"):
        store.read("s")


def test_http_lab_contract_static_assets_and_validation(tmp_path):
    path = tmp_path / "lab.sqlite3"
    app = build_app(path)
    assert not path.exists()  # Composition/import has no database side effects.
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/lab.mjs").status_code == 200
        assert client.get("/api/seasons").json() == []
        assert (
            client.post("/api/seasons", json={"season_id": "s", "starts_ms": 0}).status_code == 201
        )
        assert (
            client.post("/api/seasons", json={"season_id": "s2", "starts_ms": 0}).status_code == 409
        )
        for command in [
            {"action": "advance", "delta_ms": -1},
            {"action": "advance", "delta_ms": 1.1},
            {"action": "finalize", "injected": True},
        ]:
            response = client.post(
                "/api/seasons/s/commands", json={"request_id": "bad", "command": command}
            )
            assert response.status_code == 422
        response = client.post(
            "/api/seasons/s/commands",
            json={
                "request_id": "r1",
                "command": {"action": "start_session", "session_id": "w1", "pet_ids": ["p1"]},
            },
        )
        assert response.status_code == 200
        response = client.post(
            "/api/seasons/s/commands", json={"request_id": "r2", "command": mark()}
        )
        assert response.status_code == 200
        assert response.json()["game"]["standings"][0]["points"] == 100
        assert client.get("/api/seasons/s").json()["sites"]["A"]["protected_until_ms"] == 600_000


def test_lab_is_absent_from_the_common_entrypoint():
    # Common API never mounts labs; explicit local runners own them.
    from app.main import app

    assert not any(getattr(route, "path", "") == "/territory-season-lab" for route in app.routes)


def test_concurrent_photo_callbacks_preserve_losing_evidence(tmp_path):
    path = tmp_path / "game.sqlite3"
    store = LocalGameStore(path)
    store.create(Game.create("s", 0, DAY_MS, {"p1": "보리", "p2": "두부", "p3": "콩이"}, ["A"]))
    for i in range(1, 4):
        store.execute(
            "s",
            f"start{i}",
            {"action": "start_session", "session_id": f"w{i}", "pet_ids": [f"p{i}"]},
        )
    store.execute("s", "mark1", mark())
    store.execute("s", "time", {"action": "advance", "delta_ms": 600_000})
    for i in [2, 3]:
        store.execute("s", f"mark{i}", mark(f"p{i}", f"w{i}", f"a{i}"))
        store.execute(
            "s", f"submit{i}", {"action": "submit", "attempt_id": f"a{i}", "capture_id": f"c{i}"}
        )

    def resolve(i):
        return LocalGameStore(path).execute(
            "s",
            f"resolve{i}",
            {
                "action": "resolve",
                "attempt_id": f"a{i}",
                "capture_id": f"c{i}",
                "outcome": "ACCEPTED",
            },
        )["result"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve, [2, 3]))
    assert {r["resolution_code"] for r in results} == {None, "site_changed"}
    assert all(r["photo"] == "VERIFIED" for r in results)
    snapshot = store.read("s")
    assert sum(r["bonus"] for r in snapshot["standings"]) == 200
    assert len([e for e in snapshot["events"] if e["kind"] == "OWNERSHIP_CHANGED"]) == 2
