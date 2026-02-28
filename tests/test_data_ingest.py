"""Tests for the data_ingest module."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from fpl_agent.data_ingest.api_client import FPLClient
from fpl_agent.data_ingest.models import init_db
from fpl_agent.data_ingest.store import FPLStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BOOTSTRAP_RESPONSE = {
    "elements": [
        {
            "id": 1,
            "web_name": "Salah",
            "first_name": "Mohamed",
            "second_name": "Salah",
            "team": 10,
            "element_type": 3,
            "now_cost": 130,
            "total_points": 200,
            "minutes": 2500,
            "goals_scored": 18,
            "assists": 10,
            "clean_sheets": 0,
            "selected_by_percent": "45.0",
            "form": "8.5",
            "points_per_game": "7.5",
            "status": "a",
            "chance_of_playing_next_round": 100,
            "ict_index": "350.0",
            "ep_this": "7.5",
            "ep_next": "8.0",
            "news": "",
        },
        {
            "id": 2,
            "web_name": "Haaland",
            "first_name": "Erling",
            "second_name": "Haaland",
            "team": 11,
            "element_type": 4,
            "now_cost": 145,
            "total_points": 190,
            "minutes": 2300,
            "goals_scored": 22,
            "assists": 5,
            "clean_sheets": 0,
            "selected_by_percent": "55.0",
            "form": "9.0",
            "points_per_game": "7.2",
            "status": "a",
            "chance_of_playing_next_round": 100,
            "ict_index": "380.0",
            "ep_this": "7.0",
            "ep_next": "7.5",
            "news": "",
        },
    ],
    "teams": [
        {
            "id": 10,
            "name": "Liverpool",
            "short_name": "LIV",
            "strength": 5,
            "strength_overall_home": 1300,
            "strength_overall_away": 1280,
            "strength_attack_home": 1350,
            "strength_attack_away": 1320,
            "strength_defence_home": 1280,
            "strength_defence_away": 1260,
        },
        {
            "id": 11,
            "name": "Man City",
            "short_name": "MCI",
            "strength": 5,
            "strength_overall_home": 1310,
            "strength_overall_away": 1290,
            "strength_attack_home": 1370,
            "strength_attack_away": 1340,
            "strength_defence_home": 1290,
            "strength_defence_away": 1270,
        },
    ],
    "events": [
        {
            "id": 1,
            "name": "Gameweek 1",
            "deadline_time": "2025-08-16T10:00:00Z",
            "is_current": True,
            "is_next": False,
            "finished": True,
            "highest_score": 120,
            "average_score": 55,
        },
    ],
}

FIXTURES_RESPONSE = [
    {
        "id": 1,
        "event": 2,
        "team_h": 10,
        "team_a": 11,
        "team_h_difficulty": 4,
        "team_a_difficulty": 4,
        "finished": False,
        "team_h_score": None,
        "team_a_score": None,
        "kickoff_time": "2025-08-23T15:00:00Z",
    },
]

PLAYER_SUMMARY_RESPONSE = {
    "history": [
        {
            "element": 1,
            "round": 1,
            "opponent_team": 5,
            "total_points": 12,
            "minutes": 90,
            "goals_scored": 1,
            "assists": 1,
            "clean_sheets": 0,
            "was_home": True,
            "bps": 45,
            "influence": "70.0",
            "creativity": "55.0",
            "threat": "80.0",
            "ict_index": "20.5",
            "value": 130,
            "selected": 500000,
        },
    ],
    "fixtures": [],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFPLClient:
    """Tests for the API client (mocked HTTP)."""

    @patch("fpl_agent.data_ingest.api_client.requests.Session")
    def test_get_bootstrap(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = BOOTSTRAP_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.return_value = mock_resp
        session.headers = {}

        client = FPLClient(session=session)
        data = client.get_bootstrap()

        assert "elements" in data
        assert len(data["elements"]) == 2

    @patch("fpl_agent.data_ingest.api_client.requests.Session")
    def test_get_fixtures(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = FIXTURES_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.return_value = mock_resp
        session.headers = {}

        client = FPLClient(session=session)
        data = client.get_fixtures()

        assert len(data) == 1
        assert data[0]["team_h"] == 10

    @patch("fpl_agent.data_ingest.api_client.requests.Session")
    def test_get_player_summary(self, mock_session_cls):
        mock_resp = MagicMock()
        mock_resp.json.return_value = PLAYER_SUMMARY_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.return_value = mock_resp
        session.headers = {}

        client = FPLClient(session=session)
        data = client.get_player_summary(1)

        assert len(data["history"]) == 1
        assert data["history"][0]["total_points"] == 12


class TestInitDB:
    """Tests for database schema creation."""

    def test_creates_all_tables(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

        expected = {"players", "teams", "fixtures", "player_history", "gameweeks", "your_team"}
        assert expected.issubset(tables)
        conn.close()


class TestFPLStore:
    """Tests for the storage layer with mocked API responses."""

    def _make_store(self, tmp_path) -> FPLStore:
        client = MagicMock(spec=FPLClient)
        client.get_bootstrap.return_value = BOOTSTRAP_RESPONSE
        client.get_fixtures.return_value = FIXTURES_RESPONSE
        client.get_player_summary.return_value = PLAYER_SUMMARY_RESPONSE

        db_path = tmp_path / "test.db"
        return FPLStore(client=client, db_path=db_path)

    def test_refresh_all(self, tmp_path):
        store = self._make_store(tmp_path)
        store.refresh_all()

        players = store.players_df()
        assert len(players) == 2
        assert "Salah" in players["web_name"].values

        teams = store.teams_df()
        assert len(teams) == 2

        fixtures = store.fixtures_df()
        assert len(fixtures) == 1

    def test_refresh_player_history(self, tmp_path):
        store = self._make_store(tmp_path)
        store.refresh_all()
        store.refresh_player_history(1)

        history = store.player_history_df(player_id=1)
        assert len(history) == 1
        assert history.iloc[0]["total_points"] == 12

    def test_current_gameweek(self, tmp_path):
        store = self._make_store(tmp_path)
        store.refresh_all()

        gw = store.current_gameweek()
        assert gw == 1

    def test_upsert_idempotent(self, tmp_path):
        """Upserting the same data twice should not duplicate rows."""
        store = self._make_store(tmp_path)
        store.refresh_all()
        store.refresh_all()

        assert len(store.players_df()) == 2
        assert len(store.teams_df()) == 2
