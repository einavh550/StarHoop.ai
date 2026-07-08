# StarHoop.ai Database Schema - Milestone 1

## Entity-Relationship Diagram (Text Format)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STARHOOP.AI - DATABASE SCHEMA                       │
└─────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────┐
│          COACHES               │
├────────────────────────────────┤
│ PK  id            BIGINT       │
│     full_name     VARCHAR(120) │
│ UQ  email         VARCHAR(255) │◄──────┐
│     created_at    TIMESTAMPTZ  │       │
└────────────────────────────────┘       │
                                          │ coach_id (FK, CASCADE)
                                          │
┌────────────────────────────────┐       │
│           TEAMS                │───────┘
├────────────────────────────────┤
│ PK  id            BIGINT       │
│ FK  coach_id      BIGINT       │
│     name          VARCHAR(120) │
│     logo_url      VARCHAR(1024)│
│     season        VARCHAR(20)  │◄──────┐
│     created_at    TIMESTAMPTZ  │       │
├────────────────────────────────┤       │
│ UQ (coach_id, name, season)    │       │
└────────────────────────────────┘       │ team_id (FK, CASCADE)
                                          │
┌────────────────────────────────┐       │
│          PLAYERS               │───────┘
├────────────────────────────────┤
│ PK  id            BIGINT       │
│ FK  team_id       BIGINT       │
│     full_name     VARCHAR(120) │
│     jersey_number INTEGER      │◄──────┐
│     photo_url     VARCHAR(1024)│       │
│     birth_year    INTEGER      │       │
│     created_at    TIMESTAMPTZ  │       │
├────────────────────────────────┤       │
│ UQ (team_id, jersey_number)    │       │
│ CK jersey_number >= 0 AND <= 99│       │ player_id (FK, CASCADE)
└────────────────────────────────┘       │
                                          │
┌────────────────────────────────┐       │
│         HIGHLIGHTS             │───────┘
├────────────────────────────────┤
│ PK  id                 BIGINT  │
│ FK  player_id          BIGINT  │
│     video_url          VARCHAR(1024)
│     event_type         VARCHAR(60)
│     event_timestamp_sec NUMERIC(10,3)
│     source_video_id    VARCHAR(255)
│     captured_at        TIMESTAMPTZ
│     created_at         TIMESTAMPTZ
├────────────────────────────────┤
│ CK event_timestamp_sec >= 0    │
└────────────────────────────────┘


## Indexes

┌────────────────────────────────────────────────────────────────┐
│  INDEX NAME                           │  TABLE     │  COLUMNS   │
├───────────────────────────────────────┼────────────┼────────────┤
│  ix_coaches_email                     │  coaches   │  email     │
│  ix_teams_coach_id                    │  teams     │  coach_id  │
│  ix_players_team_id                   │  players   │  team_id   │
│  ix_players_team_id_jersey_number     │  players   │  (team_id, jersey_number)
│  ix_highlights_player_id              │  highlights│  player_id │
│  ix_highlights_player_id_captured_at  │  highlights│  (player_id, captured_at)
└────────────────────────────────────────────────────────────────┘


## Cascading Delete Behavior

coach deleted → all teams deleted → all players deleted → all highlights deleted
team deleted  → all players deleted → all highlights deleted
player deleted → all highlights deleted


## Key Business Rules (Enforced by Constraints)

1. ✅ Each coach must have a unique email address
2. ✅ A coach cannot have two teams with the same name in the same season
3. ✅ Jersey numbers must be 0-99 (youth basketball standard)
4. ✅ No two players on the same team can have the same jersey number
5. ✅ Event timestamps must be non-negative (seconds from video start)
6. ✅ All child records are deleted when parent is deleted (CASCADE)


## Sample Data Flow (Future Milestones)

1. Coach signs up → creates entry in `coaches` table
2. Coach creates team for season → entry in `teams` table
3. Coach adds players with jersey numbers → entries in `players` table
4. Coach uploads game video → processed by CV pipeline (M2-M5)
5. System detects scoring events → OCR identifies jersey number (M3)
6. System generates highlight clip → entry in `highlights` table with video_url
7. Parent receives notification → downloads highlight from Firebase storage


## Migration Version

Current: **20260224_000001** (initial schema)
Status: ✅ Ready to apply with `alembic upgrade head`


## Files Reference

- DDL (reference):    `src/app/db/schema.sql`
- SQLAlchemy models:  `src/app/db/models/` (coach.py, team.py, player.py, highlight.py)
- Alembic migration:  `alembic/versions/20260224_000001_init_schema.py`
- Integration tests:  `tests/integration/test_schema_integrity.py`
```
