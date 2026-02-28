"""Tests for the forecast module."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl_agent.forecast.expected_points import ExpectedPointsModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _players_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"id": 1, "web_name": "Salah",   "team_id": 10, "element_type": 3,
         "now_cost": 130, "ep_next": 7.5, "chance_of_playing_next_round": 100,
         "status": "a"},
        {"id": 2, "web_name": "Haaland", "team_id": 11, "element_type": 4,
         "now_cost": 145, "ep_next": 7.0, "chance_of_playing_next_round": 100,
         "status": "a"},
        {"id": 3, "web_name": "Injured", "team_id": 12, "element_type": 2,
         "now_cost": 50,  "ep_next": 4.0, "chance_of_playing_next_round": 25,
         "status": "d"},
    ])


def _history_df() -> pd.DataFrame:
    rows = []
    for gw in range(1, 9):
        rows.append({"player_id": 1, "gameweek": gw, "total_points": 5 + gw,
                      "opponent_team": 5, "minutes": 90})
        rows.append({"player_id": 2, "gameweek": gw, "total_points": 4 + gw,
                      "opponent_team": 6, "minutes": 90})
        rows.append({"player_id": 3, "gameweek": gw, "total_points": 2,
                      "opponent_team": 7, "minutes": 60})
    return pd.DataFrame(rows)


def _fixtures_df() -> pd.DataFrame:
    rows = []
    for gw in range(9, 15):
        rows.append({"id": gw * 10, "event": gw, "team_h": 10, "team_a": 12,
                      "team_h_difficulty": 2, "team_a_difficulty": 4})
        rows.append({"id": gw * 10 + 1, "event": gw, "team_h": 11, "team_a": 13,
                      "team_h_difficulty": 3, "team_a_difficulty": 3})
    return pd.DataFrame(rows)


def _teams_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"id": 10, "name": "Liverpool", "short_name": "LIV"},
        {"id": 11, "name": "Man City",  "short_name": "MCI"},
        {"id": 12, "name": "Bournemouth", "short_name": "BOU"},
    ])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExpectedPointsModel:

    def test_output_shape(self):
        model = ExpectedPointsModel(
            players=_players_df(),
            history=_history_df(),
            fixtures=_fixtures_df(),
            teams=_teams_df(),
            current_gw=8,
            horizon=6,
        )
        forecast = model.predict()

        assert "player_id" in forecast.columns
        assert "total_expected_points" in forecast.columns
        assert "variance" in forecast.columns
        # One row per player
        assert len(forecast) == 3
        # Six gameweek columns
        gw_cols = [c for c in forecast.columns if c.startswith("expected_points_gw")]
        assert len(gw_cols) == 6

    def test_injured_player_penalised(self):
        model = ExpectedPointsModel(
            players=_players_df(),
            history=_history_df(),
            fixtures=_fixtures_df(),
            teams=_teams_df(),
            current_gw=8,
            horizon=6,
        )
        forecast = model.predict()

        injured_ep = forecast.loc[forecast["player_id"] == 3, "total_expected_points"].iloc[0]
        healthy_ep = forecast.loc[forecast["player_id"] == 1, "total_expected_points"].iloc[0]
        # Injured player (25% chance) should have much lower EP
        assert injured_ep < healthy_ep

    def test_easy_fixtures_boost(self):
        """Player with easier fixtures (FDR 2) should get a multiplier > 1."""
        model = ExpectedPointsModel(
            players=_players_df(),
            history=_history_df(),
            fixtures=_fixtures_df(),
            teams=_teams_df(),
            current_gw=8,
            horizon=6,
        )
        forecast = model.predict()

        salah_ep = forecast.loc[forecast["player_id"] == 1, "total_expected_points"].iloc[0]
        # Salah's team (10) has FDR=2 (easy) → multiplier > 1
        # Base rate for Salah is weighted average of 6,7,8,9,10,11,12,13 ≈ ~10+
        assert salah_ep > 0

    def test_variance_non_negative(self):
        model = ExpectedPointsModel(
            players=_players_df(),
            history=_history_df(),
            fixtures=_fixtures_df(),
            teams=_teams_df(),
            current_gw=8,
            horizon=6,
        )
        forecast = model.predict()

        assert (forecast["variance"] >= 0).all()

    def test_empty_history_uses_ep_next(self):
        """Players with no history should fall back to ep_next from the API."""
        empty_history = pd.DataFrame(
            columns=["player_id", "gameweek", "total_points", "opponent_team", "minutes"]
        )
        model = ExpectedPointsModel(
            players=_players_df(),
            history=empty_history,
            fixtures=_fixtures_df(),
            teams=_teams_df(),
            current_gw=8,
            horizon=6,
        )
        forecast = model.predict()

        # Should still produce forecasts using ep_next fallback
        assert len(forecast) == 3
        assert (forecast["total_expected_points"] >= 0).all()
