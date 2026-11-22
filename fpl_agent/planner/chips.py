"""Chip outlook: when each available chip is worth playing.

Values come from optimizer runs over the forecast horizon:

* **Bench Boost** – EP of the four subs in each gameweek of the planned squad.
* **Triple Captain** – the planned captain's EP in each gameweek (TC adds
  one extra captain score).
* **Wildcard** – horizon points of an unlimited-transfer squad minus the best
  normal plan (after its hits).
* **Free Hit** – next-gameweek points of an unlimited one-week squad minus the
  normal plan's.

Double and blank gameweeks inside the horizon are flagged because they
usually decide chip timing. Chips are only suggested within their window
(e.g. the first set expires after GW19).
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from fpl_agent.optimizer.milp import OptimizationResult


def fixture_calendar(fixtures: pd.DataFrame, teams: pd.DataFrame, gws: list[int]) -> dict[int, dict]:
    """gw → {"doubles": [short names], "blanks": [short names]}."""
    short = dict(zip(teams["id"], teams["short_name"]))
    all_teams = set(teams["id"])
    out = {}
    for gw in gws:
        fx = fixtures[fixtures["event"] == gw]
        counts = Counter(list(fx["team_h"]) + list(fx["team_a"]))
        out[gw] = {
            "doubles": sorted(short.get(t, str(t)) for t, n in counts.items() if n >= 2),
            "blanks": sorted(short.get(t, str(t)) for t in all_teams - set(counts)),
        }
    return out


def _window_gws(chip: dict, gws: list[int]) -> list[int]:
    lo, hi = chip["window"]
    return [g for g in gws if lo <= g <= hi]


def chip_outlook(
    plan: OptimizationResult,
    chips: list[dict],
    calendar: dict[int, dict],
    wildcard: OptimizationResult | None = None,
    free_hit: OptimizationResult | None = None,
    names: dict[int, str] | None = None,
) -> list[str]:
    """Human-readable chip advice lines."""
    names = names or {}
    gws = plan.gameweeks
    lines: list[str] = []

    special = [f"GW{g}: " + "; ".join(
        part for part in (
            f"double for {', '.join(c['doubles'])}" if c["doubles"] else "",
            f"blank for {', '.join(c['blanks'])}" if c["blanks"] else "",
        ) if part)
        for g, c in calendar.items() if c["doubles"] or c["blanks"]]
    lines.append("Fixture calendar: " + (" | ".join(special) if special else
                                         f"no doubles or blanks in GW{gws[0]}–{gws[-1]}."))

    available = [c for c in chips if c.get("status") == "available"]
    if not available:
        lines.append("No chips available in the current window.")
        return lines

    for chip in available:
        in_window = _window_gws(chip, gws)
        lo, hi = chip["window"]
        expiry = f"expires after GW{hi}"
        if not in_window:
            lines.append(f"{chip['label']}: available, but its window (GW{lo}–{hi}) is outside the horizon.")
            continue
        name = chip["name"]
        if name == "bboost":
            best = max(in_window, key=lambda g: plan.bench_points.get(g, 0))
            lines.append(
                f"Bench Boost ({expiry}): best in GW{best}, bench worth "
                f"{plan.bench_points.get(best, 0):.1f} EP (vs. "
                f"{plan.bench_points.get(gws[0], 0):.1f} in GW{gws[0]})."
            )
        elif name == "3xc":
            best = max(in_window, key=lambda g: plan.captain_points.get(g, 0))
            cap = names.get(plan.captains.get(best), "?")
            lines.append(
                f"Triple Captain ({expiry}): best in GW{best} on {cap}, worth "
                f"+{plan.captain_points.get(best, 0):.1f} EP."
            )
        elif name == "wildcard" and wildcard is not None:
            gain = wildcard.horizon_points - (plan.horizon_points - plan.transfer_cost)
            lines.append(
                f"Wildcard ({expiry}): a full rebuild now gains {gain:+.1f} EP over "
                f"GW{gws[0]}–{gws[-1]} vs. the normal plan ({len(wildcard.transfers_in)} changes)."
            )
        elif name == "freehit" and free_hit is not None:
            gain = free_hit.next_gw_points - (plan.next_gw_points - plan.transfer_cost)
            lines.append(
                f"Free Hit ({expiry}): a one-week squad gains {gain:+.1f} EP in GW{gws[0]}. "
                "Best saved for a blank or double gameweek."
            )
        if hi <= gws[-1] and name in {"bboost", "3xc", "wildcard", "freehit"}:
            lines.append(f"  ↳ {chip['label']} must be used by GW{hi} or it's lost.")
    return lines
