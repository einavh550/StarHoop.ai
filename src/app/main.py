from fastapi import FastAPI

from app.api.routes.exports import router as exports_router
from app.api.routes.highlights import router as highlights_router
from app.api.routes.mapping_diagnostics import router as mapping_diagnostics_router
from app.api.routes.actions import router as actions_router
from app.api.routes.health import router as health_router
from app.api.routes.player_mapping import router as player_mapping_router
from app.api.routes.videos import router as videos_router


def create_app() -> FastAPI:
    app = FastAPI(title="StarHoop.ai API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(videos_router)
    app.include_router(player_mapping_router)
    app.include_router(mapping_diagnostics_router)
    app.include_router(exports_router)
    app.include_router(actions_router)
    app.include_router(highlights_router)
    return app


app = create_app()
