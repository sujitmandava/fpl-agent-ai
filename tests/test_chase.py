"""Tests for the chase setting: same-match covariance and the optimiser term."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_agent.forecast.correlation import (
    PAIR_CORR,
    fit_pair_correlations,
    lineup_sd,
    opponents_by_gw,
    pair_covariances,
    score_var,
)
from fpl_agent.league import suggested_chase
from fpl_agent.optimizer.milp import TeamState, optimize


def _fixtures(pairs: list[tuple[int, int]], gw: int = 1) -> pd.DataFrame:
    return pd.DataFrame([{"event": gw, "team_h": h, "team_a": a} for h, a in pairs])


def test_pair_covariances_signs_and_scale():
    players = pd.DataFrame([
        {"id": 1, "element_type": 2, "team_id": 1},   # DEF, team 1
        {"id": 2, "element_type": 2, "team_id": 1},   # DEF, team 1
        {"id": 3, "element_type": 4, "team_id": 2},   # FWD, team 2 (opponent)
        {"id": 4, "element_type": 4, "team_id": 3},   # FWD, team 3 (other match)
    ])
    opps = opponents_by_gw(_fixtures([(1, 2), (3, 4)]), [1])[1]
    cov = {frozenset((i, j)): c for i, j, c in pair_covariances(players, {1: 4, 2: 4, 3: 5, 4: 5}, opps)}
    assert cov[frozenset((1, 2))] == pytest.approx(PAIR_CORR[("same", "DD")] * score_var(4))
    assert cov[frozenset((1, 3))] < 0 and cov[frozenset((2, 3))] < 0
    assert frozenset((1, 4)) not in cov           # different matches: uncorrelated


def test_lineup_sd_counts_captain_twice():
    pairs = [(1, 2, 3.0)]
    base = lineup_sd([1, 2], None, {1: 4, 2: 4}, pairs)
    capped = lineup_sd([1, 2], 1, {1: 4, 2: 4}, pairs)
    assert capped > base


def test_fit_pair_correlations_recovers_sign():
    rows = []
    for f in range(40):
        e = (-1) ** f * 3.0
        rows += [{"fixture": f, "was_home": True, "element_type": 2, "error": e},
                 {"fixture": f, "was_home": True, "element_type": 2, "error": e + 0.1},
                 {"fixture": f, "was_home": False, "element_type": 4, "error": -e}]
    fitted = fit_pair_correlations(pd.DataFrame(rows))
    assert fitted[("same", "DD")] > 0.9
    assert fitted[("opp", "AD")] < -0.9


def _pool():
    """A tiny league: team 1 v team 2, team 3 v team 4, plenty of filler."""
    rows, fc = [], []
    pid = 0
    for team in (1, 2, 3, 4, 5, 6):
        for pos, n in ((1, 2), (2, 5), (3, 5), (4, 3)):
            for _ in range(n):
                pid += 1
                rows.append({"id": pid, "web_name": f"P{pid}", "element_type": pos,
                             "team_id": team, "now_cost": 50})
                # Distinct values: exact ties make the solver crawl.
                fc.append({"player_id": pid, "expected_points_gw1": 1.0 + (pid * 37 % 100) / 100})
    players, forecast = pd.DataFrame(rows), pd.DataFrame(fc)
    fixtures = _fixtures([(1, 2), (3, 4), (5, 6)])
    return players, forecast, fixtures


def _clash_setup(striker_xpts: float):
    """Two team-1 defenders, a team-2 striker facing them, and forwards elsewhere at 5.9."""
    players, fc, fixtures = _pool()
    p = players.set_index("id")
    t1_defs = p[(p.team_id == 1) & (p.element_type == 2)].index[:2].tolist()
    striker = int(p[(p.team_id == 2) & (p.element_type == 4)].index[0])
    others = p[(p.team_id >= 3) & (p.element_type == 4)].index.tolist()
    fc.loc[fc.player_id.isin(t1_defs), "expected_points_gw1"] = 6.0
    fc.loc[fc.player_id.isin(others), "expected_points_gw1"] = 5.9
    fc.loc[fc.player_id == striker, "expected_points_gw1"] = striker_xpts
    # Captaincy would otherwise decide it; give the armband to someone else.
    cap = int(p[(p.team_id == 5) & (p.element_type == 3)].index[0])
    fc.loc[fc.player_id == cap, "expected_points_gw1"] = 12.0
    state = TeamState(current_squad=[], selling_prices={}, bank=1000, free_transfers=15)
    return players, fc, fixtures, state, t1_defs, striker


def test_chase_avoids_a_striker_facing_your_defenders():
    players, fc, fixtures, state, t1_defs, striker = _clash_setup(6.05)
    plain = optimize(state, fc, players, unlimited_transfers=True, consistency=0, fixtures=fixtures)
    assert striker in plain.starting_xi and set(t1_defs) <= set(plain.starting_xi)
    chased = optimize(state, fc, players, unlimited_transfers=True, consistency=0,
                      fixtures=fixtures, chase=0.05)
    assert set(t1_defs) <= set(chased.starting_xi)
    assert striker not in chased.starting_xi
    assert chased.spread[1] > plain.spread[1]
    assert chased.next_gw_points < plain.next_gw_points   # spread costs a little xPts


def test_negative_chase_hedges():
    """Protecting a lead: break up the defensive stack or add the striker facing it."""
    players, fc, fixtures, state, t1_defs, striker = _clash_setup(5.85)
    plain = optimize(state, fc, players, unlimited_transfers=True, consistency=0, fixtures=fixtures)
    assert striker not in plain.starting_xi
    hedged = optimize(state, fc, players, unlimited_transfers=True, consistency=0,
                      fixtures=fixtures, chase=-0.05)
    xi = set(hedged.starting_xi)
    assert striker in xi or not set(t1_defs) <= xi
    assert hedged.spread[1] < plain.spread[1]


def test_chase_zero_matches_no_fixtures():
    players, fc, fixtures = _pool()
    fc["expected_points_gw1"] = [2 + (i % 7) * 0.3 for i in range(len(fc))]
    state = TeamState(current_squad=[], selling_prices={}, bank=1000, free_transfers=15)
    a = optimize(state, fc, players, unlimited_transfers=True, fixtures=fixtures, chase=0)
    b = optimize(state, fc, players, unlimited_transfers=True)
    assert a.next_gw_points == pytest.approx(b.next_gw_points)
    assert a.spread and not b.spread


def test_suggested_chase():
    assert suggested_chase(gap=40, expected_edge=0, weekly_sd=12, remaining=27) > 0
    assert suggested_chase(gap=-40, expected_edge=0, weekly_sd=12, remaining=27) < 0
    # Same gap, fewer weeks left: each week's spread matters more.
    assert suggested_chase(30, 0, 12, 5) > suggested_chase(30, 0, 12, 25)
    assert suggested_chase(30, 0, 12, 0) == 0.0
    assert suggested_chase(1000, 0, 1, 1) == 0.1     # clamped
