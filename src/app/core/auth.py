"""JWT authentication utilities and FastAPI dependency.

Usage
-----
Routes that require a logged-in coach declare:

    from app.core.auth import get_current_coach
    ...
    def my_route(coach: Coach = Depends(get_current_coach)):
        ...

Routes that are intentionally open (video upload, status, extract,
compose, download) do NOT add this dependency — they stay unauthenticated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.coach import Coach
from app.db.session import get_db

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(coach_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": str(coach_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> int:
    """Decode a JWT and return the coach_id (sub claim).

    Raises HTTP 401 on any decode error.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_current_coach(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Coach:
    """FastAPI dependency — resolves the Bearer token to a Coach row.

    Raises 401 if the token is missing/invalid/expired.
    Raises 404 if the coach no longer exists in the DB.
    """
    coach_id = _decode_token(credentials.credentials)
    coach = db.get(Coach, coach_id)
    if coach is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coach account not found.",
        )
    return coach
