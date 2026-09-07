"""Explicit local R&D application. Synthetic dogs/contact/photo verdicts, no authentication.

Selected by tools.lab_server, or run on loopback with the standalone lab script.
No PostGIS engine, environment credentials or external providers are loaded here.
"""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.features.territory.game.season import DAY_MS, Game, GameError, Rules
from tools.territory_game.local_store import LocalGameStore

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Balance = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BalanceInput(StrictModel):
    claim_points: Balance = 100
    takeover_points: Balance = 100
    hourly_points: Balance = 10
    extra_site_bps: Balance = 1000
    maximum_bps: Annotated[int, Field(strict=True, ge=10_000, le=1_000_000)] = 20_000
    repeat_bonus: Literal["every_change", "daily_pet_site"] = "every_change"
    unverified_scores: bool = True


class NewSeason(StrictModel):
    season_id: Identifier
    starts_ms: Annotated[int, Field(strict=True, ge=0, le=8_000_000_000_000_000)]
    duration_ms: Annotated[int, Field(strict=True, ge=600_000, le=366 * DAY_MS)] = 7 * DAY_MS
    rules: BalanceInput = Field(default_factory=BalanceInput)
    pets: dict[Identifier, Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=lambda: {"p1": "보리", "p2": "두부", "p3": "콩이"},
        min_length=1,
        max_length=20,
    )
    site_ids: list[Identifier] = Field(
        default_factory=lambda: ["A", "B", "C"], min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def unique_sites(self):
        if len(set(self.site_ids)) != len(self.site_ids):
            raise ValueError("duplicate sites")
        return self


class StartSession(StrictModel):
    action: Literal["start_session"]
    session_id: Identifier
    pet_ids: list[Identifier] = Field(min_length=1, max_length=20)


class Phase(StrictModel):
    action: Literal["phase"]
    session_id: Identifier
    phase: Literal["RECORDING", "PAUSED", "ENDED"]


class Contact(StrictModel):
    distance_m: float = Field(default=0, ge=0, le=1_000_000, allow_inf_nan=False)
    accuracy_m: float = Field(default=5, ge=0, le=1_000_000, allow_inf_nan=False)
    contact_age_ms: Annotated[int, Field(strict=True, ge=0, le=DAY_MS)] = 0
    trusted: bool = True


class Mark(Contact):
    action: Literal["mark"]
    session_id: Identifier
    pet_id: Identifier
    site_id: Identifier
    attempt_id: Identifier


class Submit(Contact):
    action: Literal["submit"]
    attempt_id: Identifier
    capture_id: Identifier


class Resolve(StrictModel):
    action: Literal["resolve"]
    attempt_id: Identifier
    capture_id: Identifier
    outcome: Literal["ACCEPTED", "REJECTED", "RETRYABLE_FAILURE"]


class Advance(StrictModel):
    action: Literal["advance"]
    delta_ms: Annotated[int, Field(strict=True, gt=0, le=366 * DAY_MS)]


class Finalize(StrictModel):
    action: Literal["finalize"]


class Envelope(StrictModel):
    request_id: Identifier
    command: Annotated[
        StartSession | Phase | Mark | Submit | Resolve | Advance | Finalize,
        Field(discriminator="action"),
    ]


def build_app(database_path: Path) -> FastAPI:
    application = FastAPI(title="댕스 시즌 게임 · 로컬 실험")
    store = LocalGameStore(database_path)
    application.state.game_store = store

    @application.exception_handler(GameError)
    async def game_error(_request: Request, exc: GameError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.get("/api/seasons")
    def seasons():
        return store.list_seasons()

    @application.post("/api/seasons", status_code=201)
    def create(body: NewSeason):
        return store.create(
            Game.create(
                body.season_id,
                body.starts_ms,
                body.starts_ms + body.duration_ms,
                body.pets,
                body.site_ids,
                Rules(**body.rules.model_dump()),
            )
        )

    @application.get("/api/seasons/{season_id}")
    def read(season_id: Identifier):
        return store.read(season_id)

    @application.post("/api/seasons/{season_id}/commands")
    def command(season_id: Identifier, body: Envelope):
        return store.execute(season_id, body.request_id, body.command.model_dump())

    assets = Path(__file__).parent / "static" / "season"
    application.mount("/", StaticFiles(directory=assets, html=True), name="territory-season-lab")
    return application


def mount(application: FastAPI, database_path: Path) -> None:
    application.mount("/territory-season-lab", build_app(database_path))
