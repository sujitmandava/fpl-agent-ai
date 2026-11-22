"""The planning engine, shared by the CLI and the web dashboard.

    setup = sync_setup(db, memory_path, manager_id, refresh_token)
    plan = plan_from_setup(setup, PlanOptions(horizon=6))

``sync_setup`` refreshes FPL data, loads your team, and updates memory.
``plan_from_setup`` forecasts and optimises; it can be re-run with different
options without hitting the API again. ``build_plan`` does both.

Precedence for free transfers and bank: explicit option, then memory
override, then the API value.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from fpl_agent.data_ingest import FPLClient, FPLStore
from fpl_agent.data_ingest.auth import TokenStore
from fpl_agent.data_ingest.manager import ManagerState, chip_status
from fpl_agent.data_ingest.models import get_meta
from fpl_agent.forecast import ExpectedPointsModel
from fpl_agent.forecast.team_ratings import TeamRatings
from fpl_agent.league import LeagueSnapshot, fetch_league
from fpl_agent.memory import AgentMemory
from fpl_agent.optimizer import optimize
from fpl_agent.optimizer.milp import OptimizationError, OptimizationResult, TeamState
from fpl_agent.planner import build_recommendation
from fpl_agent.planner.chips import chip_outlook, fixture_calendar
from fpl_agent.planner.recommend import Recommendation

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
# Your FPL team ID; FPL_MANAGER_ID or --manager-id override it.
DEFAULT_MANAGER_ID = 7588693


def manager_id_from_env() -> int:
    return int(os.environ.get("FPL_MANAGER_ID") or DEFAULT_MANAGER_ID)


class EngineError(Exception):
    """A problem the user can act on (no data, chip unavailable, solver failure)."""


# -- Setup --------------------------------------------------------------------

@dataclass
class Setup:
    """Everything known about the manager's situation for the next deadline."""
    state: ManagerState
    memory: AgentMemory
    players: pd.DataFrame
    history: pd.DataFrame
    fixtures: pd.DataFrame
    teams: pd.DataFrame
    scoring: dict
    current_gw: int
    chips: list[dict]
    max_ft: int
    synced: bool
    notes: list[str] = field(default_factory=list)
    chip_defs: list[dict] = field(default_factory=list)
    league: LeagueSnapshot | None = None

    @property
    def leagues(self) -> list[dict]:
        """Your private classic leagues: [{"id", "name", "rank"}]."""
        return self.memory.data.get("manager", {}).get("leagues", [])

    @property
    def planning_gw(self) -> int:
        return self.current_gw + 1

    def chip_available(self, name: str) -> bool:
        return any(c["name"] == name and c["status"] == "available" for c in self.chips)


def sync_setup(db: str, memory_path: str, manager_id: int,
               refresh_token: str | None = None) -> Setup:
    """Refresh data, load the manager's setup, and update memory.

    Logs in with *refresh_token* (or the rotated one saved by an earlier run)
    when available. Falls back to the cached database and the memory snapshot
    when the FPL API is unreachable.
    """
    memory = AgentMemory(memory_path)
    client = FPLClient()
    notes: list[str] = []
    if refresh_token or TokenStore().load():
        try:
            client.login(refresh_token)
        except Exception as exc:
            notes.append(f"Login failed: {exc}")

    store = FPLStore(client=client, db_path=db)
    try:
        try:
            store.refresh_all()
            if store.history_is_stale():
                store.refresh_all_player_histories()
        except Exception as exc:
            if store.players_df().empty:
                raise EngineError(f"FPL API unreachable and no cached data: {exc}") from exc
            notes.append(f"FPL API unreachable ({exc.__class__.__name__}); using cached data.")

        synced = True
        try:
            state = store.load_manager_state(manager_id)
        except Exception as exc:
            if memory.has_snapshot and memory.data["manager"].get("id") == manager_id:
                state = memory.to_manager_state()
                synced = False
            else:
                raise EngineError(f"Could not load your team: {exc}") from exc

        players, teams = store.players_df(), store.teams_df()
        current_gw = store.current_gameweek()
        if synced:
            chips = chip_status(store.chip_definitions(), state.chips_played, current_gw + 1)
            memory.record_sync(manager_id, state, current_gw + 1,
                               get_meta(store.conn, "season"), players, teams, chips)
        else:
            chips = memory.data.get("chips", [])
            memory.prune_overrides(current_gw + 1)
        memory.save()

        setup = Setup(
            state=state, memory=memory, players=players,
            history=store.player_history_df(), fixtures=store.fixtures_df(), teams=teams,
            scoring=store.scoring_rules(), current_gw=current_gw, chips=chips,
            max_ft=store.max_free_transfers(), synced=synced, notes=notes,
            chip_defs=store.chip_definitions(),
        )
        if synced:
            load_league(setup, client=client)
        return setup
    finally:
        store.close()


def load_league(setup: Setup, league_id: int | None = None, client: FPLClient | None = None,
                max_rivals: int = 10) -> LeagueSnapshot | None:
    """Fetch a mini-league into ``setup.league``; failures become a note.

    League choice: *league_id*, else ``FPL_LEAGUE_ID``, else your first
    private league.
    """
    if league_id is None:
        env = os.environ.get("FPL_LEAGUE_ID")
        league_id = int(env) if env else (setup.leagues[0]["id"] if setup.leagues else None)
    if not league_id:
        return None
    try:
        setup.league = fetch_league(client or FPLClient(), int(league_id), setup.current_gw,
                                    me=int(setup.memory.data["manager"]["id"]),
                                    chip_defs=setup.chip_defs, max_rivals=max_rivals)
    except Exception as exc:
        setup.notes.append(f"Couldn't load mini-league {league_id}: {exc.__class__.__name__}")
    return setup.league


# -- Planning -----------------------------------------------------------------

@dataclass
class PlanOptions:
    horizon: int = 6
    free_transfers: int | None = None     # one-off override
    bank: float | None = None             # one-off override, £m
    wildcard: bool = False
    free_hit: bool = False
    bench_weight: float = 0.1
    ft_value: float = 1.0


@dataclass
class Plan:
    rec: Recommendation
    setup: Setup
    team_state: TeamState
    forecast: pd.DataFrame
    chip_advice: list[str]
    sources: dict[str, str]
    ratings: TeamRatings
    result: OptimizationResult
    baseline: OptimizationResult


def plan_from_setup(setup: Setup, opts: PlanOptions, record: bool = True) -> Plan:
    """Forecast, optimise and explain. Raises EngineError on bad input."""
    if opts.wildcard and opts.free_hit:
        raise EngineError("Choose Wildcard or Free Hit, not both.")
    for flag, chip, label in ((opts.wildcard, "wildcard", "Wildcard"),
                              (opts.free_hit, "freehit", "Free Hit")):
        if flag and not setup.chip_available(chip):
            raise EngineError(f"Your {label} isn't available for GW{setup.planning_gw}.")

    state, memory = setup.state, setup.memory
    overrides = memory.active_overrides(setup.planning_gw)
    if opts.free_transfers is not None:
        ft, ft_src = opts.free_transfers, "one-off"
    elif "free_transfers" in overrides:
        ft, ft_src = int(overrides["free_transfers"]), "memory override"
    else:
        ft, ft_src = state.free_transfers, state.source
    if opts.bank is not None:
        bank, bank_src = int(round(opts.bank * 10)), "one-off"
    elif "bank" in overrides:
        bank, bank_src = int(overrides["bank"]), "memory override"
    else:
        bank, bank_src = state.bank, state.source

    team_state = TeamState(current_squad=state.squad, selling_prices=state.selling_prices,
                           bank=bank, free_transfers=min(ft, setup.max_ft))

    model = ExpectedPointsModel(
        players=setup.players, history=setup.history, fixtures=setup.fixtures,
        teams=setup.teams, current_gw=setup.current_gw, horizon=opts.horizon,
        scoring=setup.scoring,
    )
    forecast = model.predict()

    common = dict(bench_weight=opts.bench_weight, ft_value=opts.ft_value,
                  locked=memory.locked_ids, banned=memory.banned_ids)
    names = dict(zip(setup.players["id"], setup.players["web_name"]))
    chip_mode = opts.wildcard or opts.free_hit
    try:
        baseline = optimize(team_state, forecast, setup.players, max_transfers=0,
                            **{**common, "locked": set(), "banned": set()})
        result = optimize(team_state, forecast, setup.players,
                          horizon=1 if opts.free_hit else None,
                          unlimited_transfers=chip_mode, **common)
        wc_res = fh_res = None
        if not chip_mode:
            if setup.chip_available("wildcard"):
                wc_res = optimize(team_state, forecast, setup.players,
                                  unlimited_transfers=True, **common)
            if setup.chip_available("freehit"):
                fh_res = optimize(team_state, forecast, setup.players, horizon=1,
                                  unlimited_transfers=True, **common)
    except OptimizationError as exc:
        raise EngineError(f"Optimiser failed: {exc}") from exc

    rec = build_recommendation(result, setup.players, forecast, state.squad, state.selling_prices,
                               baseline=baseline, fixtures=setup.fixtures, teams=setup.teams,
                               bank=team_state.bank)
    gws = (result.gameweeks if not opts.free_hit
           else list(range(setup.planning_gw, setup.planning_gw + opts.horizon)))
    advice = chip_outlook(result if not opts.free_hit else baseline, setup.chips,
                          fixture_calendar(setup.fixtures, setup.teams, gws),
                          wildcard=wc_res, free_hit=fh_res, names=names)

    if record:
        memory.record_recommendation(setup.planning_gw, rec, names, advice)
        memory.save()
    return Plan(rec, setup, team_state, forecast, advice,
                {"free_transfers": ft_src, "bank": bank_src}, model.ratings, result, baseline)


def build_plan(db: str, memory_path: str, manager_id: int, refresh_token: str | None,
               opts: PlanOptions) -> Plan:
    return plan_from_setup(sync_setup(db, memory_path, manager_id, refresh_token), opts)


# -- Views shared by CLI and dashboard ----------------------------------------

def player_table(setup: Setup, forecast: pd.DataFrame) -> pd.DataFrame:
    """One row per player: identity, price, ownership, and every forecast column."""
    p = setup.players.merge(
        setup.teams[["id", "short_name"]].rename(columns={"id": "team_id", "short_name": "team"}),
        on="team_id", how="left",
    )
    p = p.merge(forecast, left_on="id", right_on="player_id", how="left")
    p["pos"] = p["element_type"].map(POS)
    p["price"] = p["now_cost"] / 10
    p["owned"] = p["id"].isin(setup.state.squad)
    return p


def next_opponents(fixtures: pd.DataFrame, teams: pd.DataFrame, gw: int) -> dict[int, str]:
    """team_id → 'ARS (H)' (or 'ARS (H) + CHE (a)' in a double) for one gameweek."""
    short = dict(zip(teams["id"], teams["short_name"]))
    out: dict[int, list[str]] = {}
    for f in fixtures[fixtures["event"] == gw].itertuples(index=False):
        out.setdefault(int(f.team_h), []).append(f"{short.get(f.team_a, '?')} (H)")
        out.setdefault(int(f.team_a), []).append(f"{short.get(f.team_h, '?')} (a)")
    return {t: " + ".join(v) for t, v in out.items()}


def fixture_grid(ratings: TeamRatings, fixtures: pd.DataFrame, teams: pd.DataFrame,
                 gws: list[int]) -> pd.DataFrame:
    """Long table: team, gw, opponent label, expected goals for/against, CS chance.

    Blank gameweeks get a row with no opponent; doubles get one row per match.
    """
    import math

    short = dict(zip(teams["id"], teams["short_name"]))
    rows = []
    for gw in gws:
        fx = fixtures[fixtures["event"] == gw]
        playing = set()
        for f in fx.itertuples(index=False):
            for team, opp, home in ((f.team_h, f.team_a, True), (f.team_a, f.team_h, False)):
                g_for, g_against = ratings.expected_goals(int(team), int(opp), home)
                rows.append({"team_id": int(team), "team": short.get(team, team), "gw": gw,
                             "opp": f"{short.get(opp, opp)} ({'H' if home else 'a'})",
                             "xg_for": g_for, "xg_against": g_against,
                             "cs": math.exp(-g_against)})
                playing.add(int(team))
        for t in teams["id"].astype(int):
            if t not in playing:
                rows.append({"team_id": t, "team": short.get(t, t), "gw": gw, "opp": "—",
                             "xg_for": 0.0, "xg_against": 0.0, "cs": 0.0})
    return pd.DataFrame(rows)


# -- Player lookup ------------------------------------------------------------

# Letters that Unicode normalisation doesn't decompose into base + accent.
_TRANSLIT = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss", "ł": "l",
                           "Ł": "l", "đ": "d", "Đ": "d", "ı": "i", "œ": "oe", "Œ": "oe"})


def norm(s: str) -> str:
    """Lower-case and strip accents so 'odegaard' finds 'Ødegaard'."""
    s = str(s).translate(_TRANSLIT)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def find_player(players: pd.DataFrame, query: str) -> tuple[int, str]:
    """Resolve a name (accent/case-insensitive) or numeric id to (id, web_name)."""
    if query.isdigit():
        hit = players[players["id"] == int(query)]
    else:
        q = norm(query)
        web = players["web_name"].map(norm)
        full = (players["first_name"].fillna("") + " " + players["second_name"].fillna("")).map(norm)
        hit = players[web == q]
        if hit.empty:
            hit = players[web.str.contains(q, regex=False) | full.str.contains(q, regex=False)]
    if hit.empty:
        raise EngineError(f"No player matches '{query}'.")
    if len(hit) > 1:
        team = hit["short_name"] if "short_name" in hit.columns else pd.Series("", index=hit.index)
        opts = ", ".join(f"{r.web_name} ({t}, £{r.now_cost / 10:.1f}m, id {r.id})"
                         for r, t in zip(hit.head(8).itertuples(), team.head(8)))
        raise EngineError(f"'{query}' is ambiguous: {opts}. Use the id.")
    r = hit.iloc[0]
    return int(r["id"]), str(r["web_name"])
