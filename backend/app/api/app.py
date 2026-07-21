"""FastAPI application factory.

Run locally:

    uv run uvicorn app.api.app:app --app-dir backend --reload

``--app-dir backend`` puts the ``app`` package on the import path (mirroring the
pytest ``pythonpath`` in pyproject).
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import limiter, router
from app.core.config import get_settings


def create_app(preflight: bool = True) -> FastAPI:
    """Build the app. ``preflight`` runs a one-call key check on startup and
    aborts the server if the key is missing or rejected — pass ``False`` in
    tests that must not touch the network."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if preflight:
            from app.core.preflight import PreflightError, verify_anthropic_key

            try:
                verify_anthropic_key(get_settings())
            except PreflightError as exc:
                # Fail fast and loud: one clear line, then abort startup so the
                # server never comes up half-configured.
                print(f"FATAL: {exc}", file=sys.stderr)
                raise RuntimeError(f"Startup aborted: {exc}") from exc
        yield

    app = FastAPI(
        title="vehicle-safety-agent",
        version="0.1.0",
        description="Cited vehicle-safety briefs from US NHTSA data.",
        lifespan=lifespan,
    )
    # Wire slowapi: the limiter used by the /ask decorator must be the one on
    # app.state, and 429s need the library's handler to render properly.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return app


app = create_app()
