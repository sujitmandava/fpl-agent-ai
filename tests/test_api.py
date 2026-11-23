"""HTTP layer: routing, parameter parsing and error mapping (engine mocked)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fpl_agent import api
from fpl_agent.engine import EngineError


@pytest.fixture
def client():
    return TestClient(api.app)


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_ids_parsing():
    assert api._ids(None) is None
    assert api._ids("") == frozenset()
    assert api._ids("1, 2,x,3") == frozenset({1, 2, 3})


def test_unknown_team_is_404(client, monkeypatch):
    def boom(*a, **k):
        raise EngineError("No FPL team found with ID 5. Check the number in your Points page link.")
    monkeypatch.setattr(api, "_setup", boom)
    r = client.get("/api/team/5/plan")
    assert r.status_code == 404 and "No FPL team found" in r.json()["detail"]


def test_options_reach_the_engine(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "_setup", lambda team, league, fresh: object())

    def fake_plan(setup, opts, record):
        seen.update(opts=opts, record=record)
        raise EngineError("Your Wildcard isn't available for GW12.")
    monkeypatch.setattr(api.engine, "plan_from_setup", fake_plan)
    r = client.get("/api/team/5/plan?horizon=3&chip=wildcard&locked=1,2&banned=&bank=1.5")
    assert r.status_code == 422
    o = seen["opts"]
    assert (o.horizon, o.wildcard, o.free_hit, o.bank) == (3, True, False, 1.5)
    assert o.locked == frozenset({1, 2}) and o.banned == frozenset()
    assert seen["record"] is False


def test_bad_params_rejected(client):
    assert client.get("/api/team/5/plan?horizon=9").status_code == 422
    assert client.get("/api/team/5/plan?chip=bboost").status_code == 422


def test_league_payload_race_and_ownership():
    import pandas as pd
    from tests.test_league import BASE, CHIP_DEFS, POSITIONS, FakeClient
    from fpl_agent.league import fetch_league

    snap = fetch_league(FakeClient(), 1, gw=4, me=100, chip_defs=CHIP_DEFS)
    players = pd.DataFrame({"id": list(POSITIONS), "element_type": list(POSITIONS.values())})
    forecast = pd.DataFrame({"player_id": list(POSITIONS), "expected_points_gw5": [2.0] * len(POSITIONS)})
    out, eo, rival, ids = api.league_payload(snap, forecast, players, BASE, [5], rival_entry=300)

    assert rival.entry == 300 and out["rival"]["entry"] == 300
    # Weekly points line up by gameweek and add up to the standings gap.
    weekly = out["rival"]["weekly"]
    assert [w["gw"] for w in weekly] == [1, 2, 3, 4]
    assert sum(w["you"] - w["them"] for w in weekly) == out["rival"]["gap"] == 20
    # Ownership covers rivals only, and every captain and owned player gets a card.
    assert out["ownership"]["rivals"] == 2
    assert out["ownership"]["rows"][0] == {"id": 13, "owners": 2, "captains": 1, "eo": 150.0}
    assert {16, 17, 13} <= ids and eo[16] == 100.0
    assert out["loaded"] == 3 and [s["is_me"] for s in out["standings"]] == [False, True, False]


def test_warming_up_is_503_with_retry_after(client, monkeypatch):
    def warming(*a, **k):
        raise api.DataNotReady("The planner is loading this season's FPL data.")
    monkeypatch.setattr(api, "_setup", warming)
    r = client.get("/api/team/5/plan")
    assert r.status_code == 503 and r.headers["retry-after"] == "60"
    assert "loading" in r.json()["detail"]


def test_requests_never_refresh_shared_data(monkeypatch):
    seen = {}

    def fake_sync(db, mem, team_id, **kw):
        seen.update(kw)
        raise api.DataNotReady("loading")
    monkeypatch.setattr(api.engine, "sync_setup", fake_sync)
    api._setups.clear()
    with pytest.raises(api.DataNotReady):
        api._setup(5, None)
    assert seen == {"refresh_shared": False}


def test_sync_without_shared_data_is_not_ready(tmp_path):
    from fpl_agent import engine
    with pytest.raises(engine.DataNotReady):
        engine.sync_setup(str(tmp_path / "empty.db"), tmp_path / "1.json", 1, refresh_shared=False)


def test_refresh_loop_retries_after_failure(monkeypatch):
    import threading
    calls = []
    stop = threading.Event()

    def flaky(db):
        calls.append(db)
        if len(calls) == 1:
            raise RuntimeError("FPL down")
        stop.set()
    monkeypatch.setattr(api.engine, "refresh_shared_data", flaky)
    monkeypatch.setattr(api, "REFRESH_RETRY_SECONDS", 0)
    api._refresh_loop(stop)
    assert len(calls) == 2


def test_refresh_endpoint_needs_the_token(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api.engine, "refresh_shared_data", lambda db: calls.append(db))
    monkeypatch.delenv("FPL_REFRESH_TOKEN", raising=False)
    assert client.post("/api/refresh").status_code == 404          # off by default
    monkeypatch.setenv("FPL_REFRESH_TOKEN", "s3cret")
    assert client.post("/api/refresh").status_code == 401
    assert client.post("/api/refresh", headers={"X-Refresh-Token": "nope"}).status_code == 401
    assert client.get("/api/refresh").status_code == 405
    assert calls == []
    r = client.post("/api/refresh", headers={"X-Refresh-Token": "s3cret"})
    assert r.status_code == 200 and calls == [api.DB]


def test_refresh_endpoint_reports_fpl_failure(client, monkeypatch):
    def down(db):
        raise RuntimeError("FPL down")
    monkeypatch.setattr(api.engine, "refresh_shared_data", down)
    monkeypatch.setenv("FPL_REFRESH_TOKEN", "s3cret")
    assert client.post("/api/refresh", headers={"X-Refresh-Token": "s3cret"}).status_code == 502


def test_cold_start_loads_data_inline_without_background(monkeypatch):
    monkeypatch.setenv("FPL_BACKGROUND_REFRESH", "0")
    state = {"loaded": False, "refreshes": 0}

    def fake_sync(db, mem, team_id, **kw):
        if not state["loaded"]:
            raise api.DataNotReady("loading")
        return "setup"

    def fake_refresh(db):
        state["refreshes"] += 1
        state["loaded"] = True
    monkeypatch.setattr(api.engine, "sync_setup", fake_sync)
    monkeypatch.setattr(api.engine, "refresh_shared_data", fake_refresh)
    api._setups.clear()
    assert api._setup(7, None) == "setup" and state["refreshes"] == 1


def test_cold_start_with_fpl_down_is_503(client, monkeypatch):
    monkeypatch.setenv("FPL_BACKGROUND_REFRESH", "0")

    def not_ready(*a, **k):
        raise api.DataNotReady("loading")

    def down(db):
        raise RuntimeError("FPL down")
    monkeypatch.setattr(api.engine, "sync_setup", not_ready)
    monkeypatch.setattr(api.engine, "refresh_shared_data", down)
    api._setups.clear()
    r = client.get("/api/team/8/plan")
    assert r.status_code == 503 and "Couldn't reach FPL" in r.json()["detail"]
