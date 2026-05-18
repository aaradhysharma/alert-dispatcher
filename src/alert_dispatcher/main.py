"""
Application entrypoint.

`uvicorn alert_dispatcher.main:app ...` imports `app` from this module
and runs it. The factory pattern (`create_app()`) is just a helper so
tests / scripts can also build the app without copying setup code.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from alert_dispatcher import __version__
from alert_dispatcher.api.dispatch import router as dispatch_router
from alert_dispatcher.api.mute import router as mute_router
from alert_dispatcher.repositories import retry as retry_repo


# A "lifespan" runs ONCE on app startup (before yield) and ONCE on
# shutdown (after yield). We use it to make sure the SQLite retry
# table exists before any request can land. init_db() is idempotent,
# so calling it on every startup is fine.
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    retry_repo.init_db()
    yield
    # No teardown needed: SQLite connections are opened/closed per call
    # in the repository.


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alert Dispatcher",
        description="Notification fan-out service.",
        version=__version__,  # single source of truth; pyproject.toml stays locked at 0.1.0
        lifespan=lifespan,
    )
    app.include_router(dispatch_router)
    app.include_router(mute_router)
    return app


# `app` is what uvicorn imports. Created at module-import time.
app = create_app()
