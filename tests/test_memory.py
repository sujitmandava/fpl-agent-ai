"""Tests for agent memory, chip tracking, and memory-aware planning."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
from click.testing import CliRunner

from fpl_agent.data_ingest.manager import ManagerState, chip_status
from fpl_agent.memory import AgentMemory
from fpl_agent.optimizer.milp import OptimizationResult, TeamState, optimize
from fpl_agent.planner.chips import chip_outlook, fixture_calendar

CHIP_DEFS = [
    {"name": n, "number": 1, "start_event": s, "stop_event": e}
    for n in ("wildcard", "freehit", "bboost", "3xc") for s, e in ((2, 19), (20, 38))
]
PLAYERS = pd.DataFrame([
    {"id": i, "web_name": f"P{i}", "element_type": 3, "team_id": 1, "now_cost": 50}
    for i in range(1, 16)
])
TEAMS = pd.DataFrame([{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"},
                      {"id": 3, "short_name": "CCC"}])


def _state(**kw) -> ManagerState:
    base = dict(squad=list(range(1, 16)), selling_prices={i: 50 for i in range(1, 16)},
                bank=12, free_transfers=2, source="public",
                purchase_prices={i: 48 for i in range(1, 16)},
                entry={"name": "My XI", "summary_overall_rank": 1000,
                       "leagues": {"classic": [{"id": 7, "name": "Mates", "entry_rank": 3,
                                                "league_type": "x"},
                                               {"id": 1, "name": "Overall", "entry_rank": 9,
                                                "league_type": "s"}]}})
    base.update(kw)
    return ManagerState(**base)


# -- Chips --------------------------------------------------------------------

def test_chip_status_per_window():
    played = [{"name": "wildcard", "event": 9}, {"name": "3xc", "event": 7}]
    st = {(c["name"], c["window"][0]): c["status"] for c in chip_status(CHIP_DEFS, played, 12)}
    assert st[("wildcard", 2)] == "played"
    assert st[("freehit", 2)] == "available"
    assert st[("wildcard", 20)] == "upcoming"
    later = {(c["name"], c["window"][0]): c["status"] for c in chip_status(CHIP_DEFS, played, 21)}
    assert later[("freehit", 2)] == "expired"
    assert later[("wildcard", 20)] == "available"


def test_chip_outlook_picks_best_gameweeks_and_warns_expiry():
    plan = OptimizationResult(
        selected_ids=[], transfers_in=[], transfers_out=[], total_expected_points=0,
        transfer_cost=0, solver_status="Optimal", gameweeks=[17, 18, 19, 20],
        bench_points={17: 8.0, 18: 15.0, 19: 9.0, 20: 30.0},
        captain_points={17: 6.0, 18: 7.0, 19: 12.0, 20: 20.0},
        captains={17: 1, 18: 1, 19: 2, 20: 2},
    )
    chips = chip_status(CHIP_DEFS, [], 17)
    fixtures = pd.DataFrame([{"event": 18, "team_h": 1, "team_a": 2},
                             {"event": 18, "team_h": 1, "team_a": 3}])
    lines = chip_outlook(plan, chips, fixture_calendar(fixtures, TEAMS, [17, 18, 19, 20]),
                         names={1: "Salah", 2: "Haaland"})
    text = "\n".join(lines)
    assert "Bench Boost (expires after GW19): best in GW18" in text   # GW20 is outside window
    assert "Triple Captain (expires after GW19): best in GW19 on Haaland" in text
    assert "double for AAA" in text and "blank for" in text
    assert "must be used by GW19" in text


# -- Memory -------------------------------------------------------------------

def test_memory_round_trip_and_snapshot(tmp_path):
    path = tmp_path / "mem.json"
    mem = AgentMemory(path)
    chips = chip_status(CHIP_DEFS, [{"name": "bboost", "event": 11}], 12)
    mem.record_sync(42, _state(), 12, "2026/27", PLAYERS, TEAMS, chips)
    mem.lock(3, "P3")
    mem.add_note("Saving Free Hit")
    mem.save()

    data = json.loads(path.read_text())
    assert data["manager"]["team_name"] == "My XI"
    assert data["manager"]["leagues"] == [{"id": 7, "name": "Mates", "rank": 3}]
    assert data["squad"][0]["purchase_price"] == 48
    assert data["free_transfers"] == 2 and data["bank"] == 12

    again = AgentMemory(path)
    assert again.locked_ids == {3}
    state = again.to_manager_state()
    assert state.source == "memory"
    assert state.squad == list(range(1, 16)) and state.bank == 12
    assert {"name": "bboost", "event": 11} in state.chips_played


def test_overrides_expire_after_deadline(tmp_path):
    mem = AgentMemory(tmp_path / "m.json")
    mem.set_override("free_transfers", 1, gw=12)
    assert mem.active_overrides(12) == {"free_transfers": 1}
    mem.record_sync(42, _state(), 13, "2026/27", PLAYERS, TEAMS, [])
    assert mem.active_overrides(13) == {}


def test_new_season_resets_snapshot_but_keeps_notes(tmp_path):
    mem = AgentMemory(tmp_path / "m.json")
    mem.record_sync(42, _state(), 12, "2026/27", PLAYERS, TEAMS, [])
    mem.lock(1, "P1")
    mem.add_note("Long-term plan")
    mem.record_sync(42, _state(), 2, "2027/28", PLAYERS, TEAMS, [])
    assert mem.locked_ids == set()
    assert [n["text"] for n in mem.data["notes"]] == ["Long-term plan"]


def test_lock_and_ban_are_exclusive(tmp_path):
    mem = AgentMemory(tmp_path / "m.json")
    mem.lock(5, "P5")
    mem.ban(5, "P5")
    assert mem.locked_ids == set() and mem.banned_ids == {5}
    assert mem.unlock(5) and not mem.unlock(5)


# -- Optimizer preferences ----------------------------------------------------

def _pool():
    rows, ep = [], {}
    layout = [1] * 2 + [2] * 5 + [3] * 5 + [4] * 3
    for i, pos in enumerate(layout, start=1):
        rows.append({"id": i, "web_name": f"P{i}", "element_type": pos, "team_id": i, "now_cost": 50})
        ep[i] = 4.0
    rows += [{"id": 100, "web_name": "Star", "element_type": 4, "team_id": 16, "now_cost": 50},
             {"id": 101, "web_name": "Alt", "element_type": 4, "team_id": 17, "now_cost": 50}]
    ep.update({100: 9.0, 101: 8.0})
    fc = pd.DataFrame({"player_id": list(ep), "expected_points_gw12": list(ep.values())})
    fc["total_expected_points"] = fc["expected_points_gw12"]
    state = TeamState(list(range(1, 16)), {i: 50 for i in range(1, 16)}, bank=0, free_transfers=1)
    return pd.DataFrame(rows), fc, state


def test_banned_player_is_never_bought():
    players, fc, state = _pool()
    assert optimize(state, fc, players).transfers_in == [100]
    assert optimize(state, fc, players, banned={100}).transfers_in == [101]


def test_locked_player_is_kept():
    players, fc, state = _pool()
    res = optimize(state, fc, players, locked={13})   # 13 is a FWD that would be sold
    assert 13 in res.selected_ids


# -- CLI ----------------------------------------------------------------------

def test_cli_memory_commands(tmp_path, monkeypatch):
    from fpl_agent.cli.main import cli
    from fpl_agent.data_ingest.store import FPLStore

    db, mem_dir = tmp_path / "t.db", tmp_path / "memory"
    mem_path = mem_dir / "42.json"
    store = FPLStore(client=MagicMock(), db_path=db)
    store._upsert(pd.DataFrame([
        {"id": 1, "web_name": "Ødegaard", "first_name": "Martin", "second_name": "Ødegaard",
         "team_id": 1, "element_type": 3, "now_cost": 67},
        {"id": 2, "web_name": "Haaland", "first_name": "Erling", "second_name": "Haaland",
         "team_id": 1, "element_type": 4, "now_cost": 150},
    ]), "players")
    store._upsert(pd.DataFrame([{"id": 1, "name": "A", "short_name": "AAA"}]), "teams")
    store.close()

    monkeypatch.delenv("FPL_MANAGER_ID", raising=False)
    run = lambda *a: CliRunner().invoke(cli, ["--db", str(db), "--memory-dir", str(mem_dir), *a])  # noqa: E731
    assert run("memory", "-m", "42", "lock", "odegaard").exit_code == 0   # accent-insensitive
    assert run("memory", "-m", "42", "ban", "2").exit_code == 0           # by id
    assert run("memory", "-m", "42", "set-ft", "3").exit_code == 0
    assert run("memory", "-m", "42", "note", "Free Hit in the blank").exit_code == 0
    bad = run("memory", "-m", "42", "lock", "nobody")
    assert bad.exit_code != 0 and "No player matches" in bad.output
    no_id = run("memory", "lock", "odegaard")                             # no default team
    assert no_id.exit_code != 0 and "manager-id" in no_id.output
    assert not (mem_dir / "43.json").exists()

    data = json.loads(mem_path.read_text())
    assert [p["name"] for p in data["locked"]] == ["Ødegaard"]
    assert [p["name"] for p in data["banned"]] == ["Haaland"]
    assert data["overrides"]["free_transfers"]["value"] == 3
    assert data["notes"][0]["text"] == "Free Hit in the blank"


def test_sync_falls_back_to_memory_when_api_down(tmp_path, monkeypatch):
    from fpl_agent import engine as cli_main
    from fpl_agent.data_ingest.store import FPLStore

    db, mem_path = tmp_path / "t.db", tmp_path / "mem.json"
    store = FPLStore(client=MagicMock(), db_path=db)
    store._upsert(PLAYERS.assign(web_name=PLAYERS["web_name"]), "players")
    store._upsert(TEAMS.assign(name="x"), "teams")
    store.close()
    mem = AgentMemory(mem_path)
    mem.record_sync(42, _state(), 12, "2026/27", PLAYERS, TEAMS, [])
    mem.save()

    down = MagicMock()
    down.return_value.get_bootstrap.side_effect = ConnectionError("down")
    down.return_value.get_manager_history.side_effect = ConnectionError("down")
    monkeypatch.setattr(cli_main, "FPLClient", down)

    setup = cli_main.sync_setup(str(db), str(mem_path), 42)
    assert setup.synced is False
    assert setup.state.source == "memory"
    assert setup.state.bank == 12
    assert any("unreachable" in n for n in setup.notes)


# -- Multi-user ---------------------------------------------------------------

def test_parse_manager_id_accepts_ids_and_links():
    from fpl_agent.engine import EngineError, parse_manager_id

    assert parse_manager_id("1234567") == 1234567
    assert parse_manager_id(" #42 ") == 42
    assert parse_manager_id("https://fantasy.premierleague.com/entry/7588/event/12") == 7588
    for bad in ("", "abc", "0", "12.5", "https://fantasy.premierleague.com/"):
        with pytest.raises(EngineError):
            parse_manager_id(bad)


def test_each_team_gets_its_own_memory_file(tmp_path):
    from fpl_agent.engine import memory_path

    assert memory_path(tmp_path, 1) != memory_path(tmp_path, 2)
    assert memory_path(tmp_path, 7) == tmp_path / "7.json"


def test_unknown_team_gives_a_clear_error(tmp_path, monkeypatch):
    import requests

    from fpl_agent import engine
    from fpl_agent.data_ingest.store import FPLStore

    db = tmp_path / "t.db"
    store = FPLStore(client=MagicMock(), db_path=db)
    store._upsert(PLAYERS.assign(web_name=PLAYERS["web_name"]), "players")
    store._upsert(TEAMS.assign(name="x"), "teams")
    store.close()

    resp = MagicMock(status_code=404)
    client = MagicMock()
    client.return_value.get_bootstrap.side_effect = ConnectionError("down")
    client.return_value.get_manager_history.side_effect = requests.HTTPError(response=resp)
    monkeypatch.setattr(engine, "FPLClient", client)

    with pytest.raises(engine.EngineError, match="No FPL team found with ID 99"):
        engine.sync_setup(str(db), tmp_path / "99.json", 99)
    assert not (tmp_path / "99.json").exists()
