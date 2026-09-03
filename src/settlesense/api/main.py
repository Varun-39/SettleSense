"""FastAPI application.

    uvicorn settlesense.api.main:app --reload

This layer only serves what the deterministic engine already computed. It
performs no matching and no money arithmetic of its own.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from settlesense import __version__
from settlesense.ai.client import AIClient
from settlesense.api import fixtures
from settlesense.api.deps import get_settings
from settlesense.api.routes import ai as ai_routes, results, runs
from settlesense.recon.engine import ENGINE_VERSION, RULES_VERSION

app = FastAPI(
    title="SettleSense",
    version=__version__,
    description=(
        "Evidence-first settlement reconciliation. Deterministic code "
        "calculates and controls; nothing here recomputes finance."
    ),
)

# The dashboard is served separately in development, and Vite picks the next
# free port when 5173 is taken — so match any loopback port rather than
# pinning one. Credentials stay off, and a deployment should replace this with
# an explicit origin list.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router)
app.include_router(results.router)
app.include_router(ai_routes.router)


@app.get("/fixtures", tags=["meta"])
def list_fixtures() -> list[dict]:
    """Batches a client may reconcile by name. Names, never paths."""
    return fixtures.listing()


@app.get("/health", tags=["meta"])
def health() -> dict:
    client = AIClient(get_settings().config().ai)
    return {
        "status": "ok",
        "version": __version__,
        "engine_version": ENGINE_VERSION,
        "rules_version": RULES_VERSION,
        # Reported honestly, and never load-bearing: every total on every
        # screen is identical whether this is true or false (ADR-001).
        "ai_enabled": client.available(),
        "ai_unavailable_reason": client.unavailable_reason(),
    }
