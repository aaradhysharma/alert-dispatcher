"""Application entrypoint.

The lifespan hook initialises the SQLite retry queue once, on app
startup, so the very first failed email send doesn't pay the schema
cost on the request path.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from alert_dispatcher.api.dispatch import router as dispatch_router
from alert_dispatcher.repositories import retry as retry_repo


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Idempotent; safe to run on every startup.
    retry_repo.init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alert Dispatcher",
        description="Notification fan-out service.",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.include_router(dispatch_router)
    return app


app = create_app()
