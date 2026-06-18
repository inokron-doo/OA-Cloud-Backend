from fastapi import FastAPI

from app.routers import health, predictions, settings


def create_app() -> FastAPI:
    app = FastAPI(title="Prediction Service")
    app.include_router(health.router)
    app.include_router(predictions.router, tags=["predictions"])
    app.include_router(settings.router, tags=["settings"])
    return app


app = create_app()
