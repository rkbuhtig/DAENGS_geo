"""Recorded Place UI, without importing shared settings or database providers."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount(application: FastAPI) -> None:
    application.mount(
        "/place-ui-lab", StaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="place-ui-lab",
    )
