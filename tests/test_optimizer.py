"""Tests for the optimizer module."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_agent.optimizer.milp import (
    MAX_PER_CLUB,
    POSITION_LIMITS,
    SQUAD_SIZE,
    OptimizationResult,
    TeamState,
    optimize,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_players(n: int = 50) -> pd.DataFrame:
    """Generate a synthetic player pool across 10 teams and 4 positions."""
    rows = []
    pos_cycle = [1, 2, 2, 2, 3, 3, 3, 4, 4, 4]  # rough distribution
    for i in range(1, n + 1):
        pos = pos_cycle[i % len(pos_cycle)]
        rows.append({
            "id": i,
            "web_name": f"Player_{i}",
            "element_type": pos,
            "team_id": (i % 10) + 1,
            "now_cost": 50 + (i % 20) * 5,
        })
    return pd.DataFrame(rows)


def _build_forecast(players: pd.DataFrame) -> pd.DataFrame:
    """Assign synthetic expected points proportional to cost."""
    return pd.DataFrame({
        "player_id": players["id"],
        "total_expected_points": players["now_cost"] / 10.0,
    })


def _build_team_state(players: pd.DataFrame) -> TeamState:
    """Pick the first 15 valid players as the current squad."""
    # Ensure valid formation: 2 GK, 5 DEF, 5 MID, 3 FWD
    squad: list[int] = []
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for _, row in players.iterrows():
        pos = row["element_type"]
        if counts[pos] < POSITION_LIMITS[pos]:
            squad.append(row["id"])
            counts[pos] += 1
        if len(squad) == SQUAD_SIZE:
            break

    selling_prices = {pid: int(players.loc[players["id"] == pid, "now_cost"].iloc[0])
                      for pid in squad}
    return TeamState(
        current_squad=squad,
        selling_prices=selling_prices,
        bank=50,
        free_transfers=1,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOptimizer:

    def test_selects_15_players(self):
        players = _build_players()
        forecast = _build_forecast(players)
        team_state = _build_team_state(players)

        result = optimize(team_state, forecast, players)

        assert len(result.selected_ids) == SQUAD_SIZE

    def test_position_constraints(self):
        players = _build_players()
        forecast = _build_forecast(players)
        team_state = _build_team_state(players)

        result = optimize(team_state, forecast, players)

        pid_to_pos = dict(zip(players["id"], players["element_type"]))
        counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for pid in result.selected_ids:
            counts[pid_to_pos[pid]] += 1

        assert counts == POSITION_LIMITS

    def test_club_limit(self):
        players = _build_players()
        forecast = _build_forecast(players)
        team_state = _build_team_state(players)

        result = optimize(team_state, forecast, players)

        pid_to_team = dict(zip(players["id"], players["team_id"]))
        club_counts: dict[int, int] = {}
        for pid in result.selected_ids:
            tid = pid_to_team[pid]
            club_counts[tid] = club_counts.get(tid, 0) + 1

        for tid, count in club_counts.items():
            assert count <= MAX_PER_CLUB, f"Club {tid} has {count} players (max {MAX_PER_CLUB})"

    def test_budget_constraint(self):
        players = _build_players()
        forecast = _build_forecast(players)
        team_state = _build_team_state(players)

        result = optimize(team_state, forecast, players)

        total_cost = sum(
            int(players.loc[players["id"] == pid, "now_cost"].iloc[0])
            for pid in result.selected_ids
        )
        assert total_cost <= team_state.total_budget

    def test_returns_optimization_result(self):
        players = _build_players()
        forecast = _build_forecast(players)
        team_state = _build_team_state(players)

        result = optimize(team_state, forecast, players)

        assert isinstance(result, OptimizationResult)
        assert result.total_expected_points > 0
        assert result.transfer_cost >= 0

    def test_no_transfers_when_squad_is_optimal(self):
        """If the current squad is already the best, no transfers should happen."""
        # Exactly one valid 15-man squad available → must keep it.
        rows = []
        for i, pos in enumerate([1] * 2 + [2] * 5 + [3] * 5 + [4] * 3, start=1):
            rows.append({"id": i, "web_name": f"P{i}", "element_type": pos,
                         "team_id": i, "now_cost": 50})
        players = pd.DataFrame(rows)
        forecast = _build_forecast(players)
        team_state = _build_team_state(players)

        result = optimize(team_state, forecast, players)

        assert len(result.transfers_in) == 0
        assert len(result.transfers_out) == 0
