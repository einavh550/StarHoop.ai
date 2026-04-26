from sqlalchemy import inspect

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


def test_config_loads_database_urls() -> None:
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.test_database_url.startswith("postgresql+psycopg://")


def test_engine_initializes() -> None:
    assert engine is not None
    assert str(engine.url).startswith("postgresql+psycopg://")


def test_models_metadata_contains_expected_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert {"coaches", "teams", "players", "highlights", "video_jobs", "detection_frames"}.issubset(table_names)


def test_expected_constraints_exist() -> None:
    players = Base.metadata.tables["players"]
    highlights = Base.metadata.tables["highlights"]
    teams = Base.metadata.tables["teams"]

    player_checks = {constraint.name for constraint in players.constraints if constraint.name}
    highlight_checks = {constraint.name for constraint in highlights.constraints if constraint.name}
    team_uniques = {constraint.name for constraint in teams.constraints if constraint.name}

    assert "ck_players_jersey_range" in player_checks
    assert "ck_highlights_event_timestamp_non_negative" in highlight_checks
    assert "uq_teams_coach_name_season" in team_uniques
