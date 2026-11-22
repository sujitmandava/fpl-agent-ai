"""Mixed-Integer Linear Program for FPL squad optimisation.

Formulation
-----------
Decision variables (binary):

* ``x[i]``    – player *i* is in the 15-man squad after transfers.
* ``y[i,g]``  – player *i* starts in gameweek *g*.
* ``c[i,g]``  – player *i* is captain in gameweek *g*.

Objective (maximise)::

    Σ_g  w_g · Σ_i  EP[i,g] · ( y[i,g] + c[i,g] + bench_weight · (x[i] − y[i,g]) )
      − 4 · hits − ft_value · free_transfers_used

* ``w_g = discount^(g − first_gw)`` – later gameweeks are less certain and the
  squad will change before then.
* Captain points count twice (``y + c``); bench players count only a little
  (``bench_weight``), standing in for auto-subs. Counting all 15 equally (the
  old formulation) spreads money across the bench and sells premiums.
* ``ft_value`` is what a saved free transfer is worth, charged for every
  transfer that lowers next week's free-transfer count. Marginal moves are
  skipped and hits must clear 4 + ft_value. With 5 banked, the first transfer
  is free of this cost (saving it would exceed the cap).

Constraints: 15 players, 2/5/5/3 by position, ≤3 per club, budget, and in
every gameweek a valid XI (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD) with one captain.
Budget counts *selling* prices for kept players and current prices for buys.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import pandas as pd
from pulp import (
    PULP_CBC_CMD,
    LpMaximize,
    LpProblem,
    LpStatus,
    LpVariable,
    lpSum,
    value,
)

logger = logging.getLogger(__name__)

POSITION_LIMITS = {1: 2, 2: 5, 3: 5, 4: 3}  # element_type → squad count
XI_LIMITS = {1: (1, 1), 2: (3, 5), 3: (2, 5), 4: (1, 3)}  # element_type → (min, max) starters
MAX_PER_CLUB = 3
SQUAD_SIZE = 15
XI_SIZE = 11
TRANSFER_HIT = 4  # points cost per extra transfer
MAX_FREE_TRANSFERS = 5

BENCH_WEIGHT = 0.1
DISCOUNT = 0.85
FT_VALUE = 1.0
# Candidate pool per position (plus best value-for-money picks and the current
# squad). Keeps the MILP small without excluding realistic options.
POOL_TOP_EP = 40
POOL_TOP_VALUE = 15

_GW_COL = re.compile(r"^expected_points_gw(\d+)$")


class OptimizationError(RuntimeError):
    """Raised when the solver does not return an optimal solution."""


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
    total_expected_points: float        # Σ horizon EP over all 15 selected players
    transfer_cost: int                  # total hit points
    solver_status: str
    details: pd.DataFrame = field(default_factory=pd.DataFrame)
    starting_xi: list[int] = field(default_factory=list)   # first gameweek
    captain_id: int | None = None
    vice_captain_id: int | None = None
    gameweeks: list[int] = field(default_factory=list)
    next_gw_points: float = 0.0         # XI + captain, first gameweek
    horizon_points: float = 0.0         # XI + captain summed over horizon (undiscounted)
    objective: float = 0.0
    lineups: dict[int, list[int]] = field(default_factory=dict)   # gw → XI
    captains: dict[int, int] = field(default_factory=dict)        # gw → captain
    bench_points: dict[int, float] = field(default_factory=dict)  # gw → EP of the 4 subs
    captain_points: dict[int, float] = field(default_factory=dict)  # gw → captain's EP


def gameweek_columns(forecast: pd.DataFrame) -> list[tuple[int, str]]:
    """Return ``[(gw, column)]`` for per-gameweek EP columns, sorted by gw."""
    cols = [(int(m.group(1)), c) for c in forecast.columns if (m := _GW_COL.match(c))]
    return sorted(cols)


def optimize(
    team_state: TeamState,
    forecast: pd.DataFrame,
    players: pd.DataFrame,
    horizon: int | None = None,
    bench_weight: float = BENCH_WEIGHT,
    discount: float = DISCOUNT,
    ft_value: float = FT_VALUE,
    max_transfers: int | None = None,
    unlimited_transfers: bool = False,
    locked: set[int] | None = None,
    banned: set[int] | None = None,
    time_limit: int = 60,
) -> OptimizationResult:
    """Solve the squad-selection MILP and return an `OptimizationResult`.

    Parameters
    ----------
    team_state : TeamState
        Current squad, selling prices, bank, and free transfers.
    forecast : DataFrame
        ``player_id`` plus ``expected_points_gw{N}`` columns (from
        ``ExpectedPointsModel``). If those are absent, ``total_expected_points``
        is used as a single period.
    players : DataFrame
        Needs ``id``, ``element_type``, ``team_id``, ``now_cost``, ``web_name``.
    horizon : int, optional
        Use only the first *horizon* gameweek columns.
    bench_weight, discount, ft_value : float
        See module docstring.
    max_transfers : int, optional
        Hard cap on transfers (0 evaluates the current squad as-is).
    unlimited_transfers : bool
        Wildcard / Free Hit: no hits and no free-transfer cost.
    locked, banned : set of player ids
        Players that must be in / must not be in the squad (from memory).
    """
    locked = set(locked or ())
    banned = set(banned or ())
    gw_cols = gameweek_columns(forecast)
    if horizon:
        gw_cols = gw_cols[:horizon]
    if not gw_cols:
        gw_cols = [(0, "total_expected_points")]
    gws = [g for g, _ in gw_cols]
    ep_cols = [c for _, c in gw_cols]

    keep_cols = ["player_id", *ep_cols]
    if "total_expected_points" in forecast.columns and "total_expected_points" not in keep_cols:
        keep_cols.append("total_expected_points")
    merged = players[["id", "element_type", "team_id", "now_cost", "web_name"]].merge(
        forecast[keep_cols], left_on="id", right_on="player_id", how="inner",
    )
    if "total_expected_points" not in merged.columns:
        merged["total_expected_points"] = merged[ep_cols].sum(axis=1)

    current_set = set(team_state.current_squad)
    merged = _candidate_pool(merged, current_set | locked).reset_index(drop=True)
    missing = current_set - set(merged["id"])
    if missing:
        raise OptimizationError(f"Current squad players missing from the player table: {missing}")

    # Cost: selling price for players you already own, market price otherwise.
    merged["cost"] = [
        team_state.selling_prices.get(pid, now) if pid in current_set else now
        for pid, now in zip(merged["id"], merged["now_cost"])
    ]
    budget = team_state.total_budget
    weights = {g: discount ** k for k, g in enumerate(gws)}

    ids = merged["id"].tolist()
    pos = dict(zip(merged["id"], merged["element_type"]))
    club = dict(zip(merged["id"], merged["team_id"]))
    cost = dict(zip(merged["id"], merged["cost"]))
    ep = {(pid, g): float(v) for g, col in gw_cols for pid, v in zip(merged["id"], merged[col])}

    prob = LpProblem("FPL_Squad_Selection", LpMaximize)
    x = {i: LpVariable(f"x_{i}", cat="Binary") for i in ids}
    y = {(i, g): LpVariable(f"y_{i}_{g}", cat="Binary") for i in ids for g in gws}
    c = {(i, g): LpVariable(f"c_{i}_{g}", cat="Binary") for i in ids for g in gws}

    # Transfers = owned players not kept.
    num_transfers = lpSum(1 - x[i] for i in current_set)
    h = LpVariable("hits", lowBound=0, cat="Integer")
    # Transfers that reduce next week's free transfers. At the cap, one
    # transfer is "use it or lose it" and costs nothing to make.
    ft_lost = LpVariable("ft_lost", lowBound=0)
    if unlimited_transfers:
        prob += h == 0
        prob += ft_lost == 0
    else:
        prob += h >= num_transfers - team_state.free_transfers
        wasted = max(0, team_state.free_transfers + 1 - MAX_FREE_TRANSFERS)
        prob += ft_lost >= num_transfers - wasted

    points = lpSum(
        weights[g] * ep[i, g] * (y[i, g] + c[i, g] + bench_weight * (x[i] - y[i, g]))
        for i in ids for g in gws
    )
    prob += points - TRANSFER_HIT * h - ft_value * ft_lost, "objective"

    # -- Squad constraints ----------------------------------------------------
    prob += lpSum(x.values()) == SQUAD_SIZE, "squad_size"
    for p, count in POSITION_LIMITS.items():
        prob += lpSum(x[i] for i in ids if pos[i] == p) == count, f"pos_{p}"
    prob += lpSum(x[i] * cost[i] for i in ids) <= budget, "budget"
    for team_id in set(club.values()):
        prob += lpSum(x[i] for i in ids if club[i] == team_id) <= MAX_PER_CLUB, f"club_{team_id}"
    if max_transfers is not None:
        prob += num_transfers <= max_transfers, "max_transfers"
    for i in locked & set(ids):
        if max_transfers == 0 and i not in current_set:
            continue  # baseline can't buy anyone
        prob += x[i] == 1, f"locked_{i}"
    for i in banned & set(ids):
        if max_transfers == 0 and i in current_set:
            continue  # baseline evaluation keeps the squad as-is
        prob += x[i] == 0, f"banned_{i}"

    # -- Lineup constraints per gameweek -------------------------------------
    for g in gws:
        prob += lpSum(y[i, g] for i in ids) == XI_SIZE, f"xi_{g}"
        prob += lpSum(c[i, g] for i in ids) == 1, f"cap_{g}"
        for p, (lo, hi) in XI_LIMITS.items():
            starters = lpSum(y[i, g] for i in ids if pos[i] == p)
            prob += starters >= lo, f"xi_min_{p}_{g}"
            prob += starters <= hi, f"xi_max_{p}_{g}"
        for i in ids:
            prob += y[i, g] <= x[i], f"start_owned_{i}_{g}"
            prob += c[i, g] <= y[i, g], f"cap_starts_{i}_{g}"

    # -- Solve ----------------------------------------------------------------
    prob.solve(PULP_CBC_CMD(msg=False, timeLimit=time_limit))
    status = LpStatus[prob.status]
    if status != "Optimal":
        raise OptimizationError(f"Solver returned status '{status}'.")

    chosen = lambda var: (value(var) or 0) > 0.5  # noqa: E731 – tolerate float noise
    selected = [i for i in ids if chosen(x[i])]
    first = gws[0]
    xi = [i for i in selected if chosen(y[i, first])]
    captain = next(i for i in xi if chosen(c[i, first]))
    others = sorted((i for i in xi if i != captain), key=lambda i: ep[i, first], reverse=True)
    vice = others[0] if others else captain

    transfers_in = [i for i in selected if i not in current_set]
    transfers_out = [i for i in team_state.current_squad if i not in set(selected)]
    hit_val = int(round(value(h) or 0))

    next_pts = sum(ep[i, first] for i in xi) + ep[captain, first]
    horizon_pts = sum(
        ep[i, g] * ((1 if chosen(y[i, g]) else 0) + (1 if chosen(c[i, g]) else 0))
        for i in selected for g in gws
    )

    lineups = {g: [i for i in selected if chosen(y[i, g])] for g in gws}
    captains = {g: next(i for i in lineups[g] if chosen(c[i, g])) for g in gws}
    bench_points = {g: round(sum(ep[i, g] for i in selected if i not in lineups[g]), 2) for g in gws}
    captain_points = {g: round(ep[captains[g], g], 2) for g in gws}

    details = merged[merged["id"].isin(selected)].sort_values("total_expected_points", ascending=False)
    total_ep = float(details["total_expected_points"].sum())

    logger.info(
        "Solver status=%s transfers=%d hits=%d next_gw=%.1f horizon=%.1f",
        status, len(transfers_in), hit_val, next_pts, horizon_pts,
    )

    return OptimizationResult(
        selected_ids=selected,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        total_expected_points=round(total_ep, 2),
        transfer_cost=hit_val * TRANSFER_HIT,
        solver_status=status,
        details=details,
        starting_xi=xi,
        captain_id=captain,
        vice_captain_id=vice,
        gameweeks=gws,
        next_gw_points=round(next_pts, 2),
        horizon_points=round(horizon_pts, 2),
        objective=round(value(prob.objective) or 0.0, 2),
        lineups=lineups,
        captains=captains,
        bench_points=bench_points,
        captain_points=captain_points,
    )


def _candidate_pool(merged: pd.DataFrame, current_set: set[int]) -> pd.DataFrame:
    """Current squad + top players by EP and by EP per £ in each position."""
    keep = merged["id"].isin(current_set)
    positive = merged[merged["total_expected_points"] > 0]
    for _, grp in positive.groupby("element_type"):
        top_ep = grp.nlargest(POOL_TOP_EP, "total_expected_points")["id"]
        value_ratio = grp["total_expected_points"] / grp["now_cost"]
        top_value = grp.loc[value_ratio.nlargest(POOL_TOP_VALUE).index, "id"]
        keep |= merged["id"].isin(top_ep) | merged["id"].isin(top_value)
    return merged[keep]
