from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.coach import Coach
from app.db.models.highlight import Highlight
from app.db.models.player import Player
from app.db.models.team import Team


def _seed_team(db_session):
    coach = Coach(full_name="Coach One", email="coach.one@example.com")
    db_session.add(coach)
    db_session.flush()

    team = Team(coach_id=coach.id, name="Star Hoopers", season="2025-2026", logo_url="https://cdn/logo.png")
    db_session.add(team)
    db_session.flush()
    return coach, team


def test_unique_jersey_number_per_team(db_session) -> None:
    _, team = _seed_team(db_session)

    db_session.add(Player(team_id=team.id, full_name="Player A", jersey_number=7))
    db_session.flush()

    db_session.add(Player(team_id=team.id, full_name="Player B", jersey_number=7))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_jersey_range_check_constraint(db_session) -> None:
    _, team = _seed_team(db_session)
    db_session.add(Player(team_id=team.id, full_name="Player OutOfRange", jersey_number=120))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_foreign_key_chain_enforced(db_session) -> None:
    db_session.add(Player(team_id=999999, full_name="Ghost Player", jersey_number=10))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_timestamp_check_constraint(db_session) -> None:
    _, team = _seed_team(db_session)
    player = Player(team_id=team.id, full_name="Player C", jersey_number=9)
    db_session.add(player)
    db_session.flush()

    db_session.add(
        Highlight(
            player_id=player.id,
            video_url="https://cdn/highlight.mp4",
            event_type="score",
            event_timestamp_sec=Decimal("-1.000"),
            captured_at=datetime.now(tz=timezone.utc),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_highlight_insert_success(db_session) -> None:
    _, team = _seed_team(db_session)
    player = Player(team_id=team.id, full_name="Player D", jersey_number=11)
    db_session.add(player)
    db_session.flush()

    highlight = Highlight(
        player_id=player.id,
        video_url="https://cdn/highlight-success.mp4",
        event_type="score",
        event_timestamp_sec=Decimal("12.350"),
        captured_at=datetime.now(tz=timezone.utc),
        source_video_id="game_001_q2",
    )

    db_session.add(highlight)
    db_session.flush()
    assert highlight.id is not None
