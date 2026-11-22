"""Hypotheses about the model, re-tested every gameweek as data grows.

Each hypothesis is a walk-forward check (only data available at each cutoff is
used) with a bootstrap confidence interval, so a weekly run shows whether the
evidence is building or fading. Results are appended to a JSON log, one entry
per hypothesis per completed gameweek.

H1, "outliers in tight games" (suggested 2026-11-22)
    When a fixture is hard to score in, returns spread to less obvious
    players: lower-xPts attackers beat their predicted chance of a return,
    and high-xPts attackers fall short of theirs. In easy fixtures the stars
    beat theirs instead.

    Measured on MID/FWD player-weeks, split into fixture thirds by how many
    goals the team is expected to score versus its average fixture, and
    within each third into "star" (top half by xPts) and "fringe".
    ``ratio`` = actual returns ÷ predicted returns.

    * ``hard_gap``    = fringe ratio − star ratio in hard fixtures (H1: > 0)
    * ``easy_gap``    = the same in easy fixtures (H1: < 0)
    * ``interaction`` = hard_gap − easy_gap (H1: > 0); the headline number

    Verdict: "supported" when the 95% interval of ``interaction`` is above 0,
    "contradicted" when it's below 0, otherwise "not yet clear".

    If it holds, the model should make stars' attacking returns more
    sensitive to the fixture than "share × team goals" does, and fringe
    players' less.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .expected_points import ExpectedPointsModel, returned

H1_ID = "H1_outliers_in_tight_games"
H1_TEXT = ("In hard-to-score fixtures, lower-xPts attackers beat their predicted chance of a "
           "return and stars fall short; in easy fixtures stars beat theirs.")
MIN_CUTOFF = 4        # earlier cutoffs have too little data per player
BOOTSTRAP = 1000


def return_predictions(
    players: pd.DataFrame,
    history: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    scoring: dict,
    cutoffs: list[int],
) -> pd.DataFrame:
    """One row per (cutoff, player) predicting the next gameweek.

    Columns: ``cut``, ``gw``, ``player_id``, ``pos``, ``xpts``, ``p_return``
    (chance of a return), ``att_mult`` (team's expected goals in the fixture ÷
    its average; NaN in blanks and doubles), ``returned`` (actual).
    Only players who had played and were expected to score more than 1 point.
    """
    pos = dict(zip(players["id"], players["element_type"]))
    team_of = dict(zip(players["id"], players["team_id"]))
    h = history.copy()
    h["ret"] = returned(h, pos, scoring)
    actual = h.groupby(["player_id", "gameweek"])["ret"].any()

    rows = []
    for cut in cutoffs:
        fx = fixtures.copy()
        later = fx["event"] > cut
        for col in ("finished", "finished_provisional"):
            if col in fx.columns:
                fx.loc[later, col] = 0
        fx.loc[later, ["team_h_score", "team_a_score"]] = None
        model = ExpectedPointsModel(players, history[history["gameweek"] <= cut], fx, teams,
                                    cut, 1, scoring=scoring)
        fc = model.predict()
        r, team_fx, gw = model.ratings, model._team_fixtures(), cut + 1

        def att_mult(pid: int) -> float:
            t = team_of.get(pid)
            games = team_fx.get((t, gw), [])
            if len(games) != 1:
                return float("nan")
            opp, home = games[0]
            return r.expected_goals(t, opp, home)[0] / (r.mu * r.att.get(t, 1.0))

        fc = fc[(fc["apps"] > 0) & (fc["expected_points_next"] > 1)]
        for row in fc.itertuples(index=False):
            pid = int(row.player_id)
            rows.append({"cut": cut, "gw": gw, "player_id": pid, "pos": pos.get(pid),
                         "xpts": row.expected_points_next, "p_return": row.p_return_next,
                         "att_mult": att_mult(pid),
                         "returned": bool(actual.get((pid, gw), False))})
    return pd.DataFrame(rows)


def _gaps(d: pd.DataFrame) -> tuple[float, float]:
    """(hard_gap, easy_gap) for labelled player-weeks."""
    g = d.groupby(["fixture", "profile"], observed=True).agg(a=("returned", "sum"), p=("p_return", "sum"))
    ratio = (g["a"] / g["p"]).to_dict()
    gap = lambda tier: ratio.get((tier, "fringe"), np.nan) - ratio.get((tier, "star"), np.nan)  # noqa: E731
    return gap("hard"), gap("easy")


def check_outliers_in_tight_games(preds: pd.DataFrame, seed: int = 0) -> dict:
    """Run H1 on :func:`return_predictions` output. Returns a JSON-able dict."""
    d = preds[preds["pos"].isin([3, 4]) & preds["att_mult"].notna()].copy()
    if len(d) < 60:
        return {"id": H1_ID, "verdict": "not enough data", "n": int(len(d))}
    d["fixture"] = pd.qcut(d["att_mult"], 3, labels=["hard", "mid", "easy"])
    d["profile"] = d.groupby("fixture", observed=True)["xpts"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 2, labels=["fringe", "star"]))

    table = (d.groupby(["fixture", "profile"], observed=True)
             .agg(predicted=("p_return", "mean"), actual=("returned", "mean"), n=("returned", "size")))
    table["ratio"] = table["actual"] / table["predicted"]

    hard, easy = _gaps(d)
    rng = np.random.default_rng(seed)
    idx = np.arange(len(d))
    boot = []
    for _ in range(BOOTSTRAP):
        h_, e_ = _gaps(d.iloc[rng.choice(idx, len(idx))])
        boot.append((h_, e_, h_ - e_))
    boot = np.array(boot)
    ci = lambda k: [round(float(np.nanpercentile(boot[:, k], 2.5)), 3),  # noqa: E731
                    round(float(np.nanpercentile(boot[:, k], 97.5)), 3)]
    inter_ci = ci(2)
    verdict = ("supported" if inter_ci[0] > 0 else "contradicted" if inter_ci[1] < 0
               else "not yet clear")
    return {
        "id": H1_ID,
        "hypothesis": H1_TEXT,
        "gameweeks": [int(d["gw"].min()), int(d["gw"].max())],
        "n": int(len(d)),
        "hard_gap": round(hard, 3), "hard_gap_ci": ci(0),
        "easy_gap": round(easy, 3), "easy_gap_ci": ci(1),
        "interaction": round(hard - easy, 3), "interaction_ci": inter_ci,
        "verdict": verdict,
        "table": [{"fixture": f, "profile": p, **{k: round(float(v), 3) for k, v in r.items()}}
                  for (f, p), r in table.iterrows()],
    }


def log_result(path: Path | str, result: dict, through_gw: int) -> list[dict]:
    """Add *result* to the log (replacing an entry for the same hypothesis and
    gameweek) and return that hypothesis's entries, oldest first."""
    path = Path(path)
    log = json.loads(path.read_text()) if path.exists() else []
    entry = {**result, "through_gw": through_gw,
             "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    log = [e for e in log if not (e.get("id") == result["id"] and e.get("through_gw") == through_gw)]
    log.append(entry)
    log.sort(key=lambda e: (e.get("id", ""), e.get("through_gw", 0)))
    path.write_text(json.dumps(log, indent=2))
    return [e for e in log if e.get("id") == result["id"]]
