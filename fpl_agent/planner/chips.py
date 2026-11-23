"""Chip plan: which week to play each chip before it expires.

FPL hands out chips in sets with their own window: a set for GW1–19 that
expires unused after GW19, and a fresh set for GW20–38. A first-half chip
held past GW19 is lost, not saved, so the question is never "play it or keep
it": it's which of the weeks left in the window gets which chip. Only one chip
can be played per gameweek, so the chips compete for weeks and are scheduled
together.

Values per chip and week come from optimizer runs that look ahead to the end
of the window (up to ``LOOKAHEAD_CAP`` weeks):

* **Bench Boost**: EP of the four subs that week.
* **Triple Captain**: the captain's EP that week (TC adds one extra captain
  score).
* **Free Hit**: points of the best unlimited one-week squad that week minus
  the normal plan's XI. Pure points: none of the user's preferences (locks,
  bans, consistency, bench weight, transfer value) apply to a squad that only
  exists for one week (``FREE_HIT_SETTINGS``).
* **Wildcard** in week *g*: a squad built for the ``WILDCARD_WEEKS`` weeks from
  *g*, so every Wildcard week is judged on the same length of haul (even past
  the chip window: the squad carries into GW20+). It's compared with what
  normal transfers made in week *g* would give over the same weeks, plus the
  hits avoided and the free transfers kept (FPL keeps banked free transfers
  through a Wildcard), each worth ``ft_value``.

A Bench Boost, Triple Captain or Free Hit played after the Wildcard is valued
against the rebuilt squad. If a chip's window runs past the lookahead, it gets a "hold"
option worth its average weekly value, so it's only played now when this week
stands out.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import product

import pandas as pd

from fpl_agent.optimizer.milp import OptimizationResult

# Furthest the chip plan schedules. Beyond this the model's numbers are guesses.
LOOKAHEAD_CAP = 8
# A Wildcard squad is built for this long a haul (the user's rule: at least 4).
WILDCARD_WEEKS = 5
# A Free Hit squad only has to score that week. The tiny bench weight just
# breaks ties toward subs who play, for auto-subs.
FREE_HIT_SETTINGS = dict(bench_weight=0.01, consistency=0.0, ft_value=0.0,
                         locked=set(), banned=set())
CHIP_ORDER = ("wildcard", "freehit", "bboost", "3xc")
HOLD = None   # slot meaning "after the lookahead"


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


def single_week(forecast: pd.DataFrame, gw: int) -> pd.DataFrame:
    """The forecast cut down to one gameweek (for a Free Hit that week)."""
    ep, ret = f"expected_points_gw{gw}", f"p_return_gw{gw}"
    cols = ["player_id", ep] + ([ret] if ret in forecast.columns else [])
    out = forecast[cols].copy()
    out["total_expected_points"] = out[ep]
    return out


def block(forecast: pd.DataFrame, start: int, weeks: int) -> pd.DataFrame:
    """The forecast cut to weeks ``start .. start + weeks - 1``."""
    end = start + weeks - 1
    drop = [c for c in forecast.columns
            if (m := re.match(r"^(?:expected_points|p_return)_gw(\d+)$", c))
            and not start <= int(m.group(1)) <= end]
    out = forecast.drop(columns=drop)
    ep = [c for c in out.columns if c.startswith("expected_points_gw")]
    out["total_expected_points"] = out[ep].sum(axis=1)
    return out


def xi_points(res: OptimizationResult, forecast: pd.DataFrame, gw: int) -> float:
    """XI + captain EP for one week of a plan."""
    ep = forecast.set_index("player_id")[f"expected_points_gw{gw}"]
    return float(ep.reindex(res.lineups.get(gw, [])).fillna(0).sum()) + res.captain_points.get(gw, 0.0)


@dataclass
class ChipValues:
    """EP each chip adds in each week of the lookahead."""
    weeks: list[int]
    by_chip: dict[str, dict[int, float]]
    # Wildcard week → chip → gw → value of BB/TC/FH on that rebuilt squad.
    after_wildcard: dict[int, dict[str, dict[int, float]]] = field(default_factory=dict)
    captains: dict[int, int] = field(default_factory=dict)                    # gw → captain id
    wc_captains: dict[int, dict[int, int]] = field(default_factory=dict)      # WC week → gw → captain


def wildcard_gain(wildcard: OptimizationResult, normal: OptimizationResult,
                  forecast: pd.DataFrame, free_transfers: int, ft_value: float) -> float:
    """Wildcard over the normal plan for the same weeks.

    EP gained over the haul, plus the hits the normal plan would take, plus
    the free transfers it would spend (a Wildcard keeps them banked).
    """
    ep = sum(xi_points(wildcard, forecast, g) - xi_points(normal, forecast, g)
             for g in wildcard.gameweeks)
    kept = min(len(normal.transfers_in), free_transfers)
    return ep + normal.transfer_cost + ft_value * kept


def chip_values(
    base: OptimizationResult,
    forecast: pd.DataFrame,
    wildcards: dict[int, tuple[OptimizationResult, float]] | None = None,
    free_hits: dict[int, OptimizationResult] | None = None,
) -> ChipValues:
    """Value every chip in every week of *base*'s lookahead.

    *wildcards* maps a week to (squad built from that week, its
    ``wildcard_gain``); *free_hits* maps a week to the best one-week squad.
    """
    weeks = base.gameweeks
    by_chip: dict[str, dict[int, float]] = {
        "bboost": {g: base.bench_points.get(g, 0.0) for g in weeks},
        "3xc": {g: base.captain_points.get(g, 0.0) for g in weeks},
    }
    base_xi = {g: xi_points(base, forecast, g) for g in weeks}
    fh_pts = {g: r.next_gw_points for g, r in (free_hits or {}).items()}
    if fh_pts:
        by_chip["freehit"] = {g: max(0.0, fh_pts[g] - base_xi[g]) for g in weeks if g in fh_pts}

    after: dict[int, dict[str, dict[int, float]]] = {}
    wc_caps: dict[int, dict[int, int]] = {}
    if wildcards:
        by_chip["wildcard"] = {}
        for w, (wc, gain) in wildcards.items():
            by_chip["wildcard"][w] = gain
            # Chips later in the Wildcard's haul are valued on its squad;
            # past the haul you'd have moved on, so the normal plan stands.
            haul = [g for g in wc.gameweeks if g in base_xi]
            after[w] = {"bboost": {g: wc.bench_points[g] for g in haul},
                        "3xc": {g: wc.captain_points[g] for g in haul}}
            if fh_pts:
                after[w]["freehit"] = {g: max(0.0, fh_pts[g] - xi_points(wc, forecast, g))
                                       for g in haul if g in fh_pts}
            wc_caps[w] = dict(wc.captains)
    return ChipValues(weeks, by_chip, after, dict(base.captains), wc_caps)


@dataclass
class ChipPick:
    name: str
    label: str
    gw: int | None          # None: hold until after the lookahead
    gain: float
    expires: int            # last GW of its window
    on_wildcard_squad: bool = False
    wildcard_gw: int | None = None   # set when valued on the squad rebuilt that week


def schedule_chips(values: ChipValues, chips: list[dict],
                   fixed: dict[str, int] | None = None) -> list[ChipPick]:
    """Best assignment of available chips to distinct weeks.

    *chips* are ``chip_status`` rows; only ``available`` ones are scheduled.
    *fixed* pins a chip to a week (the one the user has switched on).
    """
    fixed = fixed or {}
    weeks = values.weeks
    open_chips = sorted((c for c in chips if c.get("status") == "available"
                         and c["name"] in values.by_chip),
                        key=lambda c: CHIP_ORDER.index(c["name"]) if c["name"] in CHIP_ORDER else 9)
    if not open_chips or not weeks:
        return []

    def options(c: dict) -> list[int | None]:
        if c["name"] in fixed:
            return [fixed[c["name"]]]
        lo, hi = c["window"]
        slots: list[int | None] = [g for g in weeks if lo <= g <= hi]
        if hi > weeks[-1]:
            slots.insert(0, HOLD)   # first, so a tie keeps the chip
        return slots

    def hold_value(c: dict) -> float:
        lo, hi = c["window"]
        vals = [v for g, v in values.by_chip[c["name"]].items() if lo <= g <= hi]
        return sum(vals) / len(vals) if vals else 0.0

    def value(c: dict, gw: int | None, wc_gw: int | None) -> tuple[float, bool]:
        if gw is HOLD:
            return hold_value(c), False
        on_wc = (wc_gw is not None and gw > wc_gw
                 and gw in values.after_wildcard.get(wc_gw, {}).get(c["name"], {}))
        table = values.after_wildcard[wc_gw][c["name"]] if on_wc else values.by_chip[c["name"]]
        return table.get(gw, 0.0), on_wc

    best: tuple[float, list[ChipPick]] | None = None
    for combo in product(*(options(c) for c in open_chips)):
        played = [g for g in combo if g is not HOLD]
        if len(played) != len(set(played)):
            continue  # one chip per gameweek
        wc_gw = next((g for c, g in zip(open_chips, combo) if c["name"] == "wildcard"), None)
        picks, total = [], 0.0
        for c, g in zip(open_chips, combo):
            v, on_wc = value(c, g, wc_gw)
            total += v
            picks.append(ChipPick(c["name"], c["label"], g, round(v, 1), c["window"][1],
                                  on_wc, wc_gw if on_wc else None))
        # Ties go to the earlier combo: holding first, then earlier weeks.
        if best is None or total > best[0] + 1e-9:
            best = (total, picks)
    assert best is not None
    return sorted(best[1], key=lambda p: (p.gw is HOLD, p.gw or 0))


def chip_outlook(
    picks: list[ChipPick],
    values: ChipValues | None,
    chips: list[dict],
    calendar: dict[int, dict],
    names: dict[int, str] | None = None,
) -> list[str]:
    """Human-readable chip plan."""
    names = names or {}
    lines: list[str] = []
    weeks = values.weeks if values else sorted(calendar)

    special = [f"GW{g}: " + "; ".join(
        part for part in (
            f"double for {', '.join(c['doubles'])}" if c["doubles"] else "",
            f"blank for {', '.join(c['blanks'])}" if c["blanks"] else "",
        ) if part)
        for g, c in calendar.items() if c["doubles"] or c["blanks"]]
    span = f"GW{weeks[0]}–{weeks[-1]}" if weeks else "the horizon"
    lines.append("Fixture calendar: " + (" | ".join(special) if special else
                                         f"no doubles or blanks in {span}."))

    available = [c for c in chips if c.get("status") == "available"]
    upcoming = [c for c in chips if c.get("status") == "upcoming"]
    if not available:
        nxt = min((c["window"][0] for c in upcoming), default=None)
        lines.append("No chips left in this window." +
                     (f" A fresh set unlocks in GW{nxt}." if nxt else ""))
        return lines
    if not picks:
        lines.append("Chips available, but none could be valued for the weeks ahead.")
        return lines

    expiry = max(p.expires for p in picks)
    played = [p for p in picks if p.gw is not HOLD]
    left = [g for g in weeks if g <= expiry]
    header = f"Chip plan: {len(available)} chip{'s' if len(available) != 1 else ''} to play"
    if expiry <= weeks[-1]:
        header += (f" in {len(left)} week{'s' if len(left) != 1 else ''} (they expire after GW{expiry}"
                   + (f"; a fresh set unlocks in GW{expiry + 1}" if upcoming else "") + ")."
                   + " One chip per week, so they're planned together.")
    else:
        header += f" before GW{expiry}. Weeks past GW{weeks[-1]} are beyond the forecast."
    lines.append(header)

    for p in picks:
        if p.gw is HOLD:
            lines.append(f"Hold {p.label}: no week up to GW{weeks[-1]} beats an average week "
                         f"(~{p.gain:.1f} EP); use it by GW{p.expires}.")
            continue
        cal = calendar.get(p.gw, {})
        why = {
            "wildcard": f"+{p.gain:.1f} over GW{p.gw}–{p.gw + WILDCARD_WEEKS - 1} vs. normal transfers "
                        "that week (EP, plus hits avoided and free transfers kept)",
            "freehit": f"+{p.gain:.1f} EP for one week" + (" over the wildcard squad" if p.on_wildcard_squad else ""),
            "bboost": f"bench worth {p.gain:.1f} EP" + (" on the wildcard squad" if p.on_wildcard_squad else ""),
            "3xc": f"+{p.gain:.1f} EP on "
                   + names.get((values.wc_captains.get(p.wildcard_gw, {}) if p.on_wildcard_squad
                                else values.captains).get(p.gw), "your captain")
                   + (" (wildcard squad)" if p.on_wildcard_squad else ""),
        }.get(p.name, f"+{p.gain:.1f} EP")
        if cal.get("doubles") and p.name in {"bboost", "3xc", "freehit"}:
            why += f"; double gameweek for {', '.join(cal['doubles'])}"
        if cal.get("blanks") and p.name == "freehit":
            why += f"; blank for {', '.join(cal['blanks'])}"
        lines.append(f"GW{p.gw} {p.label}: {why}.")

    now = next((p for p in played if p.gw == weeks[0]), None)
    lines.append(f"This week: play {now.label}." if now else
                 f"This week: no chip. Next up: {played[0].label} in GW{played[0].gw}." if played else
                 "This week: no chip.")
    if values and len(weeks) > 1:
        lines.append("Later weeks are forecasts and will shift; the plan is redone every week.")
    return lines
