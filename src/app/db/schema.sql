CREATE TABLE IF NOT EXISTS coaches (
    id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    id BIGSERIAL PRIMARY KEY,
    coach_id BIGINT NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    logo_url VARCHAR(1024),
    season VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_teams_coach_name_season UNIQUE (coach_id, name, season)
);

CREATE TABLE IF NOT EXISTS players (
    id BIGSERIAL PRIMARY KEY,
    team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    full_name VARCHAR(120) NOT NULL,
    jersey_number INTEGER NOT NULL,
    photo_url VARCHAR(1024),
    birth_year INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_players_team_jersey_number UNIQUE (team_id, jersey_number),
    CONSTRAINT ck_players_jersey_range CHECK (jersey_number >= 0 AND jersey_number <= 99)
);

CREATE TABLE IF NOT EXISTS highlights (
    id BIGSERIAL PRIMARY KEY,
    player_id BIGINT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    video_url VARCHAR(1024) NOT NULL,
    event_type VARCHAR(60) NOT NULL,
    event_timestamp_sec NUMERIC(10, 3) NOT NULL,
    source_video_id VARCHAR(255),
    captured_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_highlights_event_timestamp_non_negative CHECK (event_timestamp_sec >= 0)
);

CREATE INDEX IF NOT EXISTS ix_players_team_id_jersey_number
    ON players (team_id, jersey_number);

CREATE INDEX IF NOT EXISTS ix_highlights_player_id_captured_at
    ON highlights (player_id, captured_at);
