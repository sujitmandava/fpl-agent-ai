"""Persist normalised FPL data into SQLite."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from .api_client import FPLClient
from .manager import (
    ManagerState,
    compute_free_transfers,
    purchase_prices,
    selling_price,
)
from .models import (
    DB_PATH, clear_data, get_meta, get_meta_json, init_db, set_meta, set_meta_json,
)

logger = logging.getLogger(__name__)

# Re-fetch per-player histories when the cached copy is older than this.
HISTORY_MAX_AGE_SECONDS = 6 * 3600


def season_key(events: list[dict]) -> str | None:
    """Identify the season from the first gameweek's deadline, e.g. '2026/27'."""
    deadlines = [e.get("deadline_time") for e in events if e.get("deadline_time")]
    if not deadlines:
        return None
    year = int(min(deadlines)[:4])
    return f"{year}/{str(year + 1)[-2:]}"


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
        """Fetch bootstrap-static and upsert players, teams, and gameweeks.

        If the season has changed since the last refresh, all cached data is
        wiped first: player IDs are reassigned every season, so last season's
        rows would otherwise point at the wrong players.
        """
        data = self.client.get_bootstrap()
        season = season_key(data.get("events", []))
        stored = get_meta(self.conn, "season")
        if season and stored and season != stored:
            logger.warning("Season changed (%s → %s); clearing cached data.", stored, season)
            clear_data(self.conn)
        if season:
            set_meta(self.conn, "season", season)

        self._upsert_teams(data["teams"])
        self._upsert_players(data["elements"])
        self._upsert_gameweeks(data["events"])

        # Season rules, so scoring and chips are never hard-coded.
        config = data.get("game_config", {}) or {}
        if config.get("scoring"):
            set_meta_json(self.conn, "scoring", config["scoring"])
        rules = config.get("rules") or data.get("game_settings") or {}
        if rules:
            set_meta_json(self.conn, "rules", {
                k: rules[k] for k in ("max_extra_free_transfers", "squad_team_limit",
                                      "transfers_sell_on_fee") if k in rules
            })
        if data.get("chips"):
            set_meta_json(self.conn, "chips", [
                {k: c.get(k) for k in ("name", "number", "start_event", "stop_event", "chip_type")}
                for c in data["chips"]
            ])

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
        for col in ("form", "points_per_game", "ict_index", "ep_this", "ep_next",
                    "selected_by_percent"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        if "chance_of_playing_next_round" in df.columns:
            # Keep NULL (= no news) distinct from 0; convert NaN → None for sqlite.
            df["chance_of_playing_next_round"] = df["chance_of_playing_next_round"].astype(object)
            df.loc[df["chance_of_playing_next_round"].isna(), "chance_of_playing_next_round"] = None
        self._upsert(df, "players")
        # Remove players no longer in the game (otherwise the optimizer can pick them).
        self._delete_missing("players", "id", df["id"].tolist())
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
            "started", "finished", "finished_provisional",
            "team_h_score", "team_a_score", "kickoff_time",
        ]
        df = df[[c for c in cols if c in df.columns]]
        df = df.astype(object).where(df.notna(), None)
        self._upsert(df, "fixtures")
        self._delete_missing("fixtures", "id", df["id"].tolist())
        logger.info("Upserted %d fixtures.", len(df))

    # -- Player history -------------------------------------------------------

    HISTORY_COLS = [
        "player_id", "fixture", "gameweek", "opponent_team", "total_points",
        "minutes", "starts", "goals_scored", "assists", "clean_sheets", "bonus",
        "was_home", "bps", "influence", "creativity", "threat", "ict_index",
        "expected_goals", "expected_assists", "expected_goals_conceded",
        "defensive_contribution", "goals_conceded", "saves", "yellow_cards",
        "red_cards", "own_goals", "penalties_saved", "penalties_missed",
        "value", "selected",
    ]
    _NUMERIC_STR_COLS = (
        "influence", "creativity", "threat", "ict_index",
        "expected_goals", "expected_assists", "expected_goals_conceded",
    )

    def _history_frame(self, rows: list[dict]) -> pd.DataFrame:
        df = pd.json_normalize(rows).rename(columns={"element": "player_id", "round": "gameweek"})
        df = df[[c for c in self.HISTORY_COLS if c in df.columns]]
        for col in self._NUMERIC_STR_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        if "was_home" in df.columns:
            df["was_home"] = df["was_home"].astype(int)
        return df

    def refresh_player_history(self, player_id: int) -> None:
        """Fetch and persist per-match history for a single player."""
        rows = self.client.get_player_summary(player_id).get("history", [])
        self._store_history(rows)

    def _store_history(self, rows: list[dict]) -> None:
        if not rows:
            return
        df = self._history_frame(rows)
        self._upsert(df, "player_history", conflict_cols=["player_id", "fixture"])

    def refresh_all_player_histories(
        self, top_n: int | None = None, workers: int = 8,
    ) -> int:
        """Fetch history for every player who has played this season.

        ``top_n`` limits the fetch to the top players by total points (0/None
        means all). Fetches run in parallel; writes happen on this thread.
        Returns the number of players fetched.
        """
        sql = "SELECT id FROM players WHERE minutes > 0 ORDER BY total_points DESC"
        params: tuple = ()
        if top_n:
            sql += " LIMIT ?"
            params = (top_n,)
        player_ids = pd.read_sql(sql, self.conn, params=params)["id"].tolist()

        fetched = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.client.get_player_summary, pid): pid for pid in player_ids}
            for fut in as_completed(futures):
                pid = futures[fut]
                try:
                    self._store_history(fut.result().get("history", []))
                    fetched += 1
                except Exception:
                    logger.warning("Failed to fetch history for player %d", pid, exc_info=True)
        set_meta(self.conn, "history_fetched_at", str(time.time()))
        logger.info("Fetched history for %d/%d players.", fetched, len(player_ids))
        return fetched

    def history_is_stale(self, max_age: float = HISTORY_MAX_AGE_SECONDS) -> bool:
        ts = get_meta(self.conn, "history_fetched_at")
        if ts is None:
            return True
        return (time.time() - float(ts)) > max_age

    # -- Manager / your team --------------------------------------------------

    def load_manager_state(self, manager_id: int) -> ManagerState:
        """Return squad, selling prices, bank and free transfers for the
        upcoming gameweek, and persist the squad to ``your_team``.

        Uses the authenticated ``/my-team/`` endpoint when logged in (exact
        values, including transfers already made for the next deadline);
        otherwise reconstructs everything from public endpoints.
        """
        state = None
        if getattr(self.client, "authenticated", False):
            try:
                state = self._manager_state_auth(manager_id)
            except Exception as exc:
                logger.info("Auth endpoint failed (%s); using public endpoints.", exc)
        if state is None:
            state = self._manager_state_public(manager_id)

        # Chips played and profile (public; cheap).
        try:
            history = self.client.get_manager_history(manager_id)
            state.chips_played = [
                {"name": c["name"], "event": c["event"]} for c in history.get("chips", [])
            ]
        except Exception as exc:
            logger.info("Could not fetch chip history: %s", exc)
        try:
            state.entry = self.client.get_entry(manager_id)
        except Exception as exc:
            logger.info("Could not fetch manager profile: %s", exc)
        return state

    def _manager_state_auth(self, manager_id: int) -> ManagerState:
        data = self.client.get_my_team(manager_id)
        picks = data.get("picks", [])
        if not picks:
            raise ValueError("my-team returned no picks")
        self._store_picks(picks)
        tr = data.get("transfers", {}) or {}
        limit = tr.get("limit")
        made = int(tr.get("made", 0) or 0)
        notes = []
        if limit is None:
            # Unlimited (wildcard / free hit active, or pre-season).
            ft = 15
            notes.append("Unlimited transfers this gameweek (chip active).")
        else:
            ft = max(int(limit) - made, 0)
            if made:
                notes.append(f"{made} transfer(s) already made for the next deadline.")
        return ManagerState(
            squad=[p["element"] for p in picks],
            selling_prices={p["element"]: int(p["selling_price"]) for p in picks},
            purchase_prices={p["element"]: int(p["purchase_price"]) for p in picks
                             if p.get("purchase_price") is not None},
            bank=int(tr.get("bank", 0) or 0),
            free_transfers=ft,
            source="auth",
            notes=notes,
        )

    def _manager_state_public(self, manager_id: int) -> ManagerState:
        notes: list[str] = []
        history = self.client.get_manager_history(manager_id)
        current = history.get("current", [])
        chips = history.get("chips", [])
        if not current:
            raise ValueError(f"Manager {manager_id} has no gameweek history yet.")

        gw = max(e["event"] for e in current)
        freehit_events = {c["event"] for c in chips if c.get("name") == "freehit"}

        picks_data = self.client.get_manager_picks(manager_id, gw)
        if picks_data.get("active_chip") == "freehit" and gw > 1:
            # A Free Hit squad reverts next gameweek; plan from the real squad.
            notes.append(f"Free Hit played in GW{gw}; using the GW{gw - 1} squad it reverts to.")
            picks_data = self.client.get_manager_picks(manager_id, gw - 1)

        picks = picks_data.get("picks", [])
        squad = [p["element"] for p in picks]
        bank = int(picks_data.get("entry_history", {}).get("bank", 0) or 0)

        now_costs = dict(pd.read_sql("SELECT id, now_cost FROM players", self.conn).values.tolist())
        start_event = min(e["event"] for e in current)
        start_prices = self._prices_at_gameweek(squad, start_event)
        transfers = self.client.get_manager_transfers(manager_id)
        bought, fallback = purchase_prices(squad, transfers, freehit_events, start_prices, now_costs)
        sell = {pid: selling_price(bought[pid], int(now_costs.get(pid, bought[pid]))) for pid in squad}
        if fallback:
            notes.append(
                f"Purchase price unknown for {len(fallback)} player(s); assumed current price."
            )

        for p in picks:
            p["selling_price"] = sell[p["element"]]
            p["purchase_price"] = bought[p["element"]]
        self._store_picks(picks)

        ft = compute_free_transfers(current, chips, max_ft=self.max_free_transfers())
        notes.append(
            "Logged out: free transfers and selling prices were reconstructed from public "
            "data. Transfers already made for the next deadline are not visible. Set "
            "FPL_REFRESH_TOKEN to log in (see README → Logging in)."
        )
        return ManagerState(
            squad=squad, selling_prices=sell, bank=bank,
            free_transfers=ft, source="public", notes=notes,
            purchase_prices=bought,
        )

    def _prices_at_gameweek(self, player_ids: list[int], gameweek: int) -> dict[int, int]:
        """Price of each player in *gameweek*, from the stored match history."""
        if not player_ids:
            return {}
        q = ",".join("?" * len(player_ids))
        df = pd.read_sql(
            f"SELECT player_id, gameweek, value FROM player_history "
            f"WHERE player_id IN ({q}) AND gameweek >= ? ORDER BY gameweek",
            self.conn, params=(*player_ids, gameweek),
        )
        # Earliest match on/after the manager's first gameweek (normally that
        # gameweek itself; later if the player had no fixture that week).
        df = df[df["value"] > 0].drop_duplicates("player_id", keep="first")
        return {int(r.player_id): int(r.value) for r in df.itertuples()}

    def _store_picks(self, picks: list[dict]) -> None:
        df = pd.json_normalize(picks).rename(columns={"element": "player_id"})
        cols = [
            "player_id", "selling_price", "purchase_price",
            "position", "is_captain", "is_vice_captain", "multiplier",
        ]
        df = df[[c for c in cols if c in df.columns]]
        self.conn.execute("DELETE FROM your_team")
        df.to_sql("your_team", self.conn, if_exists="append", index=False)
        self.conn.commit()

    # -- Query helpers --------------------------------------------------------

    def scoring_rules(self) -> dict:
        """This season's points per action, from bootstrap ``game_config``."""
        return get_meta_json(self.conn, "scoring", {}) or {}

    def chip_definitions(self) -> list[dict]:
        return get_meta_json(self.conn, "chips", []) or []

    def max_free_transfers(self) -> int:
        rules = get_meta_json(self.conn, "rules", {}) or {}
        return 1 + int(rules.get("max_extra_free_transfers", 4))

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
        """Return the id of the current (or most recently finished) gameweek.

        This is the latest gameweek whose deadline has passed; forecasts start
        from the gameweek after it.
        """
        row = pd.read_sql(
            "SELECT id FROM gameweeks WHERE is_current = 1 LIMIT 1",
            self.conn,
        )
        if row.empty:
            row = pd.read_sql(
                "SELECT id FROM gameweeks WHERE finished = 1 ORDER BY id DESC LIMIT 1",
                self.conn,
            )
        return int(row["id"].iloc[0]) if not row.empty else 0

    # -- Low-level upsert -----------------------------------------------------

    def _delete_missing(self, table: str, key: str, keep: list) -> None:
        if not keep:
            return
        self.conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS _keep (k INTEGER PRIMARY KEY)")
        self.conn.execute("DELETE FROM _keep")
        self.conn.executemany("INSERT OR IGNORE INTO _keep (k) VALUES (?)", [(int(k),) for k in keep])
        cur = self.conn.execute(f"DELETE FROM {table} WHERE {key} NOT IN (SELECT k FROM _keep)")
        if cur.rowcount:
            logger.info("Removed %d stale rows from %s.", cur.rowcount, table)
        self.conn.commit()

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

        rows = [
            [None if (isinstance(v, float) and pd.isna(v)) else (v.item() if hasattr(v, "item") else v)
             for v in row]
            for row in df.itertuples(index=False, name=None)
        ]
        self.conn.executemany(sql, rows)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
