"""Persist normalised FPL data into SQLite."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from .api_client import FPLClient
from .models import DB_PATH, init_db

logger = logging.getLogger(__name__)


class FPLStore:
    """Orchestrates fetching from the FPL API, normalisation, and SQLite upserts."""

    def __init__(
        self,
        client: FPLClient | None = None,
        db_path: Path | str = DB_PATH,
    ) -> None:
        self.client = client or FPLClient()
        self.conn = init_db(db_path)

    # -- Full refresh ---------------------------------------------------------

    def refresh_all(self) -> None:
        """Pull bootstrap, fixtures, and persist everything."""
        self.refresh_bootstrap()
        self.refresh_fixtures()
        logger.info("Full data refresh complete.")

    # -- Bootstrap (players, teams, gameweeks) --------------------------------

    def refresh_bootstrap(self) -> None:
        """Fetch bootstrap-static and upsert players, teams, and gameweeks."""
        data = self.client.get_bootstrap()
        self._upsert_teams(data["teams"])
        self._upsert_players(data["elements"])
        self._upsert_gameweeks(data["events"])

    def _upsert_teams(self, raw: list[dict]) -> None:
        df = pd.json_normalize(raw)
        cols = [
            "id", "name", "short_name", "strength",
            "strength_overall_home", "strength_overall_away",
            "strength_attack_home", "strength_attack_away",
            "strength_defence_home", "strength_defence_away",
        ]
        df = df[[c for c in cols if c in df.columns]]
        self._upsert(df, "teams")
        logger.info("Upserted %d teams.", len(df))

    def _upsert_players(self, raw: list[dict]) -> None:
        df = pd.json_normalize(raw)
        cols = [
            "id", "web_name", "first_name", "second_name", "team",
            "element_type", "now_cost", "total_points", "minutes",
            "goals_scored", "assists", "clean_sheets",
            "selected_by_percent", "form", "points_per_game",
            "status", "chance_of_playing_next_round",
            "ict_index", "ep_this", "ep_next", "news",
        ]
        df = df[[c for c in cols if c in df.columns]].rename(columns={"team": "team_id"})
        # Coerce numeric columns that may arrive as strings
        for col in ("form", "points_per_game", "ict_index", "ep_this", "ep_next"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        self._upsert(df, "players")
        logger.info("Upserted %d players.", len(df))

    def _upsert_gameweeks(self, raw: list[dict]) -> None:
        df = pd.json_normalize(raw)
        cols = [
            "id", "name", "deadline_time", "is_current", "is_next",
            "finished", "highest_score", "average_score",
        ]
        df = df[[c for c in cols if c in df.columns]]
        self._upsert(df, "gameweeks")
        logger.info("Upserted %d gameweeks.", len(df))

    # -- Fixtures -------------------------------------------------------------

    def refresh_fixtures(self) -> None:
        """Fetch and persist all fixtures."""
        raw = self.client.get_fixtures()
        df = pd.json_normalize(raw)
        cols = [
            "id", "event", "team_h", "team_a",
            "team_h_difficulty", "team_a_difficulty",
            "finished", "team_h_score", "team_a_score", "kickoff_time",
        ]
        df = df[[c for c in cols if c in df.columns]]
        self._upsert(df, "fixtures")
        logger.info("Upserted %d fixtures.", len(df))

    # -- Player history -------------------------------------------------------

    def refresh_player_history(self, player_id: int) -> None:
        """Fetch and persist per-match history for a single player."""
        data = self.client.get_player_summary(player_id)
        rows = data.get("history", [])
        if not rows:
            return
        df = pd.json_normalize(rows)
        rename = {
            "element": "player_id",
            "round": "gameweek",
        }
        df = df.rename(columns=rename)
        cols = [
            "player_id", "gameweek", "opponent_team", "total_points",
            "minutes", "goals_scored", "assists", "clean_sheets",
            "was_home", "bps", "influence", "creativity", "threat",
            "ict_index", "value", "selected",
        ]
        df = df[[c for c in cols if c in df.columns]]
        for col in ("influence", "creativity", "threat", "ict_index"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        self._upsert(df, "player_history", conflict_cols=["player_id", "gameweek"])
        logger.info("Upserted %d history rows for player %d.", len(df), player_id)

    def refresh_all_player_histories(self, top_n: int = 300) -> None:
        """Bulk-fetch history for the top *top_n* players by total_points."""
        player_ids = pd.read_sql(
            "SELECT id FROM players ORDER BY total_points DESC LIMIT ?",
            self.conn,
            params=(top_n,),
        )["id"].tolist()
        for pid in player_ids:
            try:
                self.refresh_player_history(pid)
            except Exception:
                logger.warning("Failed to fetch history for player %d", pid, exc_info=True)

    # -- Manager / your team --------------------------------------------------

    def refresh_my_team(self, manager_id: int) -> None:
        """Fetch the manager's current squad — tries auth endpoint first,
        falls back to the public picks endpoint automatically."""
        try:
            data = self.client.get_my_team(manager_id)
            self._store_picks(data.get("picks", []), manager_id, source="auth")
            return
        except Exception as exc:
            logger.info("Auth endpoint unavailable (%s), falling back to public picks.", exc)

        self._refresh_my_team_public(manager_id)

    def _refresh_my_team_public(self, manager_id: int) -> None:
        """Fetch the squad via the public ``/entry/{id}/event/{gw}/picks/``
        endpoint which requires no authentication.  Selling prices are
        approximated from ``now_cost`` in the players table."""
        current_gw = self.current_gameweek()
        data = self.client.get_manager_picks(manager_id, current_gw)

        picks = data.get("picks", [])
        if not picks:
            logger.warning("No picks returned for GW%d.", current_gw)
            return

        # The public endpoint doesn't include selling_price / purchase_price.
        # We approximate selling_price from the players table (now_cost).
        players_costs = dict(
            pd.read_sql("SELECT id, now_cost FROM players", self.conn).values.tolist()
        )

        df = pd.json_normalize(picks)
        df = df.rename(columns={"element": "player_id"})
        df["selling_price"] = df["player_id"].map(players_costs)
        df["purchase_price"] = df["selling_price"]

        cols = [
            "player_id", "selling_price", "purchase_price",
            "position", "is_captain", "is_vice_captain", "multiplier",
        ]
        df = df[[c for c in cols if c in df.columns]]
        self.conn.execute("DELETE FROM your_team")
        df.to_sql("your_team", self.conn, if_exists="append", index=False)
        self.conn.commit()

        # Also extract bank value from entry_history if present
        entry_hist = data.get("entry_history", {})
        bank = entry_hist.get("bank")
        if bank is not None:
            logger.info("Bank from public endpoint: %d (£%.1fm)", bank, bank / 10)
        logger.info(
            "Stored %d picks for manager %d via public endpoint (GW%d).",
            len(df), manager_id, current_gw,
        )

    def get_manager_bank(self, manager_id: int) -> int | None:
        """Return the bank value (×10) from the public picks endpoint, or None."""
        try:
            current_gw = self.current_gameweek()
            data = self.client.get_manager_picks(manager_id, current_gw)
            return data.get("entry_history", {}).get("bank")
        except Exception:
            return None

    def _store_picks(self, picks: list[dict], manager_id: int, source: str = "auth") -> None:
        """Persist picks from either the auth or public endpoint."""
        if not picks:
            logger.warning("No picks returned – source=%s.", source)
            return
        df = pd.json_normalize(picks)
        df = df.rename(columns={"element": "player_id"})
        cols = [
            "player_id", "selling_price", "purchase_price",
            "position", "is_captain", "is_vice_captain", "multiplier",
        ]
        df = df[[c for c in cols if c in df.columns]]
        self.conn.execute("DELETE FROM your_team")
        df.to_sql("your_team", self.conn, if_exists="append", index=False)
        self.conn.commit()
        logger.info("Stored %d picks for manager %d (%s).", len(df), manager_id, source)

    # -- Query helpers --------------------------------------------------------

    def players_df(self) -> pd.DataFrame:
        """Return the full players table as a DataFrame."""
        return pd.read_sql("SELECT * FROM players", self.conn)

    def teams_df(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM teams", self.conn)

    def fixtures_df(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM fixtures", self.conn)

    def gameweeks_df(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM gameweeks", self.conn)

    def player_history_df(self, player_id: int | None = None) -> pd.DataFrame:
        if player_id is not None:
            return pd.read_sql(
                "SELECT * FROM player_history WHERE player_id = ?",
                self.conn,
                params=(player_id,),
            )
        return pd.read_sql("SELECT * FROM player_history", self.conn)

    def your_team_df(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM your_team", self.conn)

    def current_gameweek(self) -> int:
        """Return the id of the current (or most recently finished) gameweek."""
        row = pd.read_sql(
            "SELECT id FROM gameweeks WHERE is_current = 1 LIMIT 1",
            self.conn,
        )
        if row.empty:
            row = pd.read_sql(
                "SELECT id FROM gameweeks WHERE finished = 1 ORDER BY id DESC LIMIT 1",
                self.conn,
            )
        return int(row["id"].iloc[0]) if not row.empty else 1

    # -- Low-level upsert -----------------------------------------------------

    def _upsert(
        self,
        df: pd.DataFrame,
        table: str,
        conflict_cols: list[str] | None = None,
    ) -> None:
        """INSERT OR REPLACE rows from *df* into *table*."""
        if df.empty:
            return
        cols = ", ".join(df.columns)
        placeholders = ", ".join(["?"] * len(df.columns))

        if conflict_cols:
            conflict = ", ".join(conflict_cols)
            update_cols = [c for c in df.columns if c not in conflict_cols]
            update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
            sql = (
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict}) DO UPDATE SET {update_clause}"
            )
        else:
            sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"

        cur = self.conn.cursor()
        cur.executemany(sql, df.values.tolist())
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
