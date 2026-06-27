"""Teams and roster endpoints.

Read-only endpoints (GET) are open — no auth required — so the existing
video pipeline can look up rosters without a token.

Write endpoints (POST / PUT / DELETE) require a Bearer token and enforce
that the authenticated coach owns the team being modified.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_coach
from app.cv.schemas import (
    CreatePlayerRequest,
    CreateTeamRequest,
    PlayerDto,
    TeamDto,
    UpdatePlayerRequest,
)
from app.db.models.coach import Coach
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.session import get_db

router = APIRouter(prefix="/api/teams", tags=["teams"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _player_to_dto(p: Player) -> PlayerDto:
    return PlayerDto(
        player_id=p.id,
        team_id=p.team_id,
        jersey_number=p.jersey_number,
        full_name=p.full_name,
        photo_url=p.photo_url,
        birth_year=p.birth_year,
    )


def _team_to_dto(team: Team, include_players: bool = True) -> TeamDto:
    players = (
        sorted(team.players, key=lambda p: p.jersey_number)
        if include_players
        else []
    )
    return TeamDto(
        team_id=team.id,
        coach_id=team.coach_id,
        name=team.name,
        season=team.season,
        color=team.color,
        logo_url=team.logo_url,
        players=[_player_to_dto(p) for p in players],
    )


def _require_team_ownership(team_id: int, coach: Coach, db: Session) -> Team:
    """Fetch a team and verify the coach owns it. Raises 404 or 403."""
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team {team_id} not found.")
    if team.coach_id != coach.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this team.")
    return team


# ---------------------------------------------------------------------------
# Team endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=TeamDto, status_code=status.HTTP_201_CREATED)
def create_team(
    body: CreateTeamRequest,
    coach: Coach = Depends(get_current_coach),
    db: Session = Depends(get_db),
) -> TeamDto:
    """Create a new team owned by the authenticated coach."""
    team = Team(
        coach_id=coach.id,
        name=body.name,
        season=body.season,
        color=body.color,
        logo_url=body.logo_url,
    )
    db.add(team)
    try:
        db.commit()
        db.refresh(team)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a team named '{body.name}' for season {body.season}.",
        )
    return _team_to_dto(team)


@router.get("", response_model=list[TeamDto])
def list_teams(
    coach: Coach = Depends(get_current_coach),
    db: Session = Depends(get_db),
) -> list[TeamDto]:
    """List all teams owned by the authenticated coach."""
    teams = (
        db.query(Team)
        .filter(Team.coach_id == coach.id)
        .order_by(Team.id.desc())
        .all()
    )
    return [_team_to_dto(t) for t in teams]


@router.get("/{team_id}", response_model=TeamDto)
def get_team(team_id: int, db: Session = Depends(get_db)) -> TeamDto:
    """Return team metadata plus full roster. Open endpoint — no auth needed."""
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team {team_id} not found.")
    return _team_to_dto(team)


# ---------------------------------------------------------------------------
# Player endpoints
# ---------------------------------------------------------------------------

@router.get("/{team_id}/players", response_model=list[PlayerDto])
def get_team_players(team_id: int, db: Session = Depends(get_db)) -> list[PlayerDto]:
    """Return all players on a team ordered by jersey number. Open endpoint."""
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team {team_id} not found.")
    players = (
        db.query(Player)
        .filter(Player.team_id == team_id)
        .order_by(Player.jersey_number)
        .all()
    )
    return [_player_to_dto(p) for p in players]


@router.post("/{team_id}/players", response_model=PlayerDto, status_code=status.HTTP_201_CREATED)
def add_player(
    team_id: int,
    body: CreatePlayerRequest,
    coach: Coach = Depends(get_current_coach),
    db: Session = Depends(get_db),
) -> PlayerDto:
    """Add a player to a team. Requires auth; coach must own the team."""
    _require_team_ownership(team_id, coach, db)

    player = Player(
        team_id=team_id,
        jersey_number=body.jersey_number,
        full_name=body.full_name,
        photo_url=body.photo_url,
        birth_year=body.birth_year,
    )
    db.add(player)
    try:
        db.commit()
        db.refresh(player)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Jersey #{body.jersey_number} is already taken on this team.",
        )
    return _player_to_dto(player)


@router.put("/{team_id}/players/{player_id}", response_model=PlayerDto)
def update_player(
    team_id: int,
    player_id: int,
    body: UpdatePlayerRequest,
    coach: Coach = Depends(get_current_coach),
    db: Session = Depends(get_db),
) -> PlayerDto:
    """Edit a player's details. Requires auth; coach must own the team."""
    _require_team_ownership(team_id, coach, db)

    player = db.query(Player).filter(Player.id == player_id, Player.team_id == team_id).first()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Player {player_id} not found on team {team_id}.")

    if body.jersey_number is not None:
        player.jersey_number = body.jersey_number
    if body.full_name is not None:
        player.full_name = body.full_name
    if body.photo_url is not None:
        player.photo_url = body.photo_url
    if body.birth_year is not None:
        player.birth_year = body.birth_year

    try:
        db.commit()
        db.refresh(player)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Jersey #{body.jersey_number} is already taken on this team.",
        )
    return _player_to_dto(player)


@router.delete("/{team_id}/players/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_player(
    team_id: int,
    player_id: int,
    coach: Coach = Depends(get_current_coach),
    db: Session = Depends(get_db),
) -> None:
    """Remove a player from a team. Requires auth; coach must own the team."""
    _require_team_ownership(team_id, coach, db)

    player = db.query(Player).filter(Player.id == player_id, Player.team_id == team_id).first()
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Player {player_id} not found on team {team_id}.")

    db.delete(player)
    db.commit()
