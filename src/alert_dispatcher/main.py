"""Application entrypoint."""

from fastapi import FastAPI

from alert_dispatcher.api.intern_monolith import router as intern_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alert Dispatcher",
        description="Prototype notification hub (interview baseline).",
        version="0.1.0",
    )
    app.include_router(intern_router)
    return app


app = create_app()
