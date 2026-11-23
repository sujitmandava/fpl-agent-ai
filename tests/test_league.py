"""Tests for the mini-league layer and close-call alternatives."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl_agent.league import fetch_league, head_to_head, league_ownership
from fpl_agent.planner.recommend import close_alternatives

CHIP_DEFS = [
    {"name": "wildcard", "number": 1, "start_event": 2, "stop_event": 19},
    {"name": "3xc", "number": 1, "start_event": 1, "stop_event": 19},
    {"name": "wildcard", "number": 1, "start_event": 20, "stop_event": 38},
]

# 15-man squads: ids 1-2 GK, 3-7 DEF, 8-12 MID, 13-15 FWD
BASE = list(range(1, 16))
POSITIONS = {i: 1 if i <= 2 else 2 if i <= 7 else 3 if i <= 12 else 4 for i in range(1, 20)}


class FakeClient:
    def __init__(self):
        self.squads = {
            100: BASE,                                   # me
            200: [i for i in BASE if i != 15] + [16],    # leader: FWD 16 instead of 15
            300: [i for i in BASE if i != 14] + [17],
        }
        self.captain = {100: 13, 200: 16, 300: 13}
        self.weekly = {100: [60, 50, 70, 40], 200: [70, 55, 60, 50], 300: [50, 50, 50, 50]}

    def get_league_standings(self, league_id, page=1):
        totals = {e: sum(w) for e, w in self.weekly.items()}
        order = sorted(totals, key=lambda e: -totals[e])
        return {"league": {"name": "Test League"},
                "standings": {"has_next": False, "results": [
                    {"entry": e, "entry_name": f"T{e}", "player_name": f"M{e}", "rank": i + 1,
                     "total": totals[e], "event_total": self.weekly[e][-1]} for i, e in enumerate(order)]}}

    def get_manager_picks(self, entry, gw):
        cap = self.captain[entry]
        return {"active_chip": "3xc" if entry == 300 else None,
                "entry_history": {"bank": 5, "value": 1000},
                "picks": [{"element": p, "multiplier": (3 if entry == 300 else 2) if p == cap else
                           (0 if i >= 11 else 1), "is_captain": p == cap, "is_vice_captain": False}
                          for i, p in enumerate(self.squads[entry])]}

    def get_manager_history(self, entry):
        return {"current": [{"event": g + 1, "points": p, "event_transfers_cost": 0}
                            for g, p in enumerate(self.weekly[entry])],
                "chips": [{"name": "wildcard", "event": 3}] if entry == 200 else []}


@pytest.fixture
def snap():
    return fetch_league(FakeClient(), 1, gw=4, me=100, chip_defs=CHIP_DEFS)


def test_fetch_league_standings_and_chips(snap):
    assert [r.entry for r in snap.rivals] == [200, 100, 300]
    assert snap.target.entry == 200
    leader = snap.get(200)
    assert leader.captain == 16 and leader.weekly[1] == 70
    assert "Wildcard" not in leader.chips_now and "Wildcard" in leader.chips_later
    assert "Wildcard" in snap.mine.chips_now


class BigLeagueClient(FakeClient):
    """A public league: you're far below its first page, and it started in GW3."""

    def get_league_standings(self, league_id, page=1):
        data = super().get_league_standings(league_id, page)
        data["league"]["start_event"] = 3
        data["standings"]["has_next"] = True
        data["standings"]["results"] = [r for r in data["standings"]["results"] if r["entry"] != 100]
        return data

    def get_entry(self, manager_id):
        return {"name": "T100", "player_first_name": "Me", "player_last_name": "Self",
                "leagues": {"classic": [{"id": 1, "entry_rank": 5000, "rank_count": 90000}]}}

    def get_manager_history(self, entry):
        hist = super().get_manager_history(entry)
        running = 0
        for h in hist["current"]:
            running += h["points"]
            h["total_points"] = running
        return hist


def test_big_league_adds_your_row_from_your_profile():
    snap = fetch_league(BigLeagueClient(), 1, gw=4, me=100, chip_defs=CHIP_DEFS)
    me = snap.mine
    assert me is not None and me.rank == 5000 and me.manager_name == "Me Self"
    assert me.total == 70 + 40                   # counted from GW3, when the league started
    assert set(me.weekly) == {3, 4} and set(snap.get(200).weekly) == {3, 4}
    assert snap.size == 90000 and snap.partial
    assert snap.target.entry == 200


def test_league_ownership_counts_captaincy(snap):
    raw = league_ownership(snap)
    assert raw.attrs["n"] == 2            # you are excluded
    own = raw.set_index("player_id")
    # Player 13: on the leader's bench (×0), triple-captained by 300 (×3) → EO 150% of 2 rivals.
    assert own.at[13, "owners"] == 2 and own.at[13, "eo_pct"] == pytest.approx(150.0)
    assert own.at[16, "captains"] == 1 and own.at[16, "eo_pct"] == pytest.approx(100.0)
    assert own.at[15, "owners"] == 1 and own.at[15, "own_pct"] == pytest.approx(50.0)


def test_head_to_head(snap):
    players = pd.DataFrame({"id": list(POSITIONS), "element_type": list(POSITIONS.values())})
    xp = {p: 2.0 for p in POSITIONS}
    xp[15], xp[16] = 6.0, 3.0            # my unique forward beats theirs
    forecast = pd.DataFrame({"player_id": list(xp), "expected_points_gw5": list(xp.values()),
                             "expected_points_gw6": list(xp.values())})
    h = head_to_head(snap, 200, forecast, players, BASE, [5, 6])
    assert h.mine_only == [15] and h.theirs_only == [16] and len(h.shared) == 14
    assert h.gap == 15
    # 15 captains for me (+6 twice) vs 16 for them (+3 twice): edge = 2*(6-3) = 6
    assert h.edge_per_gw == pytest.approx(6.0)
    assert 0 < h.p_ahead < 1
    assert h.remaining == 34


def test_close_alternatives_respects_margin_and_budget():
    name = {1: "Buy", 2: "Near", 3: "Far", 4: "Pricey", 5: "Owned", 6: "OtherPos"}
    pos = {1: 4, 2: 4, 3: 4, 4: 4, 5: 4, 6: 3}
    cost = {1: 60, 2: 55, 3: 50, 4: 80, 5: 60, 6: 60}
    ep = {1: 30.0, 2: 29.5, 3: 25.0, 4: 30.5, 5: 30.0, 6: 30.0}
    alts = close_alternatives(1, {1, 5}, name, pos, cost, ep, max_extra_cost=10)
    assert [a["name"] for a in alts] == ["Near"]
    alts = close_alternatives(1, {1, 5}, name, pos, cost, ep, max_extra_cost=20)
    assert [a["name"] for a in alts] == ["Pricey", "Near"]
