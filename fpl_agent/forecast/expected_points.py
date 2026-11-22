"""Expected-points (xPts) model built from underlying stats.

For every player and every upcoming fixture::

    xPts = appearance + goals + assists + clean sheet + goals conceded
           + saves + defensive contribution + bonus + cards

Inputs, per player (recent matches weighted more heavily):

* **Minutes**: probability of playing, of playing 60+, and expected minutes,
  from the last few team matches.
* **Role**: the player's share of his team's xG and xA while he is on the
  pitch, shrunk toward the position average when minutes are low, so a
  100-minute cameo doesn't produce a superstar. Shares are steadier than raw
  xG/90 and pick up role changes (a new target man, a moved winger).
* **Finishing form**: recent goals − xG per 90, of which ``FINISH_WEIGHT``
  (15%) is carried forward; the rest is treated as luck that fades.
* **Defensive contribution**: how often the player hits the DC threshold in
  60+ minute games. Hits are identified by rebuilding each match's points
  from the scoring rules (the leftover +2 is the DC bonus), so the
  thresholds never need hard-coding.
* **Saves/90** (GK), **bonus/90**, **yellow cards/90**.

Per fixture, the opponent enters through team ratings fit from xG and goals
(see ``team_ratings``): a player's expected goals and assists are his role
share times the goals his team is expected to score in that fixture, while
clean-sheet and goals-conceded odds come from a negative binomial model of the
goals expected against (``CS_DISPERSION``). A blank gameweek scores 0 and a double sums both
fixtures. Availability (``chance_of_playing_next_round``) applies to the next
gameweek and fades over ``RECOVERY_GWS``.

Points per action come from the season's ``game_config.scoring`` (passed in
as ``scoring``), e.g. GK goals are worth 10 in 2026/27.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from .team_ratings import TeamRatings, fit_team_ratings

logger = logging.getLogger(__name__)

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
POS_CODE = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# 2026/27 values; replaced by the live season's rules when available.
DEFAULT_SCORING = {
    "long_play": 2, "short_play": 1, "assists": 3, "saves": 1, "bonus": 1,
    "yellow_cards": -1, "red_cards": -3, "own_goals": -2,
    "penalties_saved": 5, "penalties_missed": -2,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}

RECOVERY_GWS = 4          # gameweeks for a flagged player to count as fully fit
MINUTES_WINDOW = 6        # recent team matches used for the minutes model
MINUTES_DECAY = 0.8       # per-match weight decay for minutes
RATE_DECAY = 0.92         # per-gameweek weight decay for per-90 rates
SHRINK_MINUTES = 270.0    # prior strength for per-90 rates, in minutes
SHRINK_MATCHES = 4.0      # prior strength for DC hit rate, in matches
PRIOR_DISCOUNT = 0.85     # low-minute players are usually below positional average
# Share of recent finishing over/under-performance (goals − xG) that carries
# forward. Studies and this season's data both put it around 10–15%.
FINISH_WEIGHT = 0.15
# Goals against are modelled as negative binomial with this shape rather than
# Poisson: a team's true concession rate is uncertain, which makes 0 (and 3+)
# more likely than Poisson says. Poisson under-predicted clean sheets by ~5
# percentage points in the walk-forward test; k=4 was calibrated.
CS_DISPERSION = 4.0


def _pts(scoring: dict, key: str, pos: int) -> float:
    v = scoring.get(key, DEFAULT_SCORING.get(key, 0))
    return float(v.get(POS_CODE[pos], 0) if isinstance(v, dict) else v)


def poisson_floor_div(lam: float, k: int, nmax: int = 25) -> float:
    """E[floor(N / k)] for N ~ Poisson(lam)."""
    if lam <= 0:
        return 0.0
    total, p = 0.0, math.exp(-lam)
    for n in range(nmax + 1):
        if n:
            p *= lam / n
        total += p * (n // k)
    return total


def p_zero(lam: float, k: float | None = None) -> float:
    """P(N = 0) for N negative binomial with mean *lam* and shape *k*."""
    k = CS_DISPERSION if k is None else k
    if lam <= 0:
        return 1.0
    return (k / (k + lam)) ** k


def nb_floor_div(lam: float, div: int, k: float | None = None, nmax: int = 25) -> float:
    """E[floor(N / div)] for N negative binomial with mean *lam* and shape *k*."""
    k = CS_DISPERSION if k is None else k
    if lam <= 0:
        return 0.0
    q = lam / (k + lam)
    total, p = 0.0, p_zero(lam, k)
    for n in range(nmax + 1):
        if n:
            p *= (n - 1 + k) / n * q
        total += p * (n // div)
    return total


def defensive_points_earned(history: pd.DataFrame, positions: dict[int, int], scoring: dict) -> pd.Series:
    """Points per match not explained by any other scoring rule.

    With complete stats this is exactly the defensive-contribution bonus
    (0 or +2). Returns a Series aligned with *history*.
    """
    pos = history["player_id"].map(positions).fillna(3).astype(int)
    m = history["minutes"].fillna(0)
    get = lambda col: history[col].fillna(0) if col in history.columns else 0  # noqa: E731
    by_pos = lambda key: pos.map(lambda p: _pts(scoring, key, p))  # noqa: E731

    recon = np.where(m >= 60, _pts(scoring, "long_play", 3),
                     np.where(m > 0, _pts(scoring, "short_play", 3), 0))
    recon = recon + get("goals_scored") * by_pos("goals_scored")
    recon = recon + get("assists") * _pts(scoring, "assists", 3)
    recon = recon + get("clean_sheets") * by_pos("clean_sheets")
    recon = recon + (get("goals_conceded") // 2) * by_pos("goals_conceded")
    recon = recon + np.where(pos == 1, (get("saves") // 3) * _pts(scoring, "saves", 1), 0)
    recon = recon + get("bonus")
    for key in ("yellow_cards", "red_cards", "own_goals", "penalties_saved", "penalties_missed"):
        recon = recon + get(key) * _pts(scoring, key, 3)
    return history["total_points"] - recon


class ExpectedPointsModel:
    """Forecast expected points for every player over *horizon* gameweeks.

    Parameters
    ----------
    players, history, fixtures, teams : DataFrame
        Tables from ``FPLStore``.
    current_gw : int
        Latest gameweek whose deadline has passed; forecasts start at
        ``current_gw + 1``.
    horizon : int
        Number of future gameweeks to forecast.
    scoring : dict, optional
        The season's ``game_config.scoring`` (``FPLStore.scoring_rules()``).
    """

    def __init__(
        self,
        players: pd.DataFrame,
        history: pd.DataFrame,
        fixtures: pd.DataFrame,
        teams: pd.DataFrame,
        current_gw: int,
        horizon: int = 6,
        scoring: dict | None = None,
    ) -> None:
        self.players = players.copy()
        self.fixtures = fixtures.copy()
        self.teams = teams.copy()
        self.current_gw = current_gw
        self.horizon = horizon
        self.scoring = {**DEFAULT_SCORING, **(scoring or {})}
        self.history = self._played_matches(history.copy())
        self.ratings: TeamRatings = fit_team_ratings(self.history, self.fixtures, self.teams, current_gw)

    @property
    def future_gws(self) -> list[int]:
        return list(range(self.current_gw + 1, self.current_gw + 1 + self.horizon))

    # -- Public API -----------------------------------------------------------

    def predict(self) -> pd.DataFrame:
        """One row per player:

        * ``expected_points_gw{N}`` per future gameweek, ``expected_points_next``,
          ``total_expected_points``
        * explanatory columns: ``exp_minutes``, ``xg90``, ``xa90``, ``xg_share`` and
          ``xa_share`` (share of team xG/xA while on the pitch), ``finish90``
          (recent goals − xG per 90, shrunk), ``dc_rate``,
          ``cs_next`` (clean-sheet probability, next GW), ``xgi_next``
          (expected goal involvements, next GW), ``variance``
        """
        profiles = self.player_profiles()
        team_fx = self._team_fixtures()
        future = self.future_gws

        records = []
        for p in self.players.itertuples(index=False):
            pid, pos, team = int(p.id), int(p.element_type), int(p.team_id)
            prof = profiles.get(pid)
            row: dict = {"player_id": pid}
            total, cs_next, xgi_next = 0.0, 0.0, 0.0
            for k, gw in enumerate(future):
                avail = self._availability(p, k)
                gw_pts = 0.0
                for opp, home in team_fx.get((team, gw), []):
                    if prof is None:
                        pts, cs, xgi = float(getattr(p, "ep_next", 0) or 0), 0.0, 0.0
                    else:
                        pts, cs, xgi = self._fixture_points(prof, pos, team, opp, home)
                    gw_pts += pts
                    if k == 0:
                        cs_next = max(cs_next, cs)
                        xgi_next += xgi * avail
                gw_pts = max(gw_pts * avail, 0.0)
                row[f"expected_points_gw{gw}"] = round(gw_pts, 2)
                total += gw_pts
            row["expected_points_next"] = row[f"expected_points_gw{future[0]}"] if future else 0.0
            row["total_expected_points"] = round(total, 2)
            prof = prof or {}
            row.update(
                exp_minutes=round(prof.get("exp_minutes", 0.0), 1),
                xg90=round(prof.get("xg90", 0.0), 3),
                xa90=round(prof.get("xa90", 0.0), 3),
                xg_share=round(prof.get("xg_share", 0.0), 3),
                xa_share=round(prof.get("xa_share", 0.0), 3),
                finish90=round(prof.get("finish90", 0.0), 3),
                dc_rate=round(prof.get("dc_rate", 0.0), 3),
                cs_next=round(cs_next, 3),
                xgi_next=round(xgi_next, 3),
                variance=round(prof.get("variance", 0.0), 3),
            )
            records.append(row)
        return pd.DataFrame(records)

    # -- Player profiles ------------------------------------------------------

    def player_profiles(self) -> dict[int, dict]:
        """Per-player minutes and per-90 rates (None-free dict per player)."""
        h = self.history
        if h.empty:
            return {}
        positions = dict(zip(self.players["id"].astype(int), self.players["element_type"].astype(int)))
        h = h.copy()
        h["pos"] = h["player_id"].map(positions)
        h = h[h["pos"].notna()]
        for col in ("minutes", "expected_goals", "expected_assists", "bonus",
                    "yellow_cards", "saves", "total_points"):
            if col not in h.columns:
                h[col] = 0.0
            h[col] = pd.to_numeric(h[col], errors="coerce").fillna(0.0)
        if "goals_scored" not in h.columns:
            h["goals_scored"] = 0.0
        h["goals_scored"] = pd.to_numeric(h["goals_scored"], errors="coerce").fillna(0.0)
        h["dc_hit"] = (defensive_points_earned(h, positions, self.scoring) > 0).astype(float)
        h["w"] = RATE_DECAY ** (self.current_gw - h["gameweek"]).clip(lower=0)
        h["exposure"] = self._team_xg_exposure(h)
        sort_cols = ["gameweek", "fixture"] if "fixture" in h.columns else ["gameweek"]
        h = h.sort_values(sort_cols)

        priors = self._position_priors(h)
        # Prior strength for role shares, in team-xG units: SHRINK_MINUTES of
        # an average team's chances.
        team_xg90 = float(h["exposure"].sum() / h["minutes"].sum() * 90) if h["minutes"].sum() else 0.0
        if team_xg90 <= 0:
            team_xg90 = 1.3  # no xG data: any positive prior strength works
        shrink_share = SHRINK_MINUTES / 90.0 * team_xg90
        out: dict[int, dict] = {}
        for pid, g in h.groupby("player_id"):
            pos = int(g["pos"].iloc[0])
            pr = priors[pos]

            recent = g.tail(MINUTES_WINDOW)
            mw = MINUTES_DECAY ** np.arange(len(recent) - 1, -1, -1)
            mw = mw / mw.sum()
            mins = recent["minutes"].to_numpy()
            p_play = float(np.dot(mw, mins > 0))
            p60 = float(np.dot(mw, mins >= 60))
            exp_minutes = float(np.dot(mw, mins))
            if p_play == 0 and g["minutes"].sum() == 0:
                continue  # never played: fall back to FPL's ep_next

            played = g[g["minutes"] > 0]
            wmin = float((played["w"] * played["minutes"]).sum())
            rate = lambda col: (  # noqa: E731
                (float((played["w"] * played[col]).sum()) + SHRINK_MINUTES * pr[col] / 90.0)
                / (wmin + SHRINK_MINUTES) * 90.0
            )
            # Role: share of the team's xG (and xA) while on the pitch.
            wexp = float((played["w"] * played["exposure"]).sum())
            share = lambda col, prior: (  # noqa: E731
                (float((played["w"] * played[col]).sum()) + shrink_share * prior)
                / (wexp + shrink_share)
            )
            # Finishing form: recency-weighted goals − xG per 90, shrunk to 0.
            over90 = float((played["w"] * (played["goals_scored"] - played["expected_goals"])).sum()) \
                / (wmin + SHRINK_MINUTES) * 90.0
            full = g[g["minutes"] >= 60]
            dc_rate = (float((full["w"] * full["dc_hit"]).sum()) + SHRINK_MATCHES * pr["dc_rate"]) \
                / (float(full["w"].sum()) + SHRINK_MATCHES)
            pts_recent = g.loc[g["minutes"] > 0, "total_points"].tail(8)

            out[int(pid)] = {
                "p_play": p_play, "p60": p60, "exp_minutes": exp_minutes,
                "xg90": rate("expected_goals"), "xa90": rate("expected_assists"),
                "xg_share": share("expected_goals", pr["xg_share"]),
                "xa_share": share("expected_assists", pr["xa_share"]),
                "finish90": over90,
                "bonus90": rate("bonus"), "yc90": rate("yellow_cards"),
                "saves90": rate("saves"), "dc_rate": dc_rate,
                "variance": float(pts_recent.var()) if len(pts_recent) >= 2 else 0.0,
            }
        return out

    def _team_xg_exposure(self, h: pd.DataFrame) -> pd.Series:
        """Team xG in each player-match, scaled by the share of the match he played.

        The team is read from the fixture (home or away side), so a player's
        old club is used for matches before a transfer.
        """
        if "fixture" in h.columns and "was_home" in h.columns and "team_h" in self.fixtures.columns:
            fx = self.fixtures.set_index("id")
            home = h["was_home"].fillna(0).astype(bool)
            team = np.where(home, h["fixture"].map(fx["team_h"]), h["fixture"].map(fx["team_a"]))
        else:
            team = h["player_id"].map(dict(zip(self.players["id"], self.players["team_id"])))
        key = pd.Series(list(zip(h["fixture"] if "fixture" in h.columns else h["gameweek"], team)),
                        index=h.index)
        team_xg = h.groupby(key)["expected_goals"].transform("sum")
        return team_xg * h["minutes"] / 90.0

    @staticmethod
    def _position_priors(h: pd.DataFrame) -> dict[int, dict]:
        """Positional per-90 averages among regulars, discounted a little."""
        mins_total = h.groupby("player_id")["minutes"].transform("sum")
        regulars = h[(mins_total >= 900) & (h["minutes"] > 0)]
        priors = {}
        for pos in (1, 2, 3, 4):
            r = regulars[regulars["pos"] == pos]
            full = r[r["minutes"] >= 60]
            m = float(r["minutes"].sum())
            per90 = lambda col: float(r[col].sum()) / m * 90 if m else 0.0  # noqa: E731
            exp_total = float(r["exposure"].sum()) if "exposure" in r.columns else 0.0
            share = lambda col: float(r[col].sum()) / exp_total if exp_total else 0.0  # noqa: E731
            priors[pos] = {
                "xg_share": share("expected_goals") * PRIOR_DISCOUNT,
                "xa_share": share("expected_assists") * PRIOR_DISCOUNT,
                "expected_goals": per90("expected_goals") * PRIOR_DISCOUNT,
                "expected_assists": per90("expected_assists") * PRIOR_DISCOUNT,
                "bonus": per90("bonus") * PRIOR_DISCOUNT,
                "yellow_cards": per90("yellow_cards"),
                "saves": per90("saves"),
                "dc_rate": float(full["dc_hit"].mean()) * PRIOR_DISCOUNT if len(full) else 0.0,
            }
        return priors

    # -- Fixture-level points -------------------------------------------------

    def _fixture_points(self, prof: dict, pos: int, team: int, opp: int, home: bool
                        ) -> tuple[float, float, float]:
        """Return (expected points, clean-sheet probability, xG+xA) for one fixture."""
        sc, r = self.scoring, self.ratings
        frac = prof["exp_minutes"] / 90.0
        g_for, g_against = r.expected_goals(team, opp, home)
        att_mult = g_for / (r.mu * r.att.get(team, 1.0))
        team_avg_against = r.mu * r.dfn.get(team, 1.0)

        # Role × team: his share of his team's chances × the chances the team
        # is expected to create in this fixture.
        xg = prof["xg_share"] * g_for * frac
        xa = prof["xa_share"] * g_for * frac
        # Expected goals, nudged by a fraction of his recent finishing form.
        goals = max(0.0, xg + FINISH_WEIGHT * prof.get("finish90", 0.0) * frac * att_mult)
        p_cs = p_zero(g_against)

        pts = prof["p_play"] * _pts(sc, "short_play", pos) \
            + prof["p60"] * (_pts(sc, "long_play", pos) - _pts(sc, "short_play", pos))
        pts += goals * _pts(sc, "goals_scored", pos) + xa * _pts(sc, "assists", pos)
        pts += prof["p60"] * p_cs * _pts(sc, "clean_sheets", pos)
        gc = _pts(sc, "goals_conceded", pos)
        if gc:
            pts += gc * nb_floor_div(g_against * frac, 2)
        if pos == 1:
            exp_saves = prof["saves90"] * frac * (g_against / team_avg_against)
            pts += _pts(sc, "saves", pos) * poisson_floor_div(exp_saves, 3)
        pts += prof["dc_rate"] * prof["p60"] * _pts(sc, "defensive_contribution", pos)

        if pos in (1, 2):
            bonus_mult = math.sqrt(p_cs / p_zero(team_avg_against))
        else:
            bonus_mult = math.sqrt(att_mult)
        pts += prof["bonus90"] * frac * bonus_mult * _pts(sc, "bonus", pos)
        pts += prof["yc90"] * frac * _pts(sc, "yellow_cards", pos)
        return pts, prof["p60"] * p_cs, xg + xa

    # -- Helpers --------------------------------------------------------------

    def _played_matches(self, history: pd.DataFrame) -> pd.DataFrame:
        """Keep only matches that have actually been played."""
        if history.empty:
            return history
        if "fixture" in history.columns and "id" in self.fixtures.columns:
            done = pd.Series(False, index=self.fixtures.index)
            for col in ("finished", "finished_provisional"):
                if col in self.fixtures.columns:
                    done |= self.fixtures[col].fillna(0).astype(bool)
            played_ids = set(self.fixtures.loc[done, "id"].astype(int))
            return history[history["fixture"].isin(played_ids)]
        return history[history["gameweek"] <= self.current_gw]

    def _team_fixtures(self) -> dict[tuple[int, int], list[tuple[int, bool]]]:
        """(team_id, gameweek) → [(opponent, is_home)]; missing key = blank."""
        upcoming = self.fixtures[self.fixtures["event"].isin(set(self.future_gws))]
        out: dict[tuple[int, int], list[tuple[int, bool]]] = {}
        for f in upcoming.itertuples(index=False):
            gw = int(f.event)
            out.setdefault((int(f.team_h), gw), []).append((int(f.team_a), True))
            out.setdefault((int(f.team_a), gw), []).append((int(f.team_h), False))
        return out

    @staticmethod
    def _availability(player, weeks_ahead: int) -> float:
        """Probability of being available, ``weeks_ahead`` GWs after the next one."""
        if getattr(player, "status", "a") == "u":      # left the club / out for season
            return 0.0
        chance = getattr(player, "chance_of_playing_next_round", None)
        if chance is None or pd.isna(chance):
            return 1.0
        c = float(chance) / 100.0
        return c + (1.0 - c) * min(1.0, weeks_ahead / RECOVERY_GWS)
