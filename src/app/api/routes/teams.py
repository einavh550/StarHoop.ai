"""Teams and roster endpoints for the Android client."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.cv.schemas import PlayerDto, TeamDto
from app.db.models.player import Player
from app.db.models.team import Team
from app.db.session import get_db

router = APIRouter(prefix="/api/teams", tags=["teams"])


def _player_to_dto(p: Player) -> PlayerDto:
    return PlayerDto(
        player_id=p.id,
        team_id=p.team_id,
        jersey_number=p.jersey_number,
        full_name=p.full_name,
        photo_url=p.photo_url,
        birth_year=p.birth_year,
    )


@router.get("/{team_id}/players", response_model=list[PlayerDto])
def get_team_players(team_id: int, db: Session = Depends(get_db)) -> list[PlayerDto]:
    """Return all players on a team ordered by jersey number.

    Used by the Android app to fetch the live roster instead of
    hard-coding player_id / jersey_number pairs.
    """
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found.",
        )
    players = (
        db.query(Player)
        .filter(Player.team_id == team_id)
        .order_by(Player.jersey_number)
        .all()
    )
    return [_player_to_dto(p) for p in players]


@router.get("/{team_id}", response_model=TeamDto)
def get_team(team_id: int, db: Session = Depends(get_db)) -> TeamDto:
    """Return team metadata plus full roster."""
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team {team_id} not found.",
        )
    players = (
        db.query(Player)
        .filter(Player.team_id == team_id)
        .order_by(Player.jersey_number)
        .all()
    )
    return TeamDto(
        team_id=team.id,
        name=team.name,
        season=team.season,
        logo_url=team.logo_url,
        players=[_player_to_dto(p) for p in players],
    )
