"""Expected-points model for FPL players over a rolling horizon.

Approach
--------
1. Compute a weighted moving average of recent per-gameweek points
   (exponential decay gives more weight to recent form).
2. Adjust for upcoming fixture difficulty (FDR from the FPL API):
   easier fixtures scale points up, harder ones scale down.
3. Penalise for availability risk (chance_of_playing_next_round).
4. Estimate variance from the standard deviation of recent scores.

This is intentionally a lightweight heuristic suitable for a first release.
It can be replaced by a scikit-learn / XGBoost model by swapping this class.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# Average FDR is 3 on the 1-5 scale; we use 3 as the neutral point.
FDR_NEUTRAL = 3.0
# How much a single FDR point above/below neutral adjusts the multiplier.
FDR_SENSITIVITY = 0.08


class ExpectedPointsModel:
    """Produce a forecast DataFrame for all players over *horizon* gameweeks.

    Parameters
    ----------
    players : DataFrame
        The ``players`` table (from ``FPLStore.players_df()``).
    history : DataFrame
        The ``player_history`` table (all players combined).
    fixtures : DataFrame
        The ``fixtures`` table.
    teams : DataFrame
        The ``teams`` table.
    current_gw : int
        The current gameweek number.
    horizon : int
        Number of future gameweeks to forecast (default 6).
    lookback : int
        Number of past gameweeks to consider for form (default 8).
    decay : float
        Exponential decay factor for weighting recent games (default 0.85).
    """

    def __init__(
        self,
        players: pd.DataFrame,
        history: pd.DataFrame,
        fixtures: pd.DataFrame,
        teams: pd.DataFrame,
        current_gw: int,
        horizon: int = 6,
        lookback: int = 8,
        decay: float = 0.85,
    ) -> None:
        self.players = players.copy()
        self.history = history.copy()
        self.fixtures = fixtures.copy()
        self.teams = teams.copy()
        self.current_gw = current_gw
        self.horizon = horizon
        self.lookback = lookback
        self.decay = decay

    # -- Public API -----------------------------------------------------------

    def predict(self) -> pd.DataFrame:
        """Return a DataFrame indexed by *player_id* with columns:

        * ``expected_points_gw{N}`` for each future gameweek
        * ``total_expected_points`` – sum across horizon
        * ``variance`` – variance of recent per-GW scores
        """
        base_rates = self._base_rates()
        fdr_adj = self._fixture_adjustments()

        future_gws = list(range(self.current_gw + 1, self.current_gw + 1 + self.horizon))
        records: list[dict] = []

        for _, player in self.players.iterrows():
            pid = int(player["id"])
            base = base_rates.get(pid, float(player.get("ep_next", 2.0)))
            avail = self._availability_factor(player)
            var = self._variance(pid)

            row: dict = {"player_id": pid}
            total = 0.0
            for gw in future_gws:
                fdr_mult = fdr_adj.get((pid, gw), 1.0)
                ep = base * fdr_mult * avail
                ep = max(ep, 0.0)
                row[f"expected_points_gw{gw}"] = round(ep, 2)
                total += ep
            row["total_expected_points"] = round(total, 2)
            row["variance"] = round(var, 4)
            records.append(row)

        forecast = pd.DataFrame(records)
        return forecast

    # -- Internal helpers -----------------------------------------------------

    def _base_rates(self) -> dict[int, float]:
        """Compute exponentially-weighted mean points per GW for each player."""
        recent = self.history[
            self.history["gameweek"].between(
                self.current_gw - self.lookback, self.current_gw
            )
        ].copy()

        rates: dict[int, float] = {}
        for pid, grp in recent.groupby("player_id"):
            grp = grp.sort_values("gameweek")
            n = len(grp)
            if n == 0:
                continue
            weights = np.array([self.decay ** (n - 1 - i) for i in range(n)])
            weights /= weights.sum()
            rates[int(pid)] = float(np.dot(weights, grp["total_points"].values))
        return rates

    def _fixture_adjustments(self) -> dict[tuple[int, int], float]:
        """Map (player_id, gameweek) → FDR-based multiplier."""
        upcoming = self.fixtures[
            (self.fixtures["event"] > self.current_gw)
            & (self.fixtures["event"] <= self.current_gw + self.horizon)
        ].copy()

        team_to_players: dict[int, list[int]] = {}
        for _, p in self.players[["id", "team_id"]].iterrows():
            team_to_players.setdefault(int(p["team_id"]), []).append(int(p["id"]))

        adjustments: dict[tuple[int, int], float] = {}
        for _, fix in upcoming.iterrows():
            gw = int(fix["event"])
            # home team faces team_h_difficulty; away team faces team_a_difficulty
            for team_id, fdr in [
                (int(fix["team_h"]), int(fix["team_h_difficulty"])),
                (int(fix["team_a"]), int(fix["team_a_difficulty"])),
            ]:
                mult = 1.0 + FDR_SENSITIVITY * (FDR_NEUTRAL - fdr)
                for pid in team_to_players.get(team_id, []):
                    existing = adjustments.get((pid, gw), 1.0)
                    # If a team has a double GW, multiply additional fixture boost
                    adjustments[(pid, gw)] = existing * mult
        return adjustments

    @staticmethod
    def _availability_factor(player: pd.Series) -> float:
        """Scale expected points by the player's availability likelihood."""
        chance = player.get("chance_of_playing_next_round")
        if chance is None or pd.isna(chance):
            return 1.0
        return float(chance) / 100.0

    def _variance(self, player_id: int) -> float:
        """Variance of recent per-GW scores."""
        recent = self.history[
            (self.history["player_id"] == player_id)
            & (self.history["gameweek"].between(
                self.current_gw - self.lookback, self.current_gw
            ))
        ]
        if len(recent) < 2:
            return 0.0
        return float(recent["total_points"].var())
