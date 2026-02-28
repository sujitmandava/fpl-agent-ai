"""Mixed-Integer Linear Program for FPL squad optimisation.

Formulation
-----------
* **Decision variables**: binary ``x[i]`` = 1 if player *i* is in the squad.
* **Objective**: maximise  Σ  x[i] · effective_score[i]  − 4 · hits
  where ``effective_score`` = expected_points + retention_bonus (if owned)
  + consistency_bonus (low-variance reward).
* **Constraints**:
  - Exactly 15 players selected.
  - Exactly 2 GK, 5 DEF, 5 MID, 3 FWD.
  - Budget ≤ remaining budget (current squad selling prices + bank).
  - At most 3 players from any single club.
  - Transfer-balance: new squad differs from current squad by ≤ free_transfers
    without a hit, otherwise 4-pt penalty each.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd
from pulp import (
    LpMaximize,
    LpProblem,
    LpVariable,
    lpSum,
    value,
)

logger = logging.getLogger(__name__)

POSITION_LIMITS = {1: 2, 2: 5, 3: 5, 4: 3}  # element_type → count
MAX_PER_CLUB = 3
SQUAD_SIZE = 15
TRANSFER_HIT = 4  # points cost per extra transfer

# Bonus EP added to current-squad players so the solver keeps consistent
# performers unless a replacement is a clear upgrade.
RETENTION_BONUS = 2.0

# Reward for consistency: players with low variance (reliable returners)
# receive up to this many bonus EP.  Scaled as bonus × (1 − norm_variance).
CONSISTENCY_BONUS = 1.5


@dataclass
class TeamState:
    """Snapshot of the manager's current squad and budget situation."""

    current_squad: list[int]            # player_ids currently owned
    selling_prices: dict[int, int]      # player_id → selling price (×10)
    bank: int = 0                       # remaining budget (×10)
    free_transfers: int = 1

    @property
    def total_budget(self) -> int:
        return sum(self.selling_prices.get(pid, 0) for pid in self.current_squad) + self.bank


@dataclass
class OptimizationResult:
    """Output of the optimizer."""

    selected_ids: list[int]
    transfers_in: list[int]
    transfers_out: list[int]
    total_expected_points: float
    transfer_cost: int                  # total hit points
    solver_status: str
    details: pd.DataFrame = field(default_factory=pd.DataFrame)


def optimize(
    team_state: TeamState,
    forecast: pd.DataFrame,
    players: pd.DataFrame,
    horizon: int = 6,
    retention_bonus: float = RETENTION_BONUS,
    consistency_bonus: float = CONSISTENCY_BONUS,
) -> OptimizationResult:
    """Solve the squad-selection MILP and return an `OptimizationResult`.

    Parameters
    ----------
    team_state : TeamState
        Current squad, selling prices, bank, and free transfers.
    forecast : pd.DataFrame
        Must contain ``player_id``, ``total_expected_points``, and
        optionally ``variance``.
    players : pd.DataFrame
        Full players table (needs ``id``, ``element_type``, ``team_id``, ``now_cost``).
    horizon : int
        Forecast horizon (used only for labelling).
    retention_bonus : float
        Extra EP credited to currently-owned players so the solver
        prefers keeping consistent returners (default 2.0).
    consistency_bonus : float
        Max bonus for low-variance players (default 1.5).
    """
    forecast_cols = ["player_id", "total_expected_points"]
    if "variance" in forecast.columns:
        forecast_cols.append("variance")

    merged = players[["id", "element_type", "team_id", "now_cost", "web_name"]].merge(
        forecast[forecast_cols],
        left_on="id",
        right_on="player_id",
        how="inner",
    )
    merged = merged[merged["total_expected_points"] > 0].copy()
    merged = merged.reset_index(drop=True)

    budget = team_state.total_budget
    current_set = set(team_state.current_squad)

    # -- Build effective score used by the solver ----------------------------
    # 1) Retention bonus: reward keeping current squad members
    merged["retention"] = merged["id"].apply(
        lambda pid: retention_bonus if pid in current_set else 0.0
    )
    # 2) Consistency bonus: reward low-variance (reliable) players
    if "variance" in merged.columns:
        max_var = merged["variance"].max()
        if max_var > 0:
            merged["consistency"] = consistency_bonus * (1.0 - merged["variance"] / max_var)
        else:
            merged["consistency"] = consistency_bonus
    else:
        merged["consistency"] = 0.0

    merged["effective_score"] = (
        merged["total_expected_points"]
        + merged["retention"]
        + merged["consistency"]
    )

    prob = LpProblem("FPL_Squad_Selection", LpMaximize)

    # Binary selection variables
    x = {
        row["id"]: LpVariable(f"x_{row['id']}", cat="Binary")
        for _, row in merged.iterrows()
    }

    # Transfer-out indicator: t[i]=1 if player *i* is in current squad but NOT selected
    t_out = {
        pid: LpVariable(f"tout_{pid}", cat="Binary")
        for pid in current_set
        if pid in x
    }
    # Also handle players in current squad but absent from merged (force sell)
    forced_out = current_set - set(x.keys())

    # Number of transfers out
    num_transfers = lpSum(t_out.values()) + len(forced_out)

    # Hits = max(0, num_transfers − free_transfers)
    # Linearise using auxiliary variable h ≥ 0
    h = LpVariable("hits", lowBound=0, cat="Integer")
    prob += h >= num_transfers - team_state.free_transfers

    # Objective: effective score (EP + retention + consistency) minus hit cost
    prob += (
        lpSum(x[row["id"]] * row["effective_score"] for _, row in merged.iterrows())
        - TRANSFER_HIT * h,
        "objective",
    )

    # -- Constraints ----------------------------------------------------------

    # Squad size
    prob += lpSum(x.values()) == SQUAD_SIZE, "squad_size"

    # Positional limits
    for pos, count in POSITION_LIMITS.items():
        prob += (
            lpSum(
                x[row["id"]]
                for _, row in merged[merged["element_type"] == pos].iterrows()
            )
            == count,
            f"pos_{pos}",
        )

    # Budget
    prob += (
        lpSum(x[row["id"]] * row["now_cost"] for _, row in merged.iterrows())
        <= budget,
        "budget",
    )

    # Max per club
    for team_id in merged["team_id"].unique():
        prob += (
            lpSum(
                x[row["id"]]
                for _, row in merged[merged["team_id"] == team_id].iterrows()
            )
            <= MAX_PER_CLUB,
            f"club_{team_id}",
        )

    # Link transfer-out variables: t_out[i] = 1  ⟺  x[i] = 0 for current squad members
    for pid, tv in t_out.items():
        prob += tv >= 1 - x[pid], f"tout_link_lb_{pid}"
        prob += tv <= 1 - x[pid], f"tout_link_ub_{pid}"

    # -- Solve ----------------------------------------------------------------

    prob.solve()
    status = prob.status

    selected = [pid for pid, var in x.items() if value(var) == 1]
    transfers_in = [pid for pid in selected if pid not in current_set]
    transfers_out_ids = [pid for pid in current_set if pid not in set(selected)]

    details = merged[merged["id"].isin(selected)].copy()
    details = details.sort_values("total_expected_points", ascending=False)

    total_ep = sum(
        merged.loc[merged["id"] == pid, "total_expected_points"].iloc[0]
        for pid in selected
        if pid in merged["id"].values
    )

    hit_val = int(value(h)) if value(h) else 0

    logger.info(
        "Solver status=%s  selected=%d  transfers_in=%d  transfers_out=%d  hits=%d",
        status, len(selected), len(transfers_in), len(transfers_out_ids), hit_val,
    )

    return OptimizationResult(
        selected_ids=selected,
        transfers_in=transfers_in,
        transfers_out=transfers_out_ids,
        total_expected_points=round(total_ep, 2),
        transfer_cost=hit_val * TRANSFER_HIT,
        solver_status=str(status),
        details=details,
    )
