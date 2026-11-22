"""Walk-forward backtest of the expected-points model.

For each cutoff gameweek, the model is fit only on data available then
(later fixtures are marked unplayed) and asked to predict the next few
gameweeks. Predictions are compared with actual points, and with a naive
baseline: each player's points per match so far.
"""

from __future__ import annotations

import pandas as pd

from .expected_points import ExpectedPointsModel


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
            rows.append({"cut": cut, "gw": gw, "actual": pts,
                         "xpts": fc.at[pid, f"expected_points_gw{gw}"],
                         "ppg_baseline": float(ppg.get(pid, 0.0))})
    d = pd.DataFrame(rows)
    if d.empty:
        return pd.DataFrame()
    d = d[(d["xpts"] > 1) | (d["ppg_baseline"] > 1)]   # players who matter

    out = []
    for model in ("xpts", "ppg_baseline"):
        top = d.sort_values(model, ascending=False).groupby(["cut", "gw"]).head(top_n)
        out.append({
            "model": model,
            "mae": round((d[model] - d["actual"]).abs().mean(), 3),
            "correlation": round(d[model].corr(d["actual"]), 3),
            "bias": round((d[model] - d["actual"]).mean(), 3),
            f"top{top_n}_actual_avg": round(top["actual"].mean(), 2),
            "predictions": len(d),
        })
    return pd.DataFrame(out)
