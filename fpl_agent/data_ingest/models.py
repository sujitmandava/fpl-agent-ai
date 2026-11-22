"""SQLite schema definitions and database bootstrapping."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("fpl_agent.db")

# Bump whenever the schema changes: an older database is wiped and rebuilt
# (all data here is re-fetchable from the FPL API).
SCHEMA_VERSION = "3"

# Tables holding season data.  Cleared on schema change or season rollover.
DATA_TABLES = ("players", "teams", "fixtures", "player_history", "gameweeks", "your_team")

META_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

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
    started         INTEGER DEFAULT 0,
    finished        INTEGER DEFAULT 0,
    finished_provisional INTEGER DEFAULT 0,
    team_h_score    INTEGER,
    team_a_score    INTEGER,
    kickoff_time    TEXT
);

-- One row per player per *fixture* (a double gameweek has two rows).
CREATE TABLE IF NOT EXISTS player_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       INTEGER NOT NULL,
    fixture         INTEGER NOT NULL,
    gameweek        INTEGER NOT NULL,
    opponent_team   INTEGER,
    total_points    INTEGER DEFAULT 0,
    minutes         INTEGER DEFAULT 0,
    starts          INTEGER DEFAULT 0,
    goals_scored    INTEGER DEFAULT 0,
    assists         INTEGER DEFAULT 0,
    clean_sheets    INTEGER DEFAULT 0,
    bonus           INTEGER DEFAULT 0,
    was_home        INTEGER DEFAULT 0,
    bps             INTEGER DEFAULT 0,
    influence       REAL DEFAULT 0,
    creativity      REAL DEFAULT 0,
    threat          REAL DEFAULT 0,
    ict_index       REAL DEFAULT 0,
    expected_goals  REAL DEFAULT 0,
    expected_assists REAL DEFAULT 0,
    expected_goals_conceded REAL DEFAULT 0,
    defensive_contribution INTEGER DEFAULT 0,
    goals_conceded  INTEGER DEFAULT 0,
    saves           INTEGER DEFAULT 0,
    yellow_cards    INTEGER DEFAULT 0,
    red_cards       INTEGER DEFAULT 0,
    own_goals       INTEGER DEFAULT 0,
    penalties_saved INTEGER DEFAULT 0,
    penalties_missed INTEGER DEFAULT 0,
    value           INTEGER DEFAULT 0,      -- price × 10 at the time of the match
    selected        INTEGER DEFAULT 0,
    UNIQUE(player_id, fixture)
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
    selling_price   INTEGER,
    purchase_price  INTEGER,
    position        INTEGER NOT NULL,       -- squad slot 1-15
    is_captain      INTEGER DEFAULT 0,
    is_vice_captain INTEGER DEFAULT 0,
    multiplier      INTEGER DEFAULT 1       -- 0=benched
);
"""


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta_json(conn: sqlite3.Connection, key: str, default=None):
    raw = get_meta(conn, key)
    return json.loads(raw) if raw else default


def set_meta_json(conn: sqlite3.Connection, key: str, obj) -> None:
    set_meta(conn, key, json.dumps(obj))


def clear_data(conn: sqlite3.Connection) -> None:
    """Delete all season data (keeps the schema)."""
    for table in DATA_TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM meta WHERE key != 'schema_version'")
    conn.commit()


def init_db(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Create the database file (if needed) and ensure all tables exist.

    A database built with an older schema is dropped and rebuilt.
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(META_SQL)
    if get_meta(conn, "schema_version") != SCHEMA_VERSION:
        for table in DATA_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("DELETE FROM meta")
        conn.executescript(SCHEMA_SQL)
        set_meta(conn, "schema_version", SCHEMA_VERSION)
    else:
        conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
