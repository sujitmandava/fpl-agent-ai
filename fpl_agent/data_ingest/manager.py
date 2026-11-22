"""Derive a manager's transfer state (free transfers, selling prices, bank)
from FPL API payloads.

They are reconstructed from public endpoints (no login):

* free transfers: replayed from ``/entry/{id}/history/`` (transfers made per
  gameweek plus chips played);
* selling prices: purchase price comes from ``/entry/{id}/transfers/`` (or the
  player's price in the manager's first gameweek for players never transferred
  in), then FPL's sell-on rule is applied (you keep half of any rise, rounded
  down to £0.1m).
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_FREE_TRANSFERS = 5
TRANSFER_RESET_CHIPS = {"wildcard", "freehit"}


@dataclass
class ManagerState:
    """What the optimizer needs to know about the manager's squad."""

    squad: list[int]
    selling_prices: dict[int, int]       # player_id → selling price (×10)
    bank: int                            # ×10
    free_transfers: int
    source: str                          # "public" or "memory"
    notes: list[str] = field(default_factory=list)
    chips_played: list[dict] = field(default_factory=list)   # [{"name", "event"}]
    entry: dict = field(default_factory=dict)                # /entry/{id}/ payload
    purchase_prices: dict[int, int] = field(default_factory=dict)


CHIP_LABELS = {"wildcard": "Wildcard", "freehit": "Free Hit",
               "bboost": "Bench Boost", "3xc": "Triple Captain"}


def chip_status(chip_defs: list[dict], chips_played: list[dict], next_gw: int) -> list[dict]:
    """Status of every chip instance this season.

    FPL issues chips per window (e.g. one set for GW1–19, one for GW20–38).
    A played chip uses up the instance whose window contains the gameweek it
    was played in. Returns one dict per instance with ``status`` in
    {"played", "available", "upcoming", "expired"}.
    """
    used = [dict(c) for c in chips_played]
    out = []
    for d in sorted(chip_defs, key=lambda d: (d["start_event"], d["name"])):
        entry = {
            "name": d["name"],
            "label": CHIP_LABELS.get(d["name"], d["name"]),
            "window": [d["start_event"], d["stop_event"]],
        }
        match = next((c for c in used if c["name"] == d["name"]
                      and d["start_event"] <= c["event"] <= d["stop_event"]), None)
        if match:
            used.remove(match)
            entry.update(status="played", event=match["event"])
        elif next_gw > d["stop_event"]:
            entry["status"] = "expired"
        elif next_gw < d["start_event"]:
            entry["status"] = "upcoming"
        else:
            entry["status"] = "available"
        out.append(entry)
    return out


def selling_price(purchase: int, now: int) -> int:
    """FPL sell-on rule: you receive half of any price rise, rounded down.

    Prices are in tenths of £m. A fall is passed on in full.
    """
    if now <= purchase:
        return now
    return purchase + (now - purchase) // 2


def compute_free_transfers(
    history_current: list[dict],
    chips: list[dict],
    max_ft: int = MAX_FREE_TRANSFERS,
) -> int:
    """Replay the season to get the free transfers available for the *next*
    gameweek.

    Rules applied:
    * The first gameweek a manager plays has unlimited transfers; they start
      the following week with 1.
    * Each later gameweek: unused transfers roll over and +1 is added, capped
      at ``max_ft``. Hits leave you with 0 before the +1.
    * Wildcard / Free Hit weeks don't use banked transfers.

    One-off league-wide top-ups announced by FPL cannot be seen in the API;
    use the CLI ``--free-transfers`` override if FPL grants one.
    """
    events = sorted(history_current, key=lambda e: e["event"])
    if not events:
        return 1
    chip_events = {c["event"] for c in chips if c.get("name") in TRANSFER_RESET_CHIPS}

    ft = 1
    for ev in events[1:]:
        if ev["event"] in chip_events:
            ft = min(max_ft, ft + 1)
            continue
        used = int(ev.get("event_transfers", 0) or 0)
        ft = min(max_ft, max(ft - used, 0) + 1)
    return ft


def purchase_prices(
    squad: list[int],
    transfers: list[dict],
    freehit_events: set[int],
    start_prices: dict[int, int],
    now_costs: dict[int, int],
) -> tuple[dict[int, int], list[int]]:
    """Return ``(player_id → purchase price, ids that fell back to now_cost)``.

    The most recent non-Free-Hit transfer-in sets the purchase price. Players
    never transferred in were in the original squad, so they were bought at
    their price in the manager's first gameweek (``start_prices``).
    """
    latest_in: dict[int, tuple[str, int]] = {}
    for t in transfers:
        if t.get("event") in freehit_events:
            continue
        pid = t["element_in"]
        when = t.get("time", "")
        if pid not in latest_in or when > latest_in[pid][0]:
            latest_in[pid] = (when, int(t["element_in_cost"]))

    prices: dict[int, int] = {}
    fallback: list[int] = []
    for pid in squad:
        if pid in latest_in:
            prices[pid] = latest_in[pid][1]
        elif pid in start_prices:
            prices[pid] = start_prices[pid]
        else:
            prices[pid] = now_costs.get(pid, 0)
            fallback.append(pid)
    return prices, fallback
