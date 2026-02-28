"""SQLite schema definitions and database bootstrapping."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("fpl_agent.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    id              INTEGER PRIMARY KEY,
    web_name        TEXT NOT NULL,
    first_name      TEXT,
    second_name     TEXT,
    team_id         INTEGER NOT NULL,
    element_type    INTEGER NOT NULL,       -- 1=GK 2=DEF 3=MID 4=FWD
    now_cost        INTEGER NOT NULL,       -- price × 10
    total_points    INTEGER DEFAULT 0,
    minutes         INTEGER DEFAULT 0,
    goals_scored    INTEGER DEFAULT 0,
    assists         INTEGER DEFAULT 0,
    clean_sheets    INTEGER DEFAULT 0,
    selected_by_percent REAL DEFAULT 0,
    form            REAL DEFAULT 0,
    points_per_game REAL DEFAULT 0,
    status          TEXT DEFAULT 'a',
    chance_of_playing_next_round INTEGER,
    ict_index       REAL DEFAULT 0,
    ep_this         REAL DEFAULT 0,
    ep_next         REAL DEFAULT 0,
    news            TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    short_name      TEXT NOT NULL,
    strength        INTEGER DEFAULT 0,
    strength_overall_home   INTEGER DEFAULT 0,
    strength_overall_away   INTEGER DEFAULT 0,
    strength_attack_home    INTEGER DEFAULT 0,
    strength_attack_away    INTEGER DEFAULT 0,
    strength_defence_home   INTEGER DEFAULT 0,
    strength_defence_away   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fixtures (
    id              INTEGER PRIMARY KEY,
    event           INTEGER,                -- gameweek number (NULL if unscheduled)
    team_h          INTEGER NOT NULL,
    team_a          INTEGER NOT NULL,
    team_h_difficulty INTEGER DEFAULT 0,
    team_a_difficulty INTEGER DEFAULT 0,
    finished        INTEGER DEFAULT 0,
    team_h_score    INTEGER,
    team_a_score    INTEGER,
    kickoff_time    TEXT
);

CREATE TABLE IF NOT EXISTS player_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       INTEGER NOT NULL,
    gameweek        INTEGER NOT NULL,
    opponent_team   INTEGER,
    total_points    INTEGER DEFAULT 0,
    minutes         INTEGER DEFAULT 0,
    goals_scored    INTEGER DEFAULT 0,
    assists         INTEGER DEFAULT 0,
    clean_sheets    INTEGER DEFAULT 0,
    was_home        INTEGER DEFAULT 0,
    bps             INTEGER DEFAULT 0,
    influence       REAL DEFAULT 0,
    creativity      REAL DEFAULT 0,
    threat          REAL DEFAULT 0,
    ict_index       REAL DEFAULT 0,
    value           INTEGER DEFAULT 0,
    selected        INTEGER DEFAULT 0,
    UNIQUE(player_id, gameweek)
);

CREATE TABLE IF NOT EXISTS gameweeks (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    deadline_time   TEXT,
    is_current      INTEGER DEFAULT 0,
    is_next         INTEGER DEFAULT 0,
    finished        INTEGER DEFAULT 0,
    highest_score   INTEGER,
    average_score   INTEGER
);

CREATE TABLE IF NOT EXISTS your_team (
    player_id       INTEGER PRIMARY KEY,
    selling_price   INTEGER,                -- NULL when fetched via public endpoint
    purchase_price  INTEGER,
    position        INTEGER NOT NULL,       -- squad slot 1-15
    is_captain      INTEGER DEFAULT 0,
    is_vice_captain INTEGER DEFAULT 0,
    multiplier      INTEGER DEFAULT 1       -- 0=benched
);
"""


def init_db(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Create the database file (if needed) and ensure all tables exist."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
