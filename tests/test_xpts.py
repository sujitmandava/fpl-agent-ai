"""Tests for the stats-based xPts model and team ratings."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fpl_agent.forecast.expected_points import (
    DEFAULT_SCORING,
    ExpectedPointsModel,
    defensive_points_earned,
    nb_floor_div,
    p_zero,
    poisson_floor_div,
)
from fpl_agent.forecast.team_ratings import fit_team_ratings

# Player archetypes: id → (team, position, minutes per match, xG, xA, DC count)
ARCHETYPES = {
    1: (10, 3, 90, 0.50, 0.20, 3),    # attacking mid in a strong team
    2: (20, 4, 90, 0.30, 0.05, 1),    # forward in a weak team
    3: (10, 2, 90, 0.05, 0.05, 12),   # defender who racks up defensive actions
    4: (30, 1, 90, 0.00, 0.00, 0),    # goalkeeper
    5: (10, 3, None, 0.50, 0.00, 0),  # cameo: 10 minutes in one match only
    6: (20, 3, "rotate", 0.20, 0.10, 4),  # plays every other match
}
TEAMS = [10, 20, 30, 40]


def _scores(home: int, away: int) -> tuple[int, int]:
    strength = {10: 2, 20: 0, 30: 1, 40: 1}
    return strength[home], max(0, strength[away] - (1 if home == 10 else 0))


def _points(pos, minutes, goals, assists, cs, gc, dc_hit, saves=0):
    sc, code = DEFAULT_SCORING, {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}[pos]
    if minutes == 0:
        return 0
    pts = sc["long_play"] if minutes >= 60 else sc["short_play"]
    pts += goals * sc["goals_scored"][code] + assists * sc["assists"]
    pts += cs * sc["clean_sheets"][code] + (gc // 2) * sc["goals_conceded"][code]
    pts += (saves // 3) * sc["saves"] if pos == 1 else 0
    pts += sc["defensive_contribution"][code] if dc_hit else 0
    return pts


def build_world(gws: int = 8):
    """Small synthetic league: 4 teams, 2 matches per GW, 6 players."""
    teams = pd.DataFrame([{"id": t, "name": f"T{t}", "short_name": f"T{t}"} for t in TEAMS])
    pairings = [((10, 20), (30, 40)), ((30, 10), (40, 20)), ((10, 40), (20, 30))]
    fixtures, history = [], []
    fid = 1
    for gw in range(1, gws + 1):
        for home, away in pairings[gw % 3]:
            hg, ag = _scores(home, away)
            fixtures.append({"id": fid, "event": gw, "team_h": home, "team_a": away,
                             "team_h_difficulty": 3, "team_a_difficulty": 3,
                             "finished": 1, "finished_provisional": 1,
                             "team_h_score": hg, "team_a_score": ag})
            for pid, (team, pos, mins, xg, xa, dc) in ARCHETYPES.items():
                if team not in (home, away):
                    continue
                if mins is None:
                    minutes = 10 if gw == 1 else 0
                elif mins == "rotate":
                    minutes = 90 if gw % 2 else 0
                else:
                    minutes = mins
                is_home = team == home
                conceded = ag if is_home else hg
                cs = int(conceded == 0 and minutes >= 60 and pos in (1, 2, 3))
                frac = minutes / 90
                dc_hit = minutes >= 60 and dc >= (10 if pos == 2 else 12)
                goals = 1 if (pid == 1 and gw % 2 == 0) else 0
                history.append({
                    "player_id": pid, "fixture": fid, "gameweek": gw, "was_home": int(is_home),
                    "opponent_team": away if is_home else home, "minutes": minutes,
                    "expected_goals": xg * frac, "expected_assists": xa * frac,
                    "goals_scored": goals, "assists": 0, "clean_sheets": cs,
                    "goals_conceded": conceded if minutes else 0, "saves": 3 if pos == 1 else 0,
                    "bonus": 0, "yellow_cards": 0, "defensive_contribution": dc,
                    "total_points": _points(pos, minutes, goals, 0, cs, conceded, dc_hit,
                                            saves=3 if pos == 1 else 0),
                })
            fid += 1
    players = pd.DataFrame([
        {"id": pid, "web_name": f"P{pid}", "team_id": team, "element_type": pos,
         "now_cost": 60, "ep_next": 0.0, "status": "a", "chance_of_playing_next_round": None}
        for pid, (team, pos, *_rest) in ARCHETYPES.items()
    ])
    return players, pd.DataFrame(history), pd.DataFrame(fixtures), teams


def _future(fixtures, rows):
    return pd.concat([fixtures, pd.DataFrame(rows)], ignore_index=True)


def test_poisson_floor_div():
    assert poisson_floor_div(0, 2) == 0
    # For large λ, E[floor(N/2)] ≈ λ/2 − 1/4.
    assert poisson_floor_div(10, 2) == pytest.approx(10 / 2 - 0.25, abs=0.05)


def test_negative_binomial_goals_against():
    # Very large k converges to Poisson.
    assert p_zero(1.2, k=1e9) == pytest.approx(math.exp(-1.2), rel=1e-6)
    assert nb_floor_div(1.2, 2, k=1e9) == pytest.approx(poisson_floor_div(1.2, 2), rel=1e-4)
    # Uncertainty about the rate makes a clean sheet more likely than Poisson says.
    assert p_zero(1.2, k=4) > math.exp(-1.2)
    assert p_zero(0) == 1.0 and nb_floor_div(0, 2) == 0.0


def test_defensive_contribution_points_isolated():
    players, history, _, _ = build_world()
    positions = dict(zip(players["id"], players["element_type"]))
    resid = defensive_points_earned(history, positions, DEFAULT_SCORING)
    defender = history["player_id"] == 3
    assert (resid[defender] == 2).all()
    assert (resid[~defender] == 0).all()


def test_team_ratings_reflect_strength():
    players, history, fixtures, teams = build_world()
    r = fit_team_ratings(history, fixtures, teams, current_gw=8)
    assert r.att[10] > r.att[20]
    assert r.dfn[10] < r.dfn[20]          # lower = concedes less
    g_for_easy, _ = r.expected_goals(10, 20, home=True)
    g_for_hard, _ = r.expected_goals(20, 10, home=False)
    assert g_for_easy > g_for_hard


def test_profiles_minutes_shrinkage_and_dc():
    players, history, fixtures, teams = build_world()
    prof = ExpectedPointsModel(players, history, fixtures, teams, 8, 1).player_profiles()
    assert prof[1]["xg90"] > prof[2]["xg90"]
    # 10-minute cameo with 0.5 xG/90 raw would be 4.5 xG/90; shrinkage pulls it down.
    assert prof[5]["xg90"] < 1.0
    assert prof[5]["exp_minutes"] < 5
    assert 30 < prof[6]["exp_minutes"] < 60                  # rotation player
    # Hits DC every full game; shrinkage toward the (empty) prior keeps it below 1.
    assert prof[3]["dc_rate"] > 0.5
    assert prof[1]["dc_rate"] < 0.1


def test_opponent_changes_clean_sheet_and_attack_returns():
    players, history, fixtures, teams = build_world()
    fixtures = _future(fixtures, [
        {"id": 500, "event": 9, "team_h": 10, "team_a": 20},   # team 10 vs weak team
        {"id": 501, "event": 9, "team_h": 30, "team_a": 40},
    ])
    model = ExpectedPointsModel(players, history, fixtures, teams, 8, 1)
    prof = model.player_profiles()
    pts_weak, cs_weak, xgi_weak = model._fixture_points(prof[3], 2, 10, 20, True)
    pts_strong, cs_strong, xgi_strong = model._fixture_points(prof[3], 2, 10, 30, False)
    assert cs_weak > cs_strong
    assert pts_weak > pts_strong
    _, _, mid_weak = model._fixture_points(prof[1], 3, 10, 20, True)
    _, _, mid_strong = model._fixture_points(prof[1], 3, 10, 30, False)
    assert mid_weak > mid_strong


def test_season_scoring_rules_are_used():
    players, history, fixtures, teams = build_world()
    fixtures = _future(fixtures, [{"id": 500, "event": 9, "team_h": 10, "team_a": 20}])
    base = ExpectedPointsModel(players, history, fixtures, teams, 8, 1).predict().set_index("player_id")
    richer = {"goals_scored": {"GKP": 10, "DEF": 6, "MID": 10, "FWD": 4}}
    boosted = ExpectedPointsModel(players, history, fixtures, teams, 8, 1, scoring=richer) \
        .predict().set_index("player_id")
    assert boosted.loc[1, "expected_points_next"] > base.loc[1, "expected_points_next"]
    assert boosted.loc[3, "expected_points_next"] == pytest.approx(base.loc[3, "expected_points_next"])


def test_predict_outputs_explanations():
    players, history, fixtures, teams = build_world()
    fixtures = _future(fixtures, [{"id": 500, "event": 9, "team_h": 10, "team_a": 20}])
    fc = ExpectedPointsModel(players, history, fixtures, teams, 8, 1).predict()
    for col in ("exp_minutes", "xg90", "xa90", "xg_share", "xa_share", "finish90",
                "dc_rate", "cs_next", "xgi_next"):
        assert col in fc.columns
    assert math.isclose(fc.set_index("player_id").loc[4, "xg90"], 0.0, abs_tol=0.05)


def test_role_share_and_finishing_form():
    players, history, fixtures, teams = build_world()
    prof = ExpectedPointsModel(players, history, fixtures, teams, 8, 1).player_profiles()
    # Player 1 creates 0.5 of team 10's 0.6 xG per match (with player 3); shrinkage
    # keeps the share below that but well above the defender's.
    assert 0.5 < prof[1]["xg_share"] < 0.84
    assert prof[1]["xg_share"] > prof[3]["xg_share"]
    # Player 1 scores a goal every other match from 0.5 xG: finishing above xG,
    # but shrunk, so the carried-over amount is small.
    assert 0 < prof[1]["finish90"] < 0.5
    assert prof[2]["finish90"] < 0      # never scores from 0.3 xG/match


def test_finishing_form_moves_forecast_a_little():
    import fpl_agent.forecast.expected_points as ep

    players, history, fixtures, teams = build_world()
    fixtures = _future(fixtures, [{"id": 500, "event": 9, "team_h": 10, "team_a": 20}])
    model = ExpectedPointsModel(players, history, fixtures, teams, 8, 1)
    prof = model.player_profiles()[1]
    with_form, _, _ = model._fixture_points(prof, 3, 10, 20, True)
    old = ep.FINISH_WEIGHT
    try:
        ep.FINISH_WEIGHT = 0.0
        without, _, _ = model._fixture_points(prof, 3, 10, 20, True)
    finally:
        ep.FINISH_WEIGHT = old
    assert 0 < with_form - without < 0.5
