"""Coach registration, login, and profile endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, get_current_coach, hash_password, verify_password
from app.cv.schemas import CoachProfileResponse, LoginRequest, RegisterRequest, TokenResponse
from app.db.models.coach import Coach
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Create a new coach account and return an auth token.

    Returns 409 if the email is already registered.
    """
    coach = Coach(
        full_name=body.display_name,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
    )
    db.add(coach)
    try:
        db.commit()
        db.refresh(coach)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    token = create_access_token(coach.id)
    return TokenResponse(
        access_token=token,
        coach_id=coach.id,
        display_name=coach.full_name,
        email=coach.email,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate with email + password and return an auth token.

    Returns 401 on wrong credentials (deliberately vague to prevent
    user enumeration).
    """
    coach = db.query(Coach).filter(Coach.email == body.email.lower()).first()
    if coach is None or not verify_password(body.password, coach.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(coach.id)
    return TokenResponse(
        access_token=token,
        coach_id=coach.id,
        display_name=coach.full_name,
        email=coach.email,
    )


@router.get("/me", response_model=CoachProfileResponse)
def me(coach: Coach = Depends(get_current_coach)) -> CoachProfileResponse:
    """Return the profile of the currently authenticated coach."""
    return CoachProfileResponse(
        coach_id=coach.id,
        display_name=coach.full_name,
        email=coach.email,
        created_at=coach.created_at,
    )
