"""How players in the same match score together.

xPts is an average, and averages add up whatever the players have to do with
each other. The *spread* of a team's score doesn't: two defenders of the same
club keep (or lose) the same clean sheet, and a striker's goal costs the
defenders facing him theirs. When chasing a rival, that spread matters. A
squad of players who cancel out can't produce the big week the chase needs.

The model, per gameweek, for players *i* and *j* in the same match::

    cov(i, j) = ρ[side, roles] · sd(i) · sd(j)
    sd(i)²    = VAR_BASE + VAR_SLOPE · xPts(i)

* ``side``: ``"same"`` team or ``"opp"`` (the two teams in one fixture).
* ``roles``: ``"DD"``, ``"AD"`` or ``"AA"``, where GK/DEF are ``D`` and
  MID/FWD are ``A``.

ρ and the variance line were measured on the walk-forward forecast errors
(actual − xPts, one gameweek ahead) of GW4–11 of 2026/27, players with 2+
xPts, so they describe what the forecast doesn't already know:

=========  =====  ==========================================
pair       ρ      e.g.
=========  =====  ==========================================
same DD    +0.55  two Arsenal defenders: one clean sheet
same AD    +0.16  a team that scores a lot usually wins
same AA    +0.09  goal and assist on the same move
opp AD     −0.29  Haaland's goal is Konsa's lost clean sheet
opp DD     −0.18  only one side tends to keep a clean sheet
opp AA     −0.12  one team's chances come at the other's cost
=========  =====  ==========================================

Pairs within one match aren't independent, so the intervals around these are
wider than a naive bootstrap says, but every sign was clear of zero. Re-check
with ``python fpl_agent.py backtest-chase``.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

PAIR_CORR: dict[tuple[str, str], float] = {
    ("same", "DD"): 0.55,
    ("same", "AD"): 0.16,
    ("same", "AA"): 0.09,
    ("opp", "AD"): -0.29,
    ("opp", "DD"): -0.18,
    ("opp", "AA"): -0.12,
}
# Variance of a player's score around his xPts grows with xPts
# (fit across positions: about 2 + 2.6 · xPts).
VAR_BASE = 2.0
VAR_SLOPE = 2.6
# Players below this many xPts in a gameweek are left out of the pair terms:
# they won't start for anyone, and leaving them out keeps the MILP small.
PAIR_MIN_XPTS = 1.5


def role(element_type: int) -> str:
    return "D" if int(element_type) <= 2 else "A"


def pair_kind(role_a: str, role_b: str) -> str:
    return "".join(sorted(role_a + role_b))


def score_var(xpts: float) -> float:
    """Variance of a player's score around his xPts."""
    return VAR_BASE + VAR_SLOPE * max(float(xpts), 0.0)


def opponents_by_gw(fixtures: pd.DataFrame, gws: list[int]) -> dict[int, dict[int, set[int]]]:
    """gw → team → teams it plays that gameweek (a double has two)."""
    out: dict[int, dict[int, set[int]]] = {g: {} for g in gws}
    fx = fixtures[fixtures["event"].isin(gws)]
    for r in fx.itertuples(index=False):
        g, h, a = int(r.event), int(r.team_h), int(r.team_a)
        out[g].setdefault(h, set()).add(a)
        out[g].setdefault(a, set()).add(h)
    return out


def pair_covariances(
    players: pd.DataFrame,
    xpts: dict[int, float],
    opponents: dict[int, set[int]],
    corr: dict[tuple[str, str], float] | None = None,
    min_xpts: float = PAIR_MIN_XPTS,
) -> list[tuple[int, int, float]]:
    """``[(i, j, cov)]`` for one gameweek, each unordered pair once.

    *players* needs ``id``, ``element_type``, ``team_id``; *xpts* maps player
    id to that gameweek's xPts; *opponents* is one gameweek of
    `opponents_by_gw`. Teammates are "same", players whose teams meet are
    "opp"; every other pair is uncorrelated and left out.
    """
    corr = corr or PAIR_CORR
    p = players[players["id"].isin([i for i, v in xpts.items() if v >= min_xpts])]
    by_team: dict[int, list[tuple[int, str, float]]] = {}
    for r in p.itertuples(index=False):
        if int(r.team_id) not in opponents:   # blank gameweek
            continue
        sd = math.sqrt(score_var(xpts[int(r.id)]))
        by_team.setdefault(int(r.team_id), []).append((int(r.id), role(r.element_type), sd))

    out: list[tuple[int, int, float]] = []
    for team, members in by_team.items():
        for (i, ri, si), (j, rj, sj) in itertools.combinations(members, 2):
            out.append((i, j, corr[("same", pair_kind(ri, rj))] * si * sj))
        for opp in opponents[team]:
            if opp <= team:      # each fixture once
                continue
            for (i, ri, si), (j, rj, sj) in itertools.product(members, by_team.get(opp, [])):
                out.append((i, j, corr[("opp", pair_kind(ri, rj))] * si * sj))
    return out


def lineup_sd(lineup: list[int], captain: int | None, xpts: dict[int, float],
              pairs: list[tuple[int, int, float]]) -> float:
    """Standard deviation of an XI's score (captain counted twice)."""
    weight = {i: 1 + (i == captain) for i in lineup}
    var = sum(weight[i] ** 2 * score_var(xpts.get(i, 0.0)) for i in lineup)
    var += sum(2 * weight[i] * weight[j] * c for i, j, c in pairs if i in weight and j in weight)
    return math.sqrt(max(var, 0.0))


def fit_pair_correlations(errors: pd.DataFrame, min_pairs: int = 30) -> dict[tuple[str, str], float]:
    """Measure ρ per pair type from forecast errors.

    *errors* has one row per player-match: ``fixture``, ``was_home``,
    ``element_type``, ``error`` (actual − xPts). Pair types with fewer than
    *min_pairs* examples keep the default in `PAIR_CORR`.
    """
    rows = []
    for _, g in errors.groupby("fixture"):
        recs = list(zip(g["was_home"], g["element_type"].map(role), g["error"]))
        for (ha, ra, ea), (hb, rb, eb) in itertools.combinations(recs, 2):
            side = "same" if ha == hb else "opp"
            rows.append((side, pair_kind(ra, rb), ea, eb))
    fitted = dict(PAIR_CORR)
    if not rows:
        return fitted
    d = pd.DataFrame(rows, columns=["side", "kind", "a", "b"])
    for key, g in d.groupby(["side", "kind"]):
        if len(g) >= min_pairs and g["a"].std() > 0 and g["b"].std() > 0:
            fitted[key] = float(np.corrcoef(g["a"], g["b"])[0, 1])
    return fitted
