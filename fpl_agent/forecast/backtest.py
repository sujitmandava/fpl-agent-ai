"""Walk-forward backtest of the expected-points model.

For each cutoff gameweek, the model is fit only on data available then
(later fixtures are marked unplayed) and asked to predict the next few
gameweeks. Predictions are compared with actual points, and with a naive
baseline: each player's points per match so far.
"""

from __future__ import annotations

import pandas as pd

from .expected_points import ExpectedPointsModel


def backtest_predictions(
    players: pd.DataFrame,
    history: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    scoring: dict,
    cutoffs: list[int],
    horizon: int = 3,
) -> pd.DataFrame:
    """One row per (cutoff, player, gameweek): ``actual``, ``xpts``, ``ppg_baseline``.

    Only players who matter are kept (either model expects more than 1 point).
    """
    rows = []
    for cut in cutoffs:
        gws = list(range(cut + 1, cut + 1 + horizon))
        fx = fixtures.copy()
        later = fx["event"] > cut
        for col in ("finished", "finished_provisional"):
            if col in fx.columns:
                fx.loc[later, col] = 0
        fx.loc[later, ["team_h_score", "team_a_score"]] = None
        past = history[history["gameweek"] <= cut]

        fc = ExpectedPointsModel(players, past, fx, teams, cut, horizon, scoring=scoring) \
            .predict().set_index("player_id")
        ppg = past[past["minutes"] > 0].groupby("player_id")["total_points"].mean()
        actual = (history[history["gameweek"].isin(gws)]
                  .groupby(["player_id", "gameweek"])["total_points"].sum())
        for (pid, gw), pts in actual.items():
            if pid not in fc.index:
                continue
            rows.append({"cut": cut, "player_id": pid, "gw": gw, "actual": pts,
                         "xpts": fc.at[pid, f"expected_points_gw{gw}"],
                         "ppg_baseline": float(ppg.get(pid, 0.0))})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    return d[(d["xpts"] > 1) | (d["ppg_baseline"] > 1)].reset_index(drop=True)


def top_picks_avg(d: pd.DataFrame, by: str, top_n: int = 20) -> float:
    """Average real score of the *top_n* players ranked by *by*, each gameweek."""
    top = d.sort_values(by, ascending=False).groupby(["cut", "gw"]).head(top_n)
    return float(top["actual"].mean())


def summarise(d: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """One row of metrics per model (``xpts`` and ``ppg_baseline``)."""
    if d.empty:
        return pd.DataFrame()
    out = []
    for model in ("xpts", "ppg_baseline"):
        out.append({
            "model": model,
            "mae": round((d[model] - d["actual"]).abs().mean(), 3),
            "correlation": round(d[model].corr(d["actual"]), 3),
            "bias": round((d[model] - d["actual"]).mean(), 3),
            f"top{top_n}_actual_avg": round(top_picks_avg(d, model, top_n), 2),
            "predictions": len(d),
        })
    return pd.DataFrame(out)


def calibration(d: pd.DataFrame, edges=(0, 2, 4, 6, 8, float("inf"))) -> pd.DataFrame:
    """Group predictions into bands and compare with what those players scored."""
    labels = [f"{lo:g}–{hi:g}" if hi != float("inf") else f"{lo:g}+"
              for lo, hi in zip(edges[:-1], edges[1:])]
    band = pd.cut(d["xpts"], list(edges), labels=labels, right=False)
    g = d.groupby(band, observed=True)
    return pd.DataFrame({"predicted": g["xpts"].mean(), "actual": g["actual"].mean(),
                         "count": g.size()})


def by_window(d: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Per-cutoff accuracy, model vs baseline."""
    rows = []
    for cut, g in d.groupby("cut"):
        rows.append({
            "cut": cut, "first_gw": int(g["gw"].min()), "last_gw": int(g["gw"].max()),
            "xpts_mae": (g["xpts"] - g["actual"]).abs().mean(),
            "ppg_mae": (g["ppg_baseline"] - g["actual"]).abs().mean(),
            "xpts_top": top_picks_avg(g, "xpts", top_n),
            "ppg_top": top_picks_avg(g, "ppg_baseline", top_n),
        })
    return pd.DataFrame(rows)


def backtest(
    players: pd.DataFrame,
    history: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    scoring: dict,
    cutoffs: list[int],
    horizon: int = 3,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return one row of metrics per model (``xpts`` and ``ppg_baseline``)."""
    d = backtest_predictions(players, history, fixtures, teams, scoring, cutoffs, horizon)
    return summarise(d, top_n)
