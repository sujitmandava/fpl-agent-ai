"""Tests for the weekly hypothesis checks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fpl_agent.forecast.hypotheses import H1_ID, check_outliers_in_tight_games, log_result


def _preds(fringe_hard_boost: float, n: int = 1200, seed: int = 1) -> pd.DataFrame:
    """Synthetic predictions; fringe players in hard fixtures return more than predicted."""
    rng = np.random.default_rng(seed)
    att = rng.uniform(0.7, 1.3, n)
    xpts = rng.uniform(1.5, 7.0, n)
    p = np.clip(0.05 * xpts, 0.05, 0.6)
    hard, fringe = att < np.quantile(att, 1 / 3), xpts < np.median(xpts)
    true_p = np.where(hard & fringe, np.clip(p * fringe_hard_boost, 0, 1), p)
    return pd.DataFrame({"cut": 5, "gw": rng.integers(5, 11, n), "player_id": np.arange(n),
                         "pos": 4, "xpts": xpts, "p_return": p, "att_mult": att,
                         "returned": rng.random(n) < true_p})


def test_h1_detects_a_strong_effect_and_not_a_null_one():
    assert check_outliers_in_tight_games(_preds(2.5))["verdict"] == "supported"
    assert check_outliers_in_tight_games(_preds(1.0))["verdict"] in ("not yet clear", "contradicted")


def test_h1_needs_data_and_logs_by_gameweek(tmp_path):
    small = check_outliers_in_tight_games(_preds(1.0, n=30))
    assert small["verdict"] == "not enough data"

    res = check_outliers_in_tight_games(_preds(1.0))
    log = tmp_path / "log.json"
    log_result(log, res, 10)
    log_result(log, res, 10)            # same week re-run replaces, not duplicates
    trend = log_result(log, res, 11)
    assert [e["through_gw"] for e in trend] == [10, 11]
    assert all(e["id"] == H1_ID for e in trend)
