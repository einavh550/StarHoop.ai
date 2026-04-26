from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.videos import router as videos_router


def create_app() -> FastAPI:
    app = FastAPI(title="StarHoop.ai API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(videos_router)
    return app


app = create_app()
