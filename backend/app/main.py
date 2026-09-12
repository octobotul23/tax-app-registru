"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.ai.ollama import OllamaClient
from app.bootstrap import ensure_owner_account, run_migrations, seed_starting_rates
from app.config import settings
from app.deps import CurrentUser
from app.routers import auth, documents, rates, reports, settlements, users
from app.services.money import MissingRate
from app.services.storage import HEIC_SUPPORTED, storage_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.run_migrations_on_start:
        run_migrations()
    ensure_owner_account()
    seed_starting_rates()
    storage_root()

    if not HEIC_SUPPORTED:
        log.warning("pillow-heif is missing - iPhone HEIC uploads will be rejected")

    yield


app = FastAPI(
    title="Partner Ledger",
    description=(
        "Shared expense ledger for two business partners. Receipts are read by "
        "a vision model running on your own hardware; nothing leaves the server."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(documents.router)
app.include_router(reports.router)
app.include_router(settlements.router)
app.include_router(rates.router)


@app.exception_handler(MissingRate)
async def missing_rate_handler(_: Request, exc: MissingRate) -> JSONResponse:
    """A missing exchange rate is a setup gap, not a server fault.

    Returning 409 with the actual remedy in the message means the UI can tell
    the user what to do instead of showing a generic failure.
    """
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "missing_rate_for": exc.currency},
    )


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    """Pure liveness. Deliberately touches nothing external.

    Docker probes this every few seconds and the worker waits on it, so it must
    never block on a slow model server - otherwise a busy GPU would make the
    whole stack look unhealthy and restart it.
    """
    return {"status": "ok"}


@app.get("/api/system/status", tags=["system"])
def system_status(_: CurrentUser) -> dict[str, object]:
    """The full picture, for the Settings screen: is the AI actually usable?"""
    client = OllamaClient()
    reachable = client.health()
    model_available = False
    installed: list[str] = []

    if reachable:
        installed = client.installed_models()
        # Match "qwen2.5vl:7b" against a bare "qwen2.5vl" too, since Ollama
        # reports the tag it was pulled with.
        wanted = client.model.split(":")[0]
        model_available = any(
            name == client.model or name.split(":")[0] == wanted for name in installed
        )

    return {
        "base_currency": settings.base_currency,
        "currencies": settings.currencies,
        "heic_support": HEIC_SUPPORTED,
        "ai": {
            "reachable": reachable,
            "model": client.model,
            "model_installed": model_available,
            "installed_models": installed,
            "hint": (
                None
                if model_available
                else f"Run: docker compose exec ollama ollama pull {client.model}"
            ),
        },
    }
