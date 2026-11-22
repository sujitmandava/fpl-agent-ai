"""Team attack/defence ratings from xG and goals, adjusted for opponents.

Each team gets an attack rating ``att`` and defence rating ``dfn`` (1.0 =
league average; for defence, lower is better). Expected goals in a fixture::

    λ_home = μ · att[home] · dfn[away] · hfa
    λ_away = μ · att[away] · dfn[home] / hfa

* μ is the league average goals per team per match, hfa the home advantage
  (both estimated from this season's results).
* Each match's attacking output is ``XG_WEIGHT·xG + (1 − XG_WEIGHT)·goals``,
  so ratings track chance quality more than finishing luck.
* Recent matches count more (``decay`` per gameweek), which is what "team
  form" means here.
* Ratings are solved iteratively so a team isn't flattered by an easy run of
  opponents, and are shrunk toward a prior from FPL's own team strength
  numbers, which matters early in the season.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

XG_WEIGHT = 0.7
DECAY = 0.92            # weight multiplier per gameweek of age
PRIOR_MATCHES = 4.0     # strength of the FPL-strength prior, in matches
ITERATIONS = 25


@dataclass
class TeamRatings:
    att: dict[int, float]
    dfn: dict[int, float]
    mu: float
    hfa: float
    form: pd.DataFrame      # per-team recent xG for/against (display only)

    def expected_goals(self, team: int, opp: int, home: bool) -> tuple[float, float]:
        """(goals for, goals against) expected for *team* in this fixture."""
        h = self.hfa if home else 1.0 / self.hfa
        g_for = self.mu * self.att.get(team, 1.0) * self.dfn.get(opp, 1.0) * h
        g_against = self.mu * self.att.get(opp, 1.0) * self.dfn.get(team, 1.0) / h
        return g_for, g_against

    def attack_multiplier(self, team: int, opp: int, home: bool) -> float:
        """How much easier than this team's average fixture it is to score here."""
        g_for, _ = self.expected_goals(team, opp, home)
        return g_for / (self.mu * self.att.get(team, 1.0))


def match_table(history: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """One row per finished fixture with home/away xG and goals."""
    done = fixtures.copy()
    if "team_h_score" not in done.columns or "team_a_score" not in done.columns:
        return pd.DataFrame(columns=["fixture", "gw", "home", "away", "hxg", "axg", "hg", "ag"])
    mask = pd.Series(False, index=done.index)
    for col in ("finished", "finished_provisional"):
        if col in done.columns:
            mask |= done[col].fillna(0).astype(bool)
    done = done[mask & done["team_h_score"].notna()]
    if done.empty:
        return pd.DataFrame(columns=["fixture", "gw", "home", "away", "hxg", "axg", "hg", "ag"])

    if not history.empty and "expected_goals" in history.columns:
        xg = (history.groupby(["fixture", "was_home"])["expected_goals"].sum()
              .unstack(fill_value=0.0))
        hxg = xg.get(1, xg.get(True, pd.Series(dtype=float)))
        axg = xg.get(0, xg.get(False, pd.Series(dtype=float)))
    else:
        hxg = axg = pd.Series(dtype=float)

    out = pd.DataFrame({
        "fixture": done["id"].astype(int).to_numpy(),
        "gw": done["event"].astype(int).to_numpy(),
        "home": done["team_h"].astype(int).to_numpy(),
        "away": done["team_a"].astype(int).to_numpy(),
        "hg": done["team_h_score"].astype(float).to_numpy(),
        "ag": done["team_a_score"].astype(float).to_numpy(),
    })
    out["hxg"] = out["fixture"].map(hxg).fillna(out["hg"])
    out["axg"] = out["fixture"].map(axg).fillna(out["ag"])
    return out


def _strength_prior(teams: pd.DataFrame) -> tuple[dict[int, float], dict[int, float]]:
    if teams.empty or "strength_attack_home" not in teams.columns:
        return {}, {}
    att = (teams["strength_attack_home"] + teams["strength_attack_away"]) / 2
    dfn = (teams["strength_defence_home"] + teams["strength_defence_away"]) / 2
    if att.mean() <= 0 or dfn.mean() <= 0:
        return {}, {}
    # FPL strength numbers are compressed (±15%); squaring widens them to a
    # realistic spread of goal rates.
    att_p = (att / att.mean()) ** 2
    dfn_p = (dfn.mean() / dfn) ** 2
    ids = teams["id"].astype(int)
    return dict(zip(ids, att_p)), dict(zip(ids, dfn_p))


def fit_team_ratings(
    history: pd.DataFrame,
    fixtures: pd.DataFrame,
    teams: pd.DataFrame,
    current_gw: int,
    xg_weight: float = XG_WEIGHT,
    decay: float = DECAY,
    prior_matches: float = PRIOR_MATCHES,
) -> TeamRatings:
    matches = match_table(history, fixtures)
    att_prior, dfn_prior = _strength_prior(teams)
    team_ids = set(teams["id"].astype(int)) if not teams.empty else set()
    team_ids |= set(matches["home"]) | set(matches["away"])

    if matches.empty:
        return TeamRatings(
            att={t: att_prior.get(t, 1.0) for t in team_ids},
            dfn={t: dfn_prior.get(t, 1.0) for t in team_ids},
            mu=1.35, hfa=1.1, form=pd.DataFrame(),
        )

    m = matches.copy()
    m["hs"] = xg_weight * m["hxg"] + (1 - xg_weight) * m["hg"]
    m["as"] = xg_weight * m["axg"] + (1 - xg_weight) * m["ag"]
    m["w"] = decay ** (current_gw - m["gw"]).clip(lower=0)

    home_avg, away_avg = m["hs"].mean(), m["as"].mean()
    mu = (home_avg + away_avg) / 2
    hfa = math.sqrt(home_avg / away_avg) if away_avg > 0 else 1.0

    att = {t: att_prior.get(t, 1.0) for t in team_ids}
    dfn = {t: dfn_prior.get(t, 1.0) for t in team_ids}

    # Each match contributes one observation per side.
    obs = pd.DataFrame({
        "team": np.concatenate([m["home"], m["away"]]),
        "opp": np.concatenate([m["away"], m["home"]]),
        "scored": np.concatenate([m["hs"], m["as"]]),
        "w": np.concatenate([m["w"], m["w"]]),
        "h": np.concatenate([np.full(len(m), hfa), np.full(len(m), 1 / hfa)]),
    })

    for _ in range(ITERATIONS):
        # Attack: goals scored relative to what an average attack would score
        # against that opponent at that venue.
        exp_att = mu * obs["opp"].map(dfn) * obs["h"]
        att = _shrunk_ratio(obs, obs["team"], obs["scored"] / exp_att, att_prior, prior_matches, team_ids)
        exp_def = mu * obs["team"].map(att) * obs["h"]
        dfn = _shrunk_ratio(obs, obs["opp"], obs["scored"] / exp_def, dfn_prior, prior_matches, team_ids)
        # Normalise so the league average stays 1.0.
        a_mean, d_mean = np.mean(list(att.values())), np.mean(list(dfn.values()))
        att = {t: v / a_mean for t, v in att.items()}
        dfn = {t: v / d_mean for t, v in dfn.items()}

    form = _recent_form(m, team_ids, current_gw)
    return TeamRatings(att=att, dfn=dfn, mu=float(mu), hfa=float(hfa), form=form)


def _shrunk_ratio(obs, key, ratio, prior, prior_matches, team_ids) -> dict[int, float]:
    df = pd.DataFrame({"k": key.to_numpy(), "r": ratio.to_numpy(), "w": obs["w"].to_numpy()})
    df["wr"] = df["r"] * df["w"]
    g = df.groupby("k")[["wr", "w"]].sum()
    out = {}
    for t in team_ids:
        p = prior.get(t, 1.0)
        if t in g.index:
            out[t] = (g.at[t, "wr"] + prior_matches * p) / (g.at[t, "w"] + prior_matches)
        else:
            out[t] = p
    return out


def _recent_form(m: pd.DataFrame, team_ids: set[int], current_gw: int, n: int = 6) -> pd.DataFrame:
    rows = []
    for t in team_ids:
        tm = m[(m["home"] == t) | (m["away"] == t)].sort_values("gw").tail(n)
        if tm.empty:
            continue
        home = tm["home"] == t
        xg_for = np.where(home, tm["hxg"], tm["axg"]).sum()
        xg_against = np.where(home, tm["axg"], tm["hxg"]).sum()
        g_for = np.where(home, tm["hg"], tm["ag"]).sum()
        g_against = np.where(home, tm["ag"], tm["hg"]).sum()
        rows.append({"team_id": t, "matches": len(tm),
                     "xg_for": round(xg_for / len(tm), 2), "xg_against": round(xg_against / len(tm), 2),
                     "goals_for": g_for, "goals_against": g_against})
    return pd.DataFrame(rows)
