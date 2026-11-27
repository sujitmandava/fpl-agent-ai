"""Walk-forward test of the ``chase`` setting.

For each past gameweek *w*:

1. Fit the xPts model on data up to *w − 1* and forecast *w*.
2. Fit the pair correlations (``forecast.correlation``) on the forecast
   errors of the weeks before *w* only.
3. Pick a fresh £100m squad for *w* (Free Hit style, so every chase level
   starts from the same place) at each chase level.
4. Score the XI with what really happened (captain doubled, no auto-subs).

Two questions:

* **Does the spread model hold out of sample?** Pair correlations fitted on
  earlier weeks vs measured on the week itself, and how far each XI's real
  score landed from its xPts relative to the predicted spread.
* **What does chasing cost?** xPts and real points per chase level.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from fpl_agent.forecast.correlation import PAIR_CORR, fit_pair_correlations, pair_kind, role
from fpl_agent.forecast.expected_points import ExpectedPointsModel

from .milp import TeamState, optimize

FRESH_BUDGET = 1000
ERROR_MIN_XPTS = 2.0   # same filter the published correlations were measured with


def _masked_fixtures(fixtures: pd.DataFrame, cut: int) -> pd.DataFrame:
    fx = fixtures.copy()
    later = fx["event"] > cut
    for col in ("finished", "finished_provisional"):
        if col in fx.columns:
            fx.loc[later, col] = 0
    fx.loc[later, ["team_h_score", "team_a_score"]] = None
    return fx


def _week_errors(forecast: pd.DataFrame, history: pd.DataFrame, players: pd.DataFrame,
                 gw: int) -> pd.DataFrame:
    """One row per player who played in *gw*: fixture, side, position, xPts, error."""
    h = history[(history["gameweek"] == gw) & (history["minutes"] > 0)]
    h = h.groupby(["player_id", "fixture", "was_home"], as_index=False)["total_points"].sum()
    d = h.merge(forecast[["player_id", f"expected_points_gw{gw}"]], on="player_id")
    d = d.merge(players[["id", "element_type"]], left_on="player_id", right_on="id")
    d = d.rename(columns={f"expected_points_gw{gw}": "xpts"})
    # A double's xPts covers both matches; split it evenly for the per-match error.
    n = d.groupby("player_id")["fixture"].transform("count")
    d["xpts"] = d["xpts"] / n
    d["error"] = d["total_points"] - d["xpts"]
    d["gw"] = gw
    return d[["gw", "player_id", "fixture", "was_home", "element_type", "xpts", "error"]]


def _pair_table(errors: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (gw, _), g in errors.groupby(["gw", "fixture"]):
        recs = list(zip(g["was_home"], g["element_type"].map(role), g["error"]))
        for a in range(len(recs)):
            for b in range(a + 1, len(recs)):
                (ha, ra, ea), (hb, rb, eb) = recs[a], recs[b]
                rows.append((gw, "same" if ha == hb else "opp", pair_kind(ra, rb), ea, eb))
    return pd.DataFrame(rows, columns=["gw", "side", "kind", "a", "b"])


def run_chase_backtest(
    players: pd.DataFrame,
    history: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    scoring: dict,
    weeks: list[int],
    chase_levels: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2),
) -> dict[str, pd.DataFrame]:
    """Return ``{"lineups", "summary", "pairs"}`` (see module docstring).

    *weeks* are the gameweeks to test; the first one is used only to start the
    error history, so it gets no lineup.
    """
    actual = history.groupby(["player_id", "gameweek"])["total_points"].sum()
    errors: list[pd.DataFrame] = []
    lineups = []
    for w in weeks:
        cut = w - 1
        fx = _masked_fixtures(fixtures, cut)
        fc = ExpectedPointsModel(players, history[history["gameweek"] <= cut], fx, teams, cut,
                                 horizon=1, scoring=scoring).predict()
        week_err = _week_errors(fc, history, players, w)
        prior = pd.concat(errors) if errors else None
        errors.append(week_err)
        if prior is None:
            continue
        corr = fit_pair_correlations(prior[prior["xpts"] >= ERROR_MIN_XPTS])
        state = TeamState(current_squad=[], selling_prices={}, bank=FRESH_BUDGET, free_transfers=15)
        for level in chase_levels:
            r = optimize(state, fc, players, horizon=1, unlimited_transfers=True,
                         fixtures=fx, chase=level, pair_corr=corr, time_limit=120)
            got = sum(actual.get((i, w), 0) for i in r.starting_xi) + actual.get((r.captain_id, w), 0)
            lineups.append({"gw": w, "chase": level, "xpts": r.next_gw_points,
                            "sd": r.spread[w], "actual": float(got)})

    lu = pd.DataFrame(lineups)
    if lu.empty:
        return {"lineups": lu, "summary": pd.DataFrame(), "pairs": pd.DataFrame()}
    lu["error"] = lu["actual"] - lu["xpts"]
    lu["z"] = lu["error"] / lu["sd"]
    summary = lu.groupby("chase").agg(
        weeks=("gw", "count"), xpts=("xpts", "mean"), actual=("actual", "mean"),
        predicted_sd=("sd", "mean"), realised_sd=("error", "std"),
        best_week=("actual", "max"), worst_week=("actual", "min"),
        z_sd=("z", "std"),
    ).round(2).reset_index()

    # Out-of-sample pair check: early half fits, later half tests.
    all_err = pd.concat(errors)
    all_err = all_err[all_err["xpts"] >= ERROR_MIN_XPTS]
    split = weeks[len(weeks) // 2]
    early = fit_pair_correlations(all_err[all_err["gw"] < split])
    pt = _pair_table(all_err[all_err["gw"] >= split])
    pair_rows = []
    for key, g in pt.groupby(["side", "kind"]):
        late = float(np.corrcoef(g["a"], g["b"])[0, 1]) if len(g) > 2 else math.nan
        pair_rows.append({"side": key[0], "kind": key[1], "published": PAIR_CORR[key],
                          f"fit_before_gw{split}": round(early[key], 3),
                          f"measured_gw{split}+": round(late, 3), "pairs": len(g)})
    return {"lineups": lu, "summary": summary, "pairs": pd.DataFrame(pair_rows)}
