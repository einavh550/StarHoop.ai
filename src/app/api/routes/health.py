import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
def health_check(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/runtime-config")
def runtime_config() -> dict[str, str | bool]:
    return {
        "cwd": os.getcwd(),
        "app_env": settings.app_env,
        "enable_modal_orchestration": settings.enable_modal_orchestration,
        "webhook_base_url": settings.webhook_base_url,
    }
