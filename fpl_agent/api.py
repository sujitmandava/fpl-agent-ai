"""HTTP API for the web app: the planning engine as JSON.

Run locally with ``python fpl_agent.py api`` (http://localhost:8000).

Shared FPL data (players, fixtures, every player's match history) is kept
fresh by a background thread, so no request ever waits on that refresh. A
freshly started server answers 503 until the first refresh finishes.

On hosts that pause CPU between requests (Cloud Run), set
FPL_BACKGROUND_REFRESH=0: a request that finds no data loads it itself (a cold
start), and a scheduler keeps it fresh by calling ``POST /api/refresh`` with
the ``X-Refresh-Token`` header set to FPL_REFRESH_TOKEN.

Stateless per request: a team's saved settings (locked/banned players, free
transfer and bank overrides) arrive as query parameters, so the web app can
keep them in the visitor's browser. Each team's synced data is cached in
memory for a few minutes, so changing options re-solves without calling FPL
again.
"""

from __future__ import annotations

import hmac
import logging
import math
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Literal

import pandas as pd
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from fpl_agent import engine
from fpl_agent.engine import POS, DataNotReady, EngineError, Plan, PlanOptions, Setup

logger = logging.getLogger(__name__)

DB = os.environ.get("FPL_DB", "fpl_agent.db")
# The API never needs memory between requests; snapshots go to a scratch folder.
MEMORY_DIR = os.environ.get("FPL_API_MEMORY_DIR") or tempfile.mkdtemp(prefix="fpl-api-")
SETUP_TTL_SECONDS = 5 * 60
SETUP_CACHE_SIZE = 256
MODEL_CHECK_TTL_SECONDS = 6 * 3600
REFRESH_INTERVAL_SECONDS = 5 * 60
REFRESH_RETRY_SECONDS = 60


# -- Background refresh -------------------------------------------------------

def _refresh_loop(stop: threading.Event) -> None:
    """Keep shared data fresh: players/fixtures every few minutes, history every 6h."""
    while not stop.is_set():
        try:
            engine.refresh_shared_data(DB)
            wait = REFRESH_INTERVAL_SECONDS
        except Exception:
            logger.warning("Background FPL refresh failed; retrying soon.", exc_info=True)
            wait = REFRESH_RETRY_SECONDS
        stop.wait(wait)


def _background_refresh() -> bool:
    return os.environ.get("FPL_BACKGROUND_REFRESH", "1") != "0"


def _load_data_now() -> None:
    """Without the background thread, the first request after a cold start
    loads shared data itself. Concurrent callers wait on the same refresh."""
    try:
        engine.refresh_shared_data(DB)
    except Exception as exc:
        logger.warning("FPL refresh on request failed.", exc_info=True)
        raise DataNotReady("Couldn't reach FPL to load this season's data. "
                           "Try again in a minute.") from exc


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = threading.Event()
    if _background_refresh():
        threading.Thread(target=_refresh_loop, args=(stop,), name="fpl-refresh", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="FPL Agent API", version="0.1.0", lifespan=lifespan)
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
# Finished payloads keyed by team + every option, tied to the Setup they came from,
# so a reload or a repeat request is instant and a fresh sync invalidates them.
_plans: OrderedDict[tuple, tuple[Setup, dict]] = OrderedDict()
PLAN_CACHE_SIZE = 512


def _setup(team_id: int, league_id: int | None, fresh: bool = False) -> Setup:
    key = (team_id, league_id)
    with _setups_lock:
        hit = _setups.get(key)
        if hit and not fresh and time.time() - hit[0] < SETUP_TTL_SECONDS:
            _setups.move_to_end(key)
            return hit[1]
    mem = engine.memory_path(MEMORY_DIR, team_id)
    try:
        setup = engine.sync_setup(DB, mem, team_id, refresh_shared=False)
    except DataNotReady:
        if _background_refresh():
            raise
        _load_data_now()
        setup = engine.sync_setup(DB, mem, team_id, refresh_shared=False)
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


OWNERSHIP_ROWS = 20


def league_payload(league, forecast: pd.DataFrame, players: pd.DataFrame, my_squad: list[int],
                   gws: list[int], rival_entry: int | None = None):
    """The ``league`` block of the plan payload.

    Returns ``(payload, eo, rival, player_ids)``: league EO by player, the
    chosen rival (or None), and every player id the block refers to, so the
    caller can ship a card for each.
    """
    from fpl_agent.league import head_to_head, league_ownership

    me = league.mine
    own = league_ownership(league)
    eo = own.set_index("player_id")["eo_pct"].to_dict() if not own.empty else {}
    others = [r for r in league.rivals if r.entry != league.me]
    rival = next((r for r in others if r.entry == rival_entry), None) or league.target
    ids = {r.captain for r in league.rivals if r.captain is not None}
    top = own.head(OWNERSHIP_ROWS)
    ids |= set(top["player_id"].astype(int))

    h2h = None
    if rival is not None:
        h = head_to_head(league, rival.entry, forecast, players, my_squad, gws)
        ids |= set(rival.squad)
        h2h = {
            "entry": rival.entry, "team_name": rival.team_name, "manager_name": rival.manager_name,
            "rank": rival.rank, "gap": me.total - rival.total,
            "edge_per_gw": _num(h.edge_per_gw), "weekly_sd": _num(h.weekly_sd),
            "p_ahead": _num(h.p_ahead), "remaining": h.remaining,
            "captain": rival.captain, "active_chip": rival.active_chip,
            "chips_now": rival.chips_now, "chips_later": rival.chips_later, "squad": rival.squad,
            "shared": h.shared, "mine_only": h.mine_only, "theirs_only": h.theirs_only,
            # Points after hits in each gameweek both of you played, for the race line.
            "weekly": [{"gw": g, "you": me.weekly[g], "them": rival.weekly[g]}
                       for g in sorted(set(me.weekly) & set(rival.weekly))],
            "by_gw": [{"gw": int(r.gw), "you": _num(r.you), "them": _num(r.them),
                       "edge": _num(r.edge), "your_captain": r.your_captain,
                       "their_captain": r.their_captain}
                      for r in h.by_gw.itertuples()],
        }
    payload = {
        "id": league.league_id, "name": league.name, "gw": league.gw, "size": league.size,
        "partial": league.partial, "loaded": len(league.rivals),
        "my_rank": me.rank, "my_total": me.total,
        "standings": [{"entry": r.entry, "team_name": r.team_name, "manager_name": r.manager_name,
                       "rank": r.rank, "total": r.total, "gw_points": r.gw_points,
                       "gap": me.total - r.total, "captain": r.captain,
                       "active_chip": r.active_chip, "chips_now": r.chips_now,
                       "is_me": r.entry == league.me}
                      for r in league.rivals],
        "ownership": {
            "rivals": int(own.attrs.get("n", 0)),
            "rows": [{"id": int(r.player_id), "owners": int(r.owners), "captains": int(r.captains),
                      "eo": _num(r.eo_pct)} for r in top.itertuples()],
        },
        "rival": h2h,
    }
    return payload, eo, rival, ids


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
    league_ids: set[int] = set()
    if league is not None and league.mine is not None:
        league_out, eo, rival, league_ids = league_payload(
            league, plan.forecast, setup.players, setup.state.squad, gws, rival_entry)

    rival_squad = set(rival.squad) if rival is not None else set()
    ids = set(setup.state.squad) | set(rec.starting_xi) | set(rec.bench) | league_ids
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
        "chip_plan": [{"name": c.name, "label": c.label, "gw": c.gw, "gain": _num(c.gain),
                       "expires": c.expires, "on_wildcard_squad": c.on_wildcard_squad}
                      for c in plan.chip_plan],
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


@app.post("/api/refresh")
def refresh(x_refresh_token: str | None = Header(None)) -> dict:
    """Refresh shared FPL data now (for a scheduler). Off unless FPL_REFRESH_TOKEN is set."""
    expected = os.environ.get("FPL_REFRESH_TOKEN", "")
    if not expected:
        raise HTTPException(404, "Not found")
    if not x_refresh_token or not hmac.compare_digest(x_refresh_token, expected):
        raise HTTPException(401, "Bad refresh token")
    try:
        engine.refresh_shared_data(DB)
    except Exception as exc:
        logger.warning("Scheduled FPL refresh failed.", exc_info=True)
        raise HTTPException(502, f"FPL refresh failed: {exc.__class__.__name__}") from exc
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
    key = (team_id, horizon, chip, free_transfers, bank, ft_value, bench_weight, consistency,
           league, rival, _ids(locked), _ids(banned))
    try:
        setup = _setup(team_id, league, fresh)
        with _setups_lock:
            hit = _plans.get(key)
            if hit and hit[0] is setup:
                _plans.move_to_end(key)
                return hit[1]
        plan = engine.plan_from_setup(setup, PlanOptions(
            horizon=horizon, free_transfers=free_transfers, bank=bank,
            wildcard=chip == "wildcard", free_hit=chip == "freehit",
            bench_weight=bench_weight, ft_value=ft_value, consistency=consistency,
            locked=_ids(locked), banned=_ids(banned),
        ), record=False)
    except DataNotReady as exc:
        return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": "60"})
    except EngineError as exc:
        status = 404 if "No FPL team found" in str(exc) else 422
        raise HTTPException(status, str(exc)) from exc
    payload = plan_payload(plan, rival)
    with _setups_lock:
        _plans[key] = (setup, payload)
        _plans.move_to_end(key)
        while len(_plans) > PLAN_CACHE_SIZE:
            _plans.popitem(last=False)
    return payload


@app.get("/api/model-check")
def model_check(horizon: int = Query(3, ge=1, le=6)) -> dict:
    """Walk-forward backtest summary (cached for hours; same for every user)."""
    hit = _model_check.get(horizon)
    if hit and time.time() - hit[0] < MODEL_CHECK_TTL_SECONDS:
        return hit[1]
    from fpl_agent.data_ingest import FPLStore
    from fpl_agent.forecast.backtest import backtest_predictions, summarise, top_picks_avg

    def load():
        store = FPLStore(db_path=DB)
        try:
            return (store.players_df(), store.player_history_df(), store.fixtures_df(),
                    store.teams_df(), store.scoring_rules())
        finally:
            store.close()

    players, history, fixtures, teams, scoring = load()
    if (players.empty or history.empty) and not _background_refresh():
        try:
            _load_data_now()
        except DataNotReady:
            pass
        else:
            players, history, fixtures, teams, scoring = load()
    if players.empty or history.empty:
        return JSONResponse({"detail": "The planner is loading this season's FPL data. "
                                       "Try again in a minute or two."},
                            status_code=503, headers={"Retry-After": "60"})
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
