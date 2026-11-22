"""Mini-league awareness: standings, rivals' squads, captains and chips.

    snap = fetch_league(client, league_id, gw, me=manager_id, chip_defs=defs)
    own = league_ownership(snap)                       # who owns what in the league
    h2h = head_to_head(snap, rival_entry, forecast, my_squad, gws)

Rivals' picks for a gameweek only become public after its deadline, so
everything here is based on their squads for the gameweek just locked
(``gw``). Forward-looking comparisons assume both squads are held: it shows
where the gap comes from, not what rivals will do next.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from fpl_agent.data_ingest.manager import chip_status
from fpl_agent.planner.recommend import best_xi

DEFAULT_WEEKLY_SD = 12.0      # used when there are too few shared gameweeks
SEASON_GWS = 38


@dataclass
class Rival:
    entry: int
    team_name: str
    manager_name: str
    rank: int
    total: int
    gw_points: int
    squad: list[int] = field(default_factory=list)
    multipliers: dict[int, int] = field(default_factory=dict)   # player → 0 bench, 1, 2 C, 3 TC
    captain: int | None = None
    vice: int | None = None
    active_chip: str | None = None
    chips: list[dict] = field(default_factory=list)              # chip_status() rows
    bank: int = 0
    value: int = 0
    weekly: dict[int, int] = field(default_factory=dict)         # GW → points after hits

    @property
    def chips_now(self) -> list[str]:
        """Chips usable in the current window."""
        return [c["label"] for c in self.chips if c["status"] == "available"]

    @property
    def chips_later(self) -> list[str]:
        """Chips for a later window (e.g. GW20–38)."""
        return [c["label"] for c in self.chips if c["status"] == "upcoming"]


@dataclass
class LeagueSnapshot:
    league_id: int
    name: str
    gw: int                       # gameweek whose picks are shown
    me: int
    rivals: list[Rival]           # top of the table (including me), by rank
    size: int                     # managers in the league (lower bound if paged)
    partial: bool = False         # True when only the top of a large league was loaded

    def get(self, entry: int) -> Rival | None:
        return next((r for r in self.rivals if r.entry == entry), None)

    @property
    def mine(self) -> Rival | None:
        return self.get(self.me)

    @property
    def target(self) -> Rival | None:
        """The leader, or the closest chaser when you lead."""
        others = [r for r in self.rivals if r.entry != self.me]
        return min(others, key=lambda r: r.rank) if others else None


def fetch_league(client, league_id: int, gw: int, me: int, chip_defs: list[dict],
                 max_rivals: int = 10) -> LeagueSnapshot:
    """Standings plus the top *max_rivals* managers' picks and history.

    You are always included, even if you're below the cut.
    """
    data = client.get_league_standings(league_id)
    results = data["standings"]["results"]
    top = results[:max_rivals]
    if me not in {r["entry"] for r in top}:
        top += [r for r in results if r["entry"] == me]
    rivals = []
    for r in top:
        rv = Rival(entry=int(r["entry"]), team_name=r["entry_name"], manager_name=r["player_name"],
                   rank=int(r["rank"]), total=int(r["total"]), gw_points=int(r["event_total"]))
        if gw >= 1:
            picks = client.get_manager_picks(rv.entry, gw)
            rv.squad = [int(p["element"]) for p in picks["picks"]]
            rv.multipliers = {int(p["element"]): int(p["multiplier"]) for p in picks["picks"]}
            rv.captain = next((int(p["element"]) for p in picks["picks"] if p["is_captain"]), None)
            rv.vice = next((int(p["element"]) for p in picks["picks"] if p["is_vice_captain"]), None)
            rv.active_chip = picks.get("active_chip")
            eh = picks.get("entry_history") or {}
            rv.bank, rv.value = int(eh.get("bank") or 0), int(eh.get("value") or 0)
        hist = client.get_manager_history(rv.entry)
        rv.weekly = {int(h["event"]): int(h["points"]) - int(h.get("event_transfers_cost") or 0)
                     for h in hist.get("current", [])}
        played = [{"name": c["name"], "event": int(c["event"])} for c in hist.get("chips", [])]
        rv.chips = chip_status(chip_defs, played, gw + 1)
        rivals.append(rv)
    rivals.sort(key=lambda r: r.rank)
    league = data.get("league", {})
    has_next = bool(data["standings"].get("has_next"))
    return LeagueSnapshot(league_id=league_id, name=league.get("name", str(league_id)), gw=gw,
                          me=me, rivals=rivals, size=len(results), partial=has_next or len(results) > len(top))


def league_ownership(snap: LeagueSnapshot, exclude_me: bool = True) -> pd.DataFrame:
    """Per player among the loaded rivals: owners, own %, effective ownership %, captains.

    Effective ownership (EO) counts the captain twice (three times for a
    Triple Captain) and benched players zero: it is the share of the
    league's points that player hands out. A player you own at 100% with a
    league EO of 30% gains you 0.7× his points on the average rival.
    """
    pool = [r for r in snap.rivals if not (exclude_me and r.entry == snap.me) and r.squad]
    n = len(pool)
    rows: dict[int, dict] = {}
    for r in pool:
        for pid in r.squad:
            row = rows.setdefault(pid, {"player_id": pid, "owners": 0, "eo": 0.0, "captains": 0})
            row["owners"] += 1
            row["eo"] += r.multipliers.get(pid, 1)
            row["captains"] += int(pid == r.captain)
    df = pd.DataFrame(rows.values(), columns=["player_id", "owners", "eo", "captains"])
    if n:
        df["own_pct"] = 100 * df["owners"] / n
        df["eo_pct"] = 100 * df["eo"] / n
    else:
        df["own_pct"] = df["eo_pct"] = 0.0
    df.attrs["n"] = n
    return df.drop(columns="eo").sort_values(["eo_pct", "owners"], ascending=False).reset_index(drop=True)


def _held_points(squad: list[int], positions: dict[int, int], xpts: dict[int, float]) -> tuple[float, int | None]:
    """XI + captain xPts for a held squad in one gameweek (captain = best in XI)."""
    if not squad:
        return 0.0, None
    xi = best_xi(squad, positions, xpts)
    cap = max(xi, key=lambda p: xpts.get(p, 0.0)) if xi else None
    return sum(xpts.get(p, 0.0) for p in xi) + (xpts.get(cap, 0.0) if cap else 0.0), cap


@dataclass
class HeadToHead:
    rival: Rival
    gap: int                      # rival total − your total (positive = you trail)
    shared: list[int]
    mine_only: list[int]
    theirs_only: list[int]
    by_gw: pd.DataFrame           # gw, you, them, edge, your_captain, their_captain
    edge_per_gw: float            # your expected edge per GW over the horizon
    weekly_sd: float              # spread of the weekly points difference so far
    remaining: int                # gameweeks left after the current one
    p_ahead: float                # rough chance of finishing above this rival


def head_to_head(snap: LeagueSnapshot, rival_entry: int, forecast: pd.DataFrame,
                 players: pd.DataFrame, my_squad: list[int], gws: list[int]) -> HeadToHead:
    """Compare your held squad with a rival's over the forecast horizon.

    ``p_ahead`` is a normal approximation: the current gap, plus the expected
    edge over the horizon only (beyond it both sides are treated as equal),
    against the season's observed week-to-week spread of your score
    difference. Treat it as a rough guide, not a forecast.
    """
    rival, me = snap.get(rival_entry), snap.mine
    if rival is None or me is None:
        raise ValueError("Rival or you not in the loaded league snapshot.")
    positions = dict(zip(players["id"].astype(int), players["element_type"].astype(int)))
    fc = forecast.set_index("player_id")
    mine, theirs = set(my_squad), set(rival.squad)

    rows = []
    for gw in gws:
        col = f"expected_points_gw{gw}"
        xp = fc[col].to_dict() if col in fc.columns else {}
        you, your_c = _held_points(list(my_squad), positions, xp)
        them, their_c = _held_points(rival.squad, positions, xp)
        rows.append({"gw": gw, "you": round(you, 2), "them": round(them, 2), "edge": round(you - them, 2),
                     "your_captain": your_c, "their_captain": their_c})
    by_gw = pd.DataFrame(rows)
    edge = float(by_gw["edge"].mean()) if not by_gw.empty else 0.0

    common = sorted(set(me.weekly) & set(rival.weekly))
    diffs = [me.weekly[g] - rival.weekly[g] for g in common]
    if len(diffs) >= 3:
        mean = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1))
    else:
        sd = DEFAULT_WEEKLY_SD
    remaining = max(SEASON_GWS - snap.gw, 0)
    gap = rival.total - me.total
    if remaining:
        z = (edge * min(len(gws), remaining) - gap) / (sd * math.sqrt(remaining))
        p = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    else:
        p = 1.0 if gap < 0 else 0.0
    return HeadToHead(rival=rival, gap=gap, shared=sorted(mine & theirs),
                      mine_only=sorted(mine - theirs), theirs_only=sorted(theirs - mine),
                      by_gw=by_gw, edge_per_gw=round(edge, 2), weekly_sd=round(sd, 1),
                      remaining=remaining, p_ahead=p)
