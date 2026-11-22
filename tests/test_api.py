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
