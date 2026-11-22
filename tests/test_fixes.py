"""Regression tests for the review fixes: season rollover, manager state,
blank/double gameweeks, lineup-aware optimisation, and the planner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from fpl_agent.data_ingest.api_client import FPLClient
from fpl_agent.data_ingest.manager import (
    compute_free_transfers,
    purchase_prices,
    selling_price,
)
from fpl_agent.data_ingest.models import SCHEMA_VERSION, get_meta, init_db
from fpl_agent.data_ingest.store import FPLStore, season_key
from fpl_agent.forecast.expected_points import ExpectedPointsModel
from fpl_agent.optimizer.milp import TeamState, optimize
from fpl_agent.planner.recommend import build_recommendation


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def _bootstrap(year: int, player_ids: list[int]) -> dict:
    return {
        "elements": [
            {"id": pid, "web_name": f"P{pid}", "team": 1, "element_type": 3,
             "now_cost": 50, "status": "a", "chance_of_playing_next_round": None,
             "form": "1", "points_per_game": "1", "ict_index": "1",
             "ep_this": "1", "ep_next": "1", "selected_by_percent": "1"}
            for pid in player_ids
        ],
        "teams": [{"id": 1, "name": "A", "short_name": "AAA"}],
        "events": [{"id": 1, "name": "GW1", "deadline_time": f"{year}-08-15T17:30:00Z",
                    "is_current": True, "is_next": False, "finished": False}],
    }


def _store(tmp_path, bootstrap: dict) -> FPLStore:
    client = MagicMock(spec=FPLClient)
    client.get_bootstrap.return_value = bootstrap
    client.get_fixtures.return_value = []
    return FPLStore(client=client, db_path=tmp_path / "t.db")


def test_season_key():
    assert season_key([{"deadline_time": "2026-08-15T17:30:00Z"}]) == "2026/27"


def test_new_season_wipes_old_data(tmp_path):
    store = _store(tmp_path, _bootstrap(2025, [1, 2, 3]))
    store.refresh_bootstrap()
    store.conn.execute("INSERT INTO your_team (player_id, position) VALUES (3, 1)")
    store.conn.commit()

    store.client.get_bootstrap.return_value = _bootstrap(2026, [1, 2])
    store.refresh_bootstrap()

    assert sorted(store.players_df()["id"]) == [1, 2]
    assert store.your_team_df().empty
    assert get_meta(store.conn, "season") == "2026/27"


def test_players_removed_from_game_are_deleted(tmp_path):
    store = _store(tmp_path, _bootstrap(2026, [1, 2, 3]))
    store.refresh_bootstrap()
    store.client.get_bootstrap.return_value = _bootstrap(2026, [1, 2])
    store.refresh_bootstrap()
    assert sorted(store.players_df()["id"]) == [1, 2]


def test_old_schema_is_rebuilt(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, web_name TEXT)")
    conn.execute("INSERT INTO players VALUES (411, 'Last season')")
    conn.commit()
    conn.close()

    conn = init_db(path)
    assert get_meta(conn, "schema_version") == SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0


def test_double_gameweek_history_keeps_both_matches(tmp_path):
    store = _store(tmp_path, _bootstrap(2026, [1]))
    store._store_history([
        {"element": 1, "fixture": 10, "round": 5, "total_points": 2, "value": 50},
        {"element": 1, "fixture": 11, "round": 5, "total_points": 9, "value": 50},
    ])
    assert len(store.player_history_df(1)) == 2


# ---------------------------------------------------------------------------
# Manager state
# ---------------------------------------------------------------------------

def test_selling_price_rule():
    assert selling_price(100, 103) == 101   # keep half the rise, rounded down
    assert selling_price(100, 104) == 102
    assert selling_price(100, 97) == 97     # falls passed on in full


def _ev(gw, transfers=0):
    return {"event": gw, "event_transfers": transfers}


def test_free_transfers_bank_and_cap():
    history = [_ev(g) for g in range(1, 12)]
    assert compute_free_transfers(history, []) == 5


def test_free_transfers_after_use_and_hits():
    history = [_ev(1), _ev(2), _ev(3), _ev(4, 3)]     # 3 banked, used 3 → 0, +1
    assert compute_free_transfers(history, []) == 1
    history = [_ev(1), _ev(2, 3)]                     # hit week → 0, +1
    assert compute_free_transfers(history, []) == 1


def test_free_transfers_kept_through_wildcard():
    history = [_ev(1), _ev(2), _ev(3, 12), _ev(4)]
    chips = [{"name": "wildcard", "event": 3}]
    assert compute_free_transfers(history, chips) == 4


def test_purchase_prices_ignore_free_hit_and_use_latest():
    transfers = [
        {"element_in": 7, "element_in_cost": 60, "event": 3, "time": "2026-09-01"},
        {"element_in": 7, "element_in_cost": 65, "event": 6, "time": "2026-10-01"},
        {"element_in": 8, "element_in_cost": 90, "event": 9, "time": "2026-11-01"},  # free hit
    ]
    prices, fallback = purchase_prices(
        [7, 8, 9], transfers, freehit_events={9},
        start_prices={8: 80}, now_costs={7: 70, 8: 85, 9: 45},
    )
    assert prices == {7: 65, 8: 80, 9: 45}
    assert fallback == [9]


# ---------------------------------------------------------------------------
# Forecast (see also tests/test_xpts.py)
# ---------------------------------------------------------------------------

from tests.test_xpts import build_world  # noqa: E402


def test_blank_gameweek_scores_zero_and_double_scores_twice():
    players, history, fixtures, teams = build_world()
    future = [
        {"id": 900, "event": 9, "team_h": 10, "team_a": 20},
        # GW10: team 10 blanks
        {"id": 901, "event": 11, "team_h": 10, "team_a": 20},
        {"id": 902, "event": 11, "team_h": 30, "team_a": 10},
    ]
    fixtures = pd.concat([fixtures, pd.DataFrame(future)], ignore_index=True)
    fc = ExpectedPointsModel(players, history, fixtures, teams, 8, 3).predict().set_index("player_id")
    assert fc.loc[1, "expected_points_gw9"] > 0
    assert fc.loc[1, "expected_points_gw10"] == 0.0
    assert fc.loc[1, "expected_points_gw11"] > 1.6 * fc.loc[1, "expected_points_gw9"]


def test_unplayed_matches_excluded_from_form():
    players, history, fixtures, teams = build_world()
    # Pretend GW8 hasn't been played yet: its rows must be ignored.
    fx = fixtures.copy()
    fx.loc[fx["event"] == 8, ["finished", "finished_provisional"]] = 0
    model = ExpectedPointsModel(players, history, fx, teams, 8, 1)
    assert 8 not in set(model.history["gameweek"])


def test_injury_penalty_fades_and_departed_players_zero():
    players, history, fixtures, teams = build_world()
    players = players.copy()
    players.loc[players["id"] == 1, ["status", "chance_of_playing_next_round"]] = ["i", 0]
    players.loc[players["id"] == 2, "status"] = "u"
    future = [{"id": 950 + g, "event": g, "team_h": 10, "team_a": 20} for g in range(9, 14)]
    fixtures = pd.concat([fixtures, pd.DataFrame(future)], ignore_index=True)
    fc = ExpectedPointsModel(players, history, fixtures, teams, 8, 5).predict().set_index("player_id")
    assert fc.loc[1, "expected_points_gw9"] == 0
    assert 0 < fc.loc[1, "expected_points_gw10"] < fc.loc[1, "expected_points_gw13"]
    assert fc.loc[2, "total_expected_points"] == 0


# ---------------------------------------------------------------------------
# Optimizer + planner
# ---------------------------------------------------------------------------

def _pool():
    """Current squad (ids 1-15) plus one premium forward and one cheap keeper."""
    rows, eps = [], {}
    layout = [1] * 2 + [2] * 5 + [3] * 5 + [4] * 3
    for i, pos in enumerate(layout, start=1):
        rows.append({"id": i, "web_name": f"P{i}", "element_type": pos, "team_id": i, "now_cost": 50})
        eps[i] = 4.0
    rows.append({"id": 100, "web_name": "Premium", "element_type": 4, "team_id": 16, "now_cost": 120})
    eps[100] = 10.0
    rows.append({"id": 101, "web_name": "BackupGK", "element_type": 1, "team_id": 17, "now_cost": 40})
    eps[101] = 4.5
    players = pd.DataFrame(rows)
    forecast = pd.DataFrame({
        "player_id": list(eps),
        "expected_points_gw12": list(eps.values()),
        "expected_points_gw13": list(eps.values()),
    })
    forecast["expected_points_next"] = forecast["expected_points_gw12"]
    forecast["total_expected_points"] = forecast[["expected_points_gw12", "expected_points_gw13"]].sum(axis=1)
    state = TeamState(list(range(1, 16)), {i: 50 for i in range(1, 16)}, bank=100, free_transfers=1)
    return players, forecast, state


def test_optimizer_buys_premium_and_captains_him():
    players, forecast, state = _pool()
    res = optimize(state, forecast, players)
    assert 100 in res.selected_ids
    assert res.captain_id == 100
    assert len(res.starting_xi) == 11
    assert res.transfer_cost == 0


def test_optimizer_skips_marginal_bench_upgrade():
    """A slightly better backup keeper isn't worth a transfer (bench barely counts)."""
    players, forecast, state = _pool()
    forecast = forecast[forecast["player_id"] != 100].copy()
    gw_cols = ["expected_points_gw12", "expected_points_gw13", "expected_points_next"]
    forecast.loc[forecast["player_id"] == 1, gw_cols] = 6.0   # clear first-choice GK
    res = optimize(state, forecast, players)
    assert res.transfers_in == []


def test_baseline_zero_transfers_and_budget_uses_selling_price():
    players, forecast, state = _pool()
    # Squad member 15 is worth 50 now but only sells for 45; bank 0.
    state = TeamState(state.current_squad, {**state.selling_prices, 15: 45}, bank=0, free_transfers=1)
    base = optimize(state, forecast, players, max_transfers=0)
    assert sorted(base.selected_ids) == list(range(1, 16))
    res = optimize(state, forecast, players)
    assert 100 not in res.selected_ids   # 45 + 0 bank can't fund a 120 player


def test_wildcard_allows_many_transfers_without_hits():
    players, forecast, state = _pool()
    res = optimize(state, forecast, players, unlimited_transfers=True)
    assert res.transfer_cost == 0


def test_planner_uses_solver_lineup_and_bench_gk_first():
    players, forecast, state = _pool()
    res = optimize(state, forecast, players)
    base = optimize(state, forecast, players, max_transfers=0)
    rec = build_recommendation(res, players, forecast, state.current_squad, state.selling_prices,
                               baseline=base)
    pos = dict(zip(players["id"], players["element_type"]))
    assert rec.captain_id == 100
    assert pos[rec.bench_order[0]] == 1
    assert len(rec.bench_order) == 4
    assert rec.expected_points_delta > 0
    assert "Premium" in rec.rationale
