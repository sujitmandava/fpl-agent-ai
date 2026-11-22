"""HTTP API for the web app: the planning engine as JSON.

Run locally with ``python fpl_agent.py api`` (http://localhost:8000).

Stateless per request: a team's saved settings (locked/banned players, free
transfer and bank overrides) arrive as query parameters, so the web app can
keep them in the visitor's browser. Each team's synced data is cached in
memory for a few minutes, so changing options re-solves without calling FPL
again.
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
import time
from collections import OrderedDict
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from fpl_agent import engine
from fpl_agent.engine import POS, EngineError, Plan, PlanOptions, Setup

DB = os.environ.get("FPL_DB", "fpl_agent.db")
# The API never needs memory between requests; snapshots go to a scratch folder.
MEMORY_DIR = os.environ.get("FPL_API_MEMORY_DIR") or tempfile.mkdtemp(prefix="fpl-api-")
SETUP_TTL_SECONDS = 5 * 60
SETUP_CACHE_SIZE = 256
MODEL_CHECK_TTL_SECONDS = 6 * 3600

app = FastAPI(title="FPL Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("FPL_API_CORS", "http://localhost:3000").split(",") if o],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# -- Caches -------------------------------------------------------------------

_setups: OrderedDict[tuple[int, int | None], tuple[float, Setup]] = OrderedDict()
_setups_lock = threading.Lock()
_model_check: dict[int, tuple[float, dict]] = {}


def _setup(team_id: int, league_id: int | None, fresh: bool = False) -> Setup:
    key = (team_id, league_id)
    with _setups_lock:
        hit = _setups.get(key)
        if hit and not fresh and time.time() - hit[0] < SETUP_TTL_SECONDS:
            _setups.move_to_end(key)
            return hit[1]
    setup = engine.sync_setup(DB, engine.memory_path(MEMORY_DIR, team_id), team_id)
    if league_id and (setup.league is None or setup.league.league_id != league_id):
        engine.load_league(setup, league_id)
    with _setups_lock:
        _setups[key] = (time.time(), setup)
        _setups.move_to_end(key)
        while len(_setups) > SETUP_CACHE_SIZE:
            _setups.popitem(last=False)
    return setup


def _ids(text: str | None) -> frozenset[int] | None:
    if text is None:
        return None
    return frozenset(int(x) for x in text.split(",") if x.strip().isdigit())


def _num(v) -> float | None:
    """JSON-safe float (NaN → None), rounded for the wire."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, 3)


# -- Payload ------------------------------------------------------------------

def _fixture_counts(setup: Setup, gw: int) -> dict[int, int]:
    fx = setup.fixtures[setup.fixtures["event"] == gw]
    counts: dict[int, int] = {}
    for t in pd.concat([fx["team_h"], fx["team_a"]]).astype(int):
        counts[t] = counts.get(t, 0) + 1
    return counts


def _player_cards(plan: Plan, ids: set[int], gws: list[int], next_gw: int,
                  eo: dict[int, float], rival_squad: set[int]) -> dict[str, dict]:
    setup = plan.setup
    table = engine.player_table(setup, plan.forecast).set_index("id")
    opp = engine.next_opponents(setup.fixtures, setup.teams, next_gw)
    games = _fixture_counts(setup, next_gw)
    cards = {}
    for pid in sorted(ids):
        if pid not in table.index:
            continue
        r = table.loc[pid]
        team_id = int(r["team_id"])
        cards[str(pid)] = {
            "id": pid,
            "name": r["web_name"],
            "full_name": f"{r.get('first_name') or ''} {r.get('second_name') or ''}".strip(),
            "team": r["team"],
            "pos": r["pos"],
            "price": _num(r["price"]),
            "selling_price": _num(setup.state.selling_prices.get(pid, 0) / 10) if pid in setup.state.squad else None,
            "owned": bool(r["owned"]),
            "fixture": opp.get(team_id, "—"),
            "games_next": games.get(team_id, 0),
            "xmins": _num(r.get("exp_minutes")),
            "xg90": _num(r.get("xg90")),
            "xa90": _num(r.get("xa90")),
            "dc_rate": None if r["pos"] == "GK" else _num(r.get("dc_rate")),
            "cs_next": _num(r.get("cs_next")),
            "xpts_next": _num(r.get("expected_points_next")),
            "xpts_horizon": _num(r.get("total_expected_points")),
            "xpts_by_gw": {str(g): _num(r.get(f"expected_points_gw{g}")) for g in gws},
            "p_return_next": _num(r.get("p_return_next")),
            "returns": f"{int(r['returns'])}/{int(r['apps'])}" if _num(r.get("apps")) else None,
            "news": r.get("news") or "",
            "chance_next": _num(r.get("chance_of_playing_next_round")),
            "selected_by": _num(r.get("selected_by_percent")),
            "league_eo": _num(eo.get(pid, 0.0)),
            "rival_owns": pid in rival_squad,
        }
    return cards


def _formation(plan: Plan) -> str:
    pos = dict(zip(plan.setup.players["id"], plan.setup.players["element_type"]))
    n = [sum(1 for p in plan.rec.starting_xi if pos.get(p) == t) for t in (2, 3, 4)]
    return "-".join(str(x) for x in n)


def plan_payload(plan: Plan, rival_entry: int | None = None) -> dict:
    setup, rec, res = plan.setup, plan.rec, plan.result
    mem = setup.memory.data.get("manager", {})
    gw_cols = [c for c in plan.forecast.columns if c.startswith("expected_points_gw")]
    gws = [int(c.removeprefix("expected_points_gw")) for c in gw_cols]
    next_gw = rec.next_gw or setup.planning_gw
    fc = plan.forecast.set_index("player_id")

    league = setup.league
    eo: dict[int, float] = {}
    league_out = None
    rival = None
    if league is not None and league.mine is not None:
        from fpl_agent.league import head_to_head, league_ownership
        own = league_ownership(league)
        eo = own.set_index("player_id")["eo_pct"].to_dict() if not own.empty else {}
        others = [r for r in league.rivals if r.entry != league.me]
        rival = next((r for r in others if r.entry == rival_entry), None) or league.target
        me = league.mine
        h2h = None
        if rival is not None:
            h = head_to_head(league, rival.entry, plan.forecast, setup.players, setup.state.squad, gws)
            h2h = {
                "entry": rival.entry, "team_name": rival.team_name, "manager_name": rival.manager_name,
                "rank": rival.rank, "gap": me.total - rival.total,
                "edge_per_gw": _num(h.edge_per_gw), "weekly_sd": _num(h.weekly_sd),
                "p_ahead": _num(h.p_ahead), "remaining": h.remaining,
                "captain": rival.captain, "active_chip": rival.active_chip,
                "chips_now": rival.chips_now, "squad": rival.squad,
                "shared": h.shared, "mine_only": h.mine_only, "theirs_only": h.theirs_only,
                "by_gw": [{"gw": int(r.gw), "you": _num(r.you), "them": _num(r.them),
                           "edge": _num(r.edge), "your_captain": r.your_captain,
                           "their_captain": r.their_captain}
                          for r in h.by_gw.itertuples()],
            }
        league_out = {
            "id": league.league_id, "name": league.name, "gw": league.gw, "size": league.size,
            "partial": league.partial, "my_rank": me.rank, "my_total": me.total,
            "standings": [{"entry": r.entry, "team_name": r.team_name, "manager_name": r.manager_name,
                           "rank": r.rank, "total": r.total, "gw_points": r.gw_points,
                           "gap": me.total - r.total, "captain": r.captain,
                           "active_chip": r.active_chip, "chips_now": r.chips_now,
                           "is_me": r.entry == league.me}
                          for r in league.rivals],
            "rival": h2h,
        }

    rival_squad = set(rival.squad) if rival is not None else set()
    ids = set(setup.state.squad) | set(rec.starting_xi) | set(rec.bench) | rival_squad
    for t in rec.transfers:
        ids |= {t.sell_id, t.buy_id} | {a["id"] for a in t.alternatives}

    xi_points = {
        g: float(fc.get(f"expected_points_gw{g}", pd.Series(dtype=float))
                 .reindex(res.lineups.get(g, [])).fillna(0).sum()) + res.captain_points.get(g, 0)
        for g in res.gameweeks
    }
    return {
        "team": {"id": int(mem.get("id") or 0), "name": mem.get("team_name"),
                 "overall_rank": mem.get("overall_rank"), "overall_points": mem.get("overall_points")},
        "gameweek": {"planning": setup.planning_gw, "next": next_gw,
                     "deadline": setup.deadlines.get(setup.planning_gw), "horizon": gws},
        "budget": {"free_transfers": plan.team_state.free_transfers,
                   "free_transfers_source": plan.sources["free_transfers"],
                   "bank": plan.team_state.bank / 10, "bank_source": plan.sources["bank"]},
        "chips": [{"name": c["name"], "label": c["label"], "status": c["status"],
                   "window": c.get("window"), "event": c.get("event")} for c in setup.chips],
        "summary": {"next_gw_points": _num(rec.next_gw_points),
                    "delta_next": _num(rec.expected_points_delta),
                    "delta_horizon": _num(rec.horizon_delta), "hits": rec.transfer_cost},
        "moves": [{
            "out": t.sell_id, "in": t.buy_id, "position": t.position,
            "sell_price": _num(t.sell_price), "buy_price": _num(t.buy_price),
            "gain_next": _num(t.ep_gain_next), "gain_horizon": _num(t.ep_gain_horizon),
            "alternatives": [{"id": a["id"], "price": _num(a["price"]), "delta": _num(a["delta"])}
                             for a in t.alternatives],
        } for t in rec.transfers],
        "captain": rec.captain_id,
        "vice_captain": rec.vice_captain_id,
        "lineup": {"xi": rec.starting_xi, "bench": rec.bench_order, "formation": _formation(plan)},
        "chip_advice": plan.chip_advice,
        "plan_by_gw": [{"gw": g, "captain": res.captains.get(g), "xi_points": _num(xi_points[g]),
                        "bench_points": _num(res.bench_points.get(g, 0))} for g in res.gameweeks],
        "players": _player_cards(plan, ids, gws, next_gw, eo, rival_squad),
        "league": league_out,
        "leagues": setup.leagues,
        "notes": setup.notes + setup.state.notes,
        "synced": setup.synced,
        "rationale": rec.rationale,
    }


# -- Routes -------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/team/{team_id}/plan")
def team_plan(
    team_id: int,
    horizon: int = Query(6, ge=1, le=8),
    chip: Literal["none", "wildcard", "freehit"] = "none",
    free_transfers: int | None = Query(None, ge=0, le=5),
    bank: float | None = Query(None, ge=0, le=100),
    ft_value: float = Query(1.0, ge=0, le=3),
    bench_weight: float = Query(0.1, ge=0, le=0.5),
    consistency: float = Query(0.5, ge=0, le=2),
    league: int | None = None,
    rival: int | None = None,
    locked: str | None = Query(None, description="Comma-separated player ids"),
    banned: str | None = Query(None, description="Comma-separated player ids"),
    fresh: bool = False,
) -> dict:
    if team_id <= 0:
        raise HTTPException(400, "Team IDs are positive numbers.")
    try:
        setup = _setup(team_id, league, fresh)
        plan = engine.plan_from_setup(setup, PlanOptions(
            horizon=horizon, free_transfers=free_transfers, bank=bank,
            wildcard=chip == "wildcard", free_hit=chip == "freehit",
            bench_weight=bench_weight, ft_value=ft_value, consistency=consistency,
            locked=_ids(locked), banned=_ids(banned),
        ), record=False)
    except EngineError as exc:
        status = 404 if "No FPL team found" in str(exc) else 422
        raise HTTPException(status, str(exc)) from exc
    return plan_payload(plan, rival)


@app.get("/api/model-check")
def model_check(horizon: int = Query(3, ge=1, le=6)) -> dict:
    """Walk-forward backtest summary (cached for hours; same for every user)."""
    hit = _model_check.get(horizon)
    if hit and time.time() - hit[0] < MODEL_CHECK_TTL_SECONDS:
        return hit[1]
    from fpl_agent.data_ingest import FPLStore
    from fpl_agent.forecast.backtest import backtest_predictions, summarise, top_picks_avg

    store = FPLStore(db_path=DB)
    try:
        players, history, fixtures = store.players_df(), store.player_history_df(), store.fixtures_df()
        teams, scoring = store.teams_df(), store.scoring_rules()
    finally:
        store.close()
    done = fixtures[fixtures["finished"].fillna(0).astype(bool)]
    last_done = int(done["event"].max()) if not done.empty else 0
    cutoffs = [c for c in range(last_done - horizon - 3, last_done - horizon + 1) if c >= 3]
    if not cutoffs:
        raise HTTPException(422, "Not enough completed gameweeks yet.")
    d = backtest_predictions(players, history, fixtures, teams, scoring, cutoffs, horizon)
    m = summarise(d).set_index("model")
    out = {
        "horizon": horizon, "predictions": int(len(d)), "gameweeks": int(d["gw"].nunique()),
        "first_gw": int(d["gw"].min()), "last_gw": int(d["gw"].max()),
        "model_miss": _num(m.at["xpts", "mae"]), "baseline_miss": _num(m.at["ppg_baseline", "mae"]),
        "model_top20": _num(top_picks_avg(d, "xpts")),
        "baseline_top20": _num(top_picks_avg(d, "ppg_baseline")),
        "hindsight_top20": _num(top_picks_avg(d, "actual")),
        "average_player": _num(d["actual"].mean()), "bias": _num(m.at["xpts", "bias"]),
    }
    _model_check[horizon] = (time.time(), out)
    return out
