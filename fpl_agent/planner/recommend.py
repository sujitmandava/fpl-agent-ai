"""Assemble a human-readable recommendation from optimizer output."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fpl_agent.optimizer.milp import OptimizationResult

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
# A buy is a "close call" when another player at the same position is within
# this many horizon xPts (or 5% of the buy's total, whichever is larger).
CLOSE_MARGIN = 1.0
CLOSE_MAX_EXTRA_COST = 10       # without a known bank, alternatives may cost up to £1.0m more
CAPTAIN_CLOSE = 0.3             # next-GW xPts gap for a close captaincy call


@dataclass
class Transfer:
    """A single sell/buy pair."""
    sell_id: int
    sell_name: str
    sell_price: float
    buy_id: int
    buy_name: str
    buy_price: float
    position: str = ""
    ep_gain_next: float = 0.0
    ep_gain_horizon: float = 0.0
    # Near-equal options: [{"id", "name", "price", "xpts", "delta"}], delta =
    # their horizon xPts − the buy's. Empty when the pick is clear.
    alternatives: list[dict] = field(default_factory=list)


@dataclass
class Recommendation:
    """Full recommendation payload."""
    transfers: list[Transfer]
    starting_xi: list[int]
    bench: list[int]
    bench_order: list[int]              # [bench GK, outfield sub 1, 2, 3]
    captain_id: int
    vice_captain_id: int
    expected_points_delta: float        # next GW, vs. current squad, after hits
    transfer_cost: int
    rationale: str
    details: pd.DataFrame = field(default_factory=pd.DataFrame)
    next_gw: int | None = None
    next_gw_points: float = 0.0
    horizon_points: float = 0.0
    horizon_delta: float | None = None  # vs. current squad over the horizon, after hits


def build_recommendation(
    opt_result: OptimizationResult,
    players: pd.DataFrame,
    forecast: pd.DataFrame,
    current_squad: list[int],
    selling_prices: dict[int, int],
    baseline: OptimizationResult | None = None,
    fixtures: pd.DataFrame | None = None,
    teams: pd.DataFrame | None = None,
    bank: int | None = None,
) -> Recommendation:
    """Transform raw optimizer output into a structured recommendation.

    Parameters
    ----------
    opt_result : OptimizationResult
        The plan to recommend.
    baseline : OptimizationResult, optional
        The current squad optimised with zero transfers; used for the
        expected-points delta. Without it the delta is reported as 0.
    fixtures, teams : DataFrame, optional
        Used to list upcoming opponents in the rationale.
    bank : int, optional
        Bank before transfers (×10). Close-call alternatives are limited to
        what the money left after the plan's transfers could buy.
    """
    pid_to_name = dict(zip(players["id"], players["web_name"]))
    pid_to_pos = dict(zip(players["id"], players["element_type"]))
    pid_to_cost = dict(zip(players["id"], players["now_cost"]))
    pid_to_team = dict(zip(players["id"], players["team_id"]))
    pid_to_ep = dict(zip(forecast["player_id"], forecast["total_expected_points"]))
    next_col = "expected_points_next" if "expected_points_next" in forecast.columns else "total_expected_points"
    pid_to_next = dict(zip(forecast["player_id"], forecast[next_col]))

    transfers = _pair_transfers_by_position(
        opt_result.transfers_out, opt_result.transfers_in,
        pid_to_name, pid_to_pos, pid_to_cost, pid_to_ep, pid_to_next, selling_prices,
    )
    if bank is not None:
        left = bank + sum(selling_prices.get(p, pid_to_cost.get(p, 0)) for p in opt_result.transfers_out) \
            - sum(pid_to_cost.get(p, 0) for p in opt_result.transfers_in)
        extra = max(int(left), 0)
    else:
        extra = CLOSE_MAX_EXTRA_COST
    for t in transfers:
        if t.buy_id:
            t.alternatives = close_alternatives(t.buy_id, set(opt_result.selected_ids),
                                                pid_to_name, pid_to_pos, pid_to_cost, pid_to_ep,
                                                max_extra_cost=extra)

    # -- Lineup ---------------------------------------------------------------
    squad = opt_result.selected_ids
    starting_xi = opt_result.starting_xi or best_xi(squad, pid_to_pos, pid_to_next)
    starting_xi = sorted(starting_xi, key=lambda p: (pid_to_pos.get(p, 0), -pid_to_next.get(p, 0)))
    bench = [p for p in squad if p not in set(starting_xi)]
    bench_gk = [p for p in bench if pid_to_pos.get(p) == 1]
    bench_out = sorted((p for p in bench if pid_to_pos.get(p) != 1),
                       key=lambda p: pid_to_next.get(p, 0), reverse=True)
    bench_order = bench_gk + bench_out

    if opt_result.captain_id is not None:
        captain_id = opt_result.captain_id
        vice_captain_id = opt_result.vice_captain_id or captain_id
    else:
        by_next = sorted(starting_xi, key=lambda p: pid_to_next.get(p, 0), reverse=True)
        captain_id, vice_captain_id = by_next[0], by_next[1]

    # -- Deltas ---------------------------------------------------------------
    if baseline is not None:
        delta = opt_result.next_gw_points - baseline.next_gw_points - opt_result.transfer_cost
        # A Free Hit plan covers one GW; comparing it with a multi-GW baseline is meaningless.
        same_span = opt_result.gameweeks == baseline.gameweeks
        horizon_delta = round(
            opt_result.horizon_points - baseline.horizon_points - opt_result.transfer_cost, 2
        ) if same_span else None
    else:
        delta, horizon_delta = 0.0, None

    next_gw = opt_result.gameweeks[0] if opt_result.gameweeks else None
    upcoming = _upcoming_opponents(fixtures, teams, opt_result.gameweeks[:3]) if fixtures is not None else {}

    rationale = _generate_rationale(
        transfers=transfers,
        captain_id=captain_id,
        vice_captain_id=vice_captain_id,
        pid_to_name=pid_to_name,
        pid_to_next=pid_to_next,
        pid_to_team=pid_to_team,
        upcoming=upcoming,
        opt_result=opt_result,
        delta=delta,
        horizon_delta=horizon_delta,
        next_gw=next_gw,
    )

    return Recommendation(
        transfers=transfers,
        starting_xi=starting_xi,
        bench=bench,
        bench_order=bench_order,
        captain_id=captain_id,
        vice_captain_id=vice_captain_id,
        expected_points_delta=round(delta, 2),
        transfer_cost=opt_result.transfer_cost,
        rationale=rationale,
        details=opt_result.details,
        next_gw=next_gw,
        next_gw_points=opt_result.next_gw_points,
        horizon_points=opt_result.horizon_points,
        horizon_delta=horizon_delta,
    )


# -- Helpers ------------------------------------------------------------------

def close_alternatives(
    buy_id: int, squad: set[int], pid_to_name: dict, pid_to_pos: dict,
    pid_to_cost: dict, pid_to_ep: dict, limit: int = 3, max_extra_cost: int = CLOSE_MAX_EXTRA_COST,
) -> list[dict]:
    """Affordable players at the buy's position whose horizon xPts are within the close margin.

    *max_extra_cost* (×10) is how much more than the buy they may cost.
    Ignores the 3-per-club rule, so an alternative may need other changes.
    """
    buy_ep, pos = pid_to_ep.get(buy_id, 0.0), pid_to_pos.get(buy_id)
    margin = max(CLOSE_MARGIN, 0.05 * buy_ep)
    max_cost = pid_to_cost.get(buy_id, 0) + max_extra_cost
    alts = [
        {"id": int(pid), "name": pid_to_name.get(pid, str(pid)), "price": pid_to_cost.get(pid, 0) / 10,
         "xpts": round(ep, 2), "delta": round(ep - buy_ep, 2)}
        for pid, ep in pid_to_ep.items()
        if pid != buy_id and pid not in squad and pid_to_pos.get(pid) == pos
        and abs(ep - buy_ep) <= margin and pid_to_cost.get(pid, 0) <= max_cost
    ]
    return sorted(alts, key=lambda a: -a["xpts"])[:limit]


def best_xi(squad: list[int], pid_to_pos: dict, pid_to_next: dict) -> list[int]:
    """Best valid XI by xPts (1 GK, at least 3 DEF / 2 MID / 1 FWD).

    Used when the optimizer gave no lineup, and for rivals' held squads.
    """
    by_pos: dict[int, list[int]] = {}
    for p in sorted(squad, key=lambda p: pid_to_next.get(p, 0), reverse=True):
        by_pos.setdefault(pid_to_pos.get(p, 0), []).append(p)
    xi = by_pos.get(1, [])[:1] + by_pos.get(2, [])[:3] + by_pos.get(3, [])[:2] + by_pos.get(4, [])[:1]
    rest = sorted((p for p in squad if p not in xi and pid_to_pos.get(p) != 1),
                  key=lambda p: pid_to_next.get(p, 0), reverse=True)
    for p in rest:
        if len(xi) == 11:
            break
        pos = pid_to_pos.get(p)
        cap = {2: 5, 3: 5, 4: 3}[pos]
        if sum(1 for q in xi if pid_to_pos.get(q) == pos) < cap:
            xi.append(p)
    return xi


def _pair_transfers_by_position(
    transfers_out: list[int],
    transfers_in: list[int],
    pid_to_name: dict[int, str],
    pid_to_pos: dict[int, int],
    pid_to_cost: dict[int, int],
    pid_to_ep: dict[int, float],
    pid_to_next: dict[int, float],
    selling_prices: dict[int, int],
) -> list[Transfer]:
    """Pair each sell with a buy of the **same position** (DEF→DEF, etc.)."""
    sells_by_pos: dict[int, list[int]] = {}
    for pid in transfers_out:
        sells_by_pos.setdefault(pid_to_pos.get(pid, 0), []).append(pid)
    buys_by_pos: dict[int, list[int]] = {}
    for pid in transfers_in:
        buys_by_pos.setdefault(pid_to_pos.get(pid, 0), []).append(pid)

    for pos in sells_by_pos:
        sells_by_pos[pos].sort(key=lambda p: pid_to_ep.get(p, 0))
    for pos in buys_by_pos:
        buys_by_pos[pos].sort(key=lambda p: pid_to_ep.get(p, 0), reverse=True)

    transfers: list[Transfer] = []
    for pos in sorted(set(sells_by_pos) | set(buys_by_pos)):
        sells = sells_by_pos.get(pos, [])
        buys = buys_by_pos.get(pos, [])
        label = POSITION_MAP.get(pos, "?")
        for i in range(max(len(sells), len(buys))):
            s = sells[i] if i < len(sells) else 0
            b = buys[i] if i < len(buys) else 0
            transfers.append(Transfer(
                sell_id=s,
                sell_name=pid_to_name.get(s, "(none)") if s else "(none)",
                sell_price=selling_prices.get(s, pid_to_cost.get(s, 0)) / 10 if s else 0.0,
                buy_id=b,
                buy_name=pid_to_name.get(b, "(none)") if b else "(none)",
                buy_price=pid_to_cost.get(b, 0) / 10 if b else 0.0,
                position=label,
                ep_gain_next=round(pid_to_next.get(b, 0) - pid_to_next.get(s, 0), 2),
                ep_gain_horizon=round(pid_to_ep.get(b, 0) - pid_to_ep.get(s, 0), 2),
            ))
    return transfers


def _upcoming_opponents(
    fixtures: pd.DataFrame, teams: pd.DataFrame | None, gws: list[int],
) -> dict[int, list[str]]:
    """team_id → ['ARS (H) 4', ...] for the given gameweeks; blanks shown as '—'."""
    short = dict(zip(teams["id"], teams["short_name"])) if teams is not None else {}
    out: dict[int, list[str]] = {}
    fx = fixtures[fixtures["event"].isin(gws)].sort_values(["event", "kickoff_time"]) \
        if "kickoff_time" in fixtures.columns else fixtures[fixtures["event"].isin(gws)]
    team_ids = set(fixtures["team_h"]) | set(fixtures["team_a"])
    for tid in team_ids:
        labels = []
        for gw in gws:
            gw_fx = fx[fx["event"] == gw]
            items = []
            for f in gw_fx.itertuples(index=False):
                if f.team_h == tid:
                    items.append(f"{short.get(f.team_a, f.team_a)} (H) {f.team_h_difficulty}")
                elif f.team_a == tid:
                    items.append(f"{short.get(f.team_h, f.team_h)} (A) {f.team_a_difficulty}")
            labels.append(" + ".join(items) if items else "—")
        out[int(tid)] = labels
    return out


def _generate_rationale(
    *,
    transfers: list[Transfer],
    captain_id: int,
    vice_captain_id: int,
    pid_to_name: dict[int, str],
    pid_to_next: dict[int, float],
    pid_to_team: dict[int, int],
    upcoming: dict[int, list[str]],
    opt_result: OptimizationResult,
    delta: float,
    horizon_delta: float | None,
    next_gw: int | None,
) -> str:
    """Explain the recommendation using the numbers behind it."""
    gw_label = f"GW{next_gw}" if next_gw else "next GW"
    fx = lambda pid: ", ".join(upcoming.get(pid_to_team.get(pid, -1), [])) or "n/a"  # noqa: E731

    lines: list[str] = []
    if transfers:
        lines.append("Transfers (xPts gain next GW / over horizon; next fixtures with FPL FDR):")
        for t in transfers:
            lines.append(
                f"  [{t.position}] {t.sell_name} → {t.buy_name}: "
                f"{t.ep_gain_next:+.1f} / {t.ep_gain_horizon:+.1f}  ({fx(t.buy_id) if t.buy_id else ''})"
            )
            for a in t.alternatives:
                cost = a["price"] - t.buy_price
                lines.append(f"      close call: {a['name']} {a['delta']:+.1f} xPts, "
                             f"{'+' if cost >= 0 else '-'}£{abs(cost):.1f}m")
        if opt_result.transfer_cost:
            lines.append(f"  Hits: -{opt_result.transfer_cost} pts")
    else:
        lines.append("No transfer clears the bar this week. Bank the free transfer.")

    lines.append("")
    lines.append(
        f"Captain: {pid_to_name.get(captain_id, captain_id)} "
        f"({pid_to_next.get(captain_id, 0):.1f} EP in {gw_label}; {fx(captain_id)})"
    )
    lines.append(
        f"Vice:    {pid_to_name.get(vice_captain_id, vice_captain_id)} "
        f"({pid_to_next.get(vice_captain_id, 0):.1f} EP)"
    )
    gap = pid_to_next.get(captain_id, 0) - pid_to_next.get(vice_captain_id, 0)
    if gap < CAPTAIN_CLOSE:
        lines.append(f"  Close call: captain and vice are {gap:.1f} xPts apart; either is defensible.")
    lines.append("")
    lines.append(f"Projected {gw_label} (XI + captain): {opt_result.next_gw_points:.1f}")
    lines.append(f"Change vs. no transfers, {gw_label}: {delta:+.1f} (after hits)")
    if horizon_delta is not None:
        n = len(opt_result.gameweeks)
        lines.append(f"Change vs. no transfers, next {n} GWs: {horizon_delta:+.1f} (after hits)")
    lines.append("")
    lines.append(
        "xPts model: minutes, share of team chances, a little finishing form, defensive "
        "contributions, saves, bonus and opponent-adjusted team strength. "
        "Check team news before the deadline."
    )
    return "\n".join(lines)
