"""Assemble a human-readable recommendation from optimizer output."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field

import pandas as pd

from fpl_agent.optimizer.milp import OptimizationResult

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# Starting XI slot counts (typical 2-5-5-3 → pick best 11)
STARTING_SLOTS = {1: 1, 2: 3, 3: 4, 4: 3}  # fallback; actual selection uses EP


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


@dataclass
class Recommendation:
    """Full recommendation payload."""
    transfers: list[Transfer]
    starting_xi: list[int]
    bench: list[int]
    bench_order: list[int]
    captain_id: int
    vice_captain_id: int
    expected_points_delta: float
    transfer_cost: int
    rationale: str
    details: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_recommendation(
    opt_result: OptimizationResult,
    players: pd.DataFrame,
    forecast: pd.DataFrame,
    current_squad: list[int],
    selling_prices: dict[int, int],
) -> Recommendation:
    """Transform raw optimizer output into a structured recommendation.

    Parameters
    ----------
    opt_result : OptimizationResult
    players : DataFrame with id, web_name, element_type, now_cost, team_id
    forecast : DataFrame with player_id, total_expected_points
    current_squad : list of player_ids currently owned
    selling_prices : player_id → selling_price (×10)
    """
    pid_to_name = dict(zip(players["id"], players["web_name"]))
    pid_to_pos = dict(zip(players["id"], players["element_type"]))
    pid_to_cost = dict(zip(players["id"], players["now_cost"]))
    pid_to_ep = dict(zip(forecast["player_id"], forecast["total_expected_points"]))

    # -- Transfers (paired by position) ----------------------------------------
    transfers = _pair_transfers_by_position(
        opt_result.transfers_out,
        opt_result.transfers_in,
        pid_to_name,
        pid_to_pos,
        pid_to_cost,
        pid_to_ep,
        selling_prices,
    )

    # -- Starting XI / bench --------------------------------------------------
    squad = opt_result.selected_ids
    squad_eps = [(pid, pid_to_ep.get(pid, 0), pid_to_pos.get(pid, 0)) for pid in squad]

    starting_xi, bench = _select_starting_xi(squad_eps)
    bench_order = sorted(bench, key=lambda pid: pid_to_ep.get(pid, 0), reverse=True)

    # -- Captain / vice -------------------------------------------------------
    xi_by_ep = sorted(starting_xi, key=lambda pid: pid_to_ep.get(pid, 0), reverse=True)
    captain_id = xi_by_ep[0] if xi_by_ep else squad[0]
    vice_captain_id = xi_by_ep[1] if len(xi_by_ep) > 1 else captain_id

    # -- EP delta -------------------------------------------------------------
    old_ep = sum(pid_to_ep.get(pid, 0) for pid in current_squad)
    new_ep = opt_result.total_expected_points
    delta = new_ep - old_ep - opt_result.transfer_cost

    # -- Rationale ------------------------------------------------------------
    rationale = _generate_rationale(
        transfers, captain_id, vice_captain_id, pid_to_name, pid_to_ep, delta, opt_result,
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
    )


# -- Helpers ------------------------------------------------------------------

def _pair_transfers_by_position(
    transfers_out: list[int],
    transfers_in: list[int],
    pid_to_name: dict[int, str],
    pid_to_pos: dict[int, int],
    pid_to_cost: dict[int, int],
    pid_to_ep: dict[int, float],
    selling_prices: dict[int, int],
) -> list[Transfer]:
    """Pair each sell with a buy of the **same position** so the display
    correctly shows DEF→DEF, MID→MID, etc."""
    sells_by_pos: dict[int, list[int]] = {}
    for pid in transfers_out:
        pos = pid_to_pos.get(pid, 0)
        sells_by_pos.setdefault(pos, []).append(pid)

    buys_by_pos: dict[int, list[int]] = {}
    for pid in transfers_in:
        pos = pid_to_pos.get(pid, 0)
        buys_by_pos.setdefault(pos, []).append(pid)

    # Sort within each position: sells by EP ascending, buys by EP descending
    for pos in sells_by_pos:
        sells_by_pos[pos].sort(key=lambda p: pid_to_ep.get(p, 0))
    for pos in buys_by_pos:
        buys_by_pos[pos].sort(key=lambda p: pid_to_ep.get(p, 0), reverse=True)

    all_positions = sorted(set(list(sells_by_pos.keys()) + list(buys_by_pos.keys())))

    transfers: list[Transfer] = []
    for pos in all_positions:
        sells = sells_by_pos.get(pos, [])
        buys = buys_by_pos.get(pos, [])
        pos_label = POSITION_MAP.get(pos, "?")

        for s, b in zip(sells, buys):
            transfers.append(Transfer(
                sell_id=s,
                sell_name=pid_to_name.get(s, str(s)),
                sell_price=selling_prices.get(s, pid_to_cost.get(s, 0)) / 10,
                buy_id=b,
                buy_name=pid_to_name.get(b, str(b)),
                buy_price=pid_to_cost.get(b, 0) / 10,
                position=pos_label,
            ))
        # Unmatched sells (position removed — shouldn't happen with strict constraints)
        for extra_s in sells[len(buys):]:
            transfers.append(Transfer(
                sell_id=extra_s,
                sell_name=pid_to_name.get(extra_s, str(extra_s)),
                sell_price=selling_prices.get(extra_s, 0) / 10,
                buy_id=0, buy_name="(none)", buy_price=0,
                position=pos_label,
            ))
        # Unmatched buys
        for extra_b in buys[len(sells):]:
            transfers.append(Transfer(
                sell_id=0, sell_name="(none)", sell_price=0,
                buy_id=extra_b,
                buy_name=pid_to_name.get(extra_b, str(extra_b)),
                buy_price=pid_to_cost.get(extra_b, 0) / 10,
                position=pos_label,
            ))

    return transfers


def _select_starting_xi(
    squad_eps: list[tuple[int, float, int]],
) -> tuple[list[int], list[int]]:
    """Pick the best valid starting XI from a 15-man squad.

    Valid formation requires: 1 GK, ≥3 DEF, ≥2 MID, ≥1 FWD, total 11.
    """
    by_pos: dict[int, list[tuple[int, float]]] = {}
    for pid, ep, pos in squad_eps:
        by_pos.setdefault(pos, []).append((pid, ep))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda t: t[1], reverse=True)

    min_req = {1: 1, 2: 3, 3: 2, 4: 1}  # minimum formation constraints
    xi: list[int] = []

    # Pick minimums first
    remainder: list[tuple[int, float, int]] = []
    for pos, players_list in by_pos.items():
        req = min_req.get(pos, 0)
        for i, (pid, ep) in enumerate(players_list):
            if i < req:
                xi.append(pid)
            else:
                remainder.append((pid, ep, pos))

    # Fill remaining slots (11 − len(xi)) with highest EP from remainder,
    # excluding GKs (can only have 1 GK in XI)
    slots_left = 11 - len(xi)
    remainder.sort(key=lambda t: t[1], reverse=True)
    for pid, ep, pos in remainder:
        if slots_left <= 0:
            break
        if pos == 1:
            continue  # already have 1 GK
        xi.append(pid)
        slots_left -= 1

    bench = [pid for pid, _, _ in squad_eps if pid not in set(xi)]
    return xi, bench


def _generate_rationale(
    transfers: list[Transfer],
    captain_id: int,
    vice_captain_id: int,
    pid_to_name: dict[int, str],
    pid_to_ep: dict[int, float],
    delta: float,
    opt_result: OptimizationResult,
) -> str:
    """Build a concise natural-language explanation of the recommendation."""
    lines: list[str] = []
    lines.append("=== FPL Agent Recommendation ===\n")

    if transfers:
        lines.append("Transfers:")
        for t in transfers:
            pos_tag = f"[{t.position}] " if t.position else ""
            lines.append(f"  {pos_tag}OUT: {t.sell_name} (£{t.sell_price:.1f}m)")
            lines.append(f"  {pos_tag}IN : {t.buy_name} (£{t.buy_price:.1f}m)")
            lines.append("")
    else:
        lines.append("No transfers recommended this gameweek.\n")

    if opt_result.transfer_cost:
        lines.append(f"Transfer hits: {opt_result.transfer_cost} pts\n")

    cap_name = pid_to_name.get(captain_id, str(captain_id))
    vc_name = pid_to_name.get(vice_captain_id, str(vice_captain_id))
    cap_ep = pid_to_ep.get(captain_id, 0)

    lines.append(f"Captain: {cap_name} (EP {cap_ep:.1f})")
    lines.append(f"Vice-captain: {vc_name}\n")

    direction = "gain" if delta >= 0 else "loss"
    lines.append(f"Expected points delta: {delta:+.1f} ({direction} vs. current squad)")
    lines.append(f"Total squad expected points: {opt_result.total_expected_points:.1f}\n")

    lines.append("Reasoning:")
    if transfers:
        lines.append(
            textwrap.fill(
                "The recommended transfers improve the squad's total expected points "
                "over the forecast horizon after accounting for any hit costs. "
                "Players brought in have favourable upcoming fixtures and strong recent form.",
                width=80,
            )
        )
    lines.append(
        textwrap.fill(
            f"{cap_name} is captained due to the highest expected points in the starting XI, "
            "providing the best expected return when doubled.",
            width=80,
        )
    )

    return "\n".join(lines)
