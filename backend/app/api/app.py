"""FastAPI application factory.

Run locally:

    uv run uvicorn app.api.app:app --app-dir backend --reload

``--app-dir backend`` puts the ``app`` package on the import path (mirroring the
pytest ``pythonpath`` in pyproject).
"""

from __future__ import annotations

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import limiter, router


def create_app() -> FastAPI:
    app = FastAPI(
        title="vehicle-safety-agent",
        version="0.1.0",
        description="Cited vehicle-safety briefs from US NHTSA data.",
    )
    # Wire slowapi: the limiter used by the /ask decorator must be the one on
    # app.state, and 429s need the library's handler to render properly.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    return app


app = create_app()
