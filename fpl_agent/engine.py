"""The planning engine, shared by the CLI and the web API.

    setup = sync_setup(db, memory_path(memory_dir, manager_id), manager_id)
    plan = plan_from_setup(setup, PlanOptions(horizon=6))

Everything comes from FPL's public API: no login, so any manager ID works.
Player and fixture data is shared by every user; each manager gets their own
memory file. ``sync_setup`` refreshes FPL data, loads the team, and updates
memory.
``plan_from_setup`` forecasts and optimises; it can be re-run with different
options without hitting the API again. ``build_plan`` does both.

Precedence for free transfers and bank: explicit option, then memory
override, then the API value.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

from fpl_agent.data_ingest import FPLClient, FPLStore
from fpl_agent.data_ingest.manager import ManagerState, chip_status
from fpl_agent.data_ingest.models import get_meta
from fpl_agent.forecast import ExpectedPointsModel
from fpl_agent.forecast.team_ratings import TeamRatings
from fpl_agent.league import LeagueSnapshot, fetch_league
from fpl_agent.memory import AgentMemory
from fpl_agent.optimizer import optimize
from fpl_agent.optimizer.milp import OptimizationError, OptimizationResult, TeamState
from fpl_agent.planner import build_recommendation
from fpl_agent.planner.chips import (
    FREE_HIT_SETTINGS,
    LOOKAHEAD_CAP,
    WILDCARD_WEEKS,
    block,
    ChipPick,
    ChipValues,
    chip_outlook,
    chip_values,
    fixture_calendar,
    schedule_chips,
    single_week,
    wildcard_gain,
)
from fpl_agent.planner.recommend import Recommendation

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
DEFAULT_MEMORY_DIR = "memory"
# Players and fixtures are shared, so one user's refresh serves everyone for this long.
BOOTSTRAP_MAX_AGE_SECONDS = 5 * 60
# Several API requests can sync at once; only one refreshes the shared cache.
_refresh_lock = threading.Lock()


class EngineError(Exception):
    """A problem the user can act on (no data, chip unavailable, solver failure)."""


class DataNotReady(EngineError):
    """Shared FPL data hasn't been fetched yet (a fresh server is still warming up)."""


# Above this age, plans built from the cached data carry a note saying how old it is.
STALE_DATA_NOTE_SECONDS = 3600


def refresh_shared_data(db: str, client: FPLClient | None = None) -> None:
    """Bring players, fixtures and per-match history up to date if they're stale.

    Safe to call from several threads: only one refreshes at a time. Raises if
    FPL can't be reached.
    """
    store = FPLStore(client=client or FPLClient(), db_path=db)
    try:
        with _refresh_lock:
            if store.bootstrap_age() > BOOTSTRAP_MAX_AGE_SECONDS:
                store.refresh_all()
            if store.history_is_stale():
                store.refresh_all_player_histories()
    finally:
        store.close()


def manager_id_from_env() -> int | None:
    """FPL_MANAGER_ID if set (handy for the CLI), else None."""
    value = os.environ.get("FPL_MANAGER_ID", "").strip()
    return int(value) if value.isdigit() and int(value) > 0 else None


def parse_manager_id(text: str) -> int:
    """Read a team ID from what a user typed: '123456' or any FPL URL with
    ``/entry/123456/`` in it (e.g. the Points page)."""
    text = str(text).strip()
    match = re.search(r"/entry/(\d+)", text) or re.fullmatch(r"#?(\d+)", text)
    if not match or int(match.group(1)) <= 0:
        raise EngineError("That doesn't look like a team ID. It's the number in your "
                          "Points page link: fantasy.premierleague.com/entry/<ID>/event/…")
    return int(match.group(1))


def memory_path(memory_dir: str | Path, manager_id: int) -> Path:
    """Each manager's memory file: ``<memory_dir>/<manager_id>.json``."""
    return Path(memory_dir) / f"{int(manager_id)}.json"


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
    deadlines: dict[int, str] = field(default_factory=dict)   # GW → ISO deadline (UTC)

    @property
    def leagues(self) -> list[dict]:
        """Your private classic leagues: [{"id", "name", "rank"}]."""
        return self.memory.data.get("manager", {}).get("leagues", [])

    @property
    def planning_gw(self) -> int:
        return self.current_gw + 1

    def chip_available(self, name: str) -> bool:
        return any(c["name"] == name and c["status"] == "available" for c in self.chips)


def _is_not_found(exc: Exception) -> bool:
    resp = getattr(exc, "response", None)
    return isinstance(exc, requests.HTTPError) and resp is not None and resp.status_code == 404


def sync_setup(db: str, memory_file: str | Path, manager_id: int,
               force_refresh: bool = False, refresh_shared: bool = True) -> Setup:
    """Refresh shared data if it's stale, load the manager's team from public
    endpoints, and update their memory.

    With ``refresh_shared=False`` (the hosted API, where a background thread
    keeps shared data fresh) it never fetches players, fixtures or history
    while a user waits; it raises DataNotReady if there's no data yet.

    Falls back to the cached database and the memory snapshot when the FPL API
    is unreachable. Raises EngineError if the team doesn't exist.
    """
    memory = AgentMemory(memory_file)
    client = FPLClient()
    notes: list[str] = []

    store = FPLStore(client=client, db_path=db)
    try:
        if refresh_shared:
            with _refresh_lock:
                try:
                    if force_refresh or store.bootstrap_age() > BOOTSTRAP_MAX_AGE_SECONDS:
                        store.refresh_all()
                    if store.history_is_stale():
                        store.refresh_all_player_histories()
                except Exception as exc:
                    if store.players_df().empty:
                        raise EngineError(f"FPL API unreachable and no cached data: {exc}") from exc
                    notes.append(f"FPL API unreachable ({exc.__class__.__name__}); using cached data.")
        else:
            if store.players_df().empty or get_meta(store.conn, "history_fetched_at") is None:
                raise DataNotReady("The planner is loading this season's FPL data. "
                                   "Try again in a minute or two.")
            age = store.bootstrap_age()
            if age > STALE_DATA_NOTE_SECONDS:
                notes.append(f"Player data is {age / 3600:.0f}h old; FPL couldn't be reached since.")

        synced = True
        try:
            state = store.load_manager_state(manager_id)
        except Exception as exc:
            if _is_not_found(exc):
                raise EngineError(f"No FPL team found with ID {manager_id}. Check the number "
                                  "in your Points page link.") from exc
            if memory.has_snapshot and memory.data["manager"].get("id") == manager_id:
                state = memory.to_manager_state()
                synced = False
            elif isinstance(exc, ValueError):      # e.g. team created but no gameweek played
                raise EngineError(str(exc)) from exc
            else:
                raise EngineError(f"Couldn't load team {manager_id}: {exc}") from exc

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
            deadlines={int(r.id): r.deadline_time for r in store.gameweeks_df().itertuples()
                       if r.deadline_time},
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
    consistency: float = 0.5              # preference for steady returners
    # Locked/banned player ids for this request; None = use the team's memory.
    locked: frozenset[int] | None = None
    banned: frozenset[int] | None = None


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
    chip_plan: list[ChipPick] = field(default_factory=list)


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
                  consistency=opts.consistency,
                  locked=set(memory.locked_ids if opts.locked is None else opts.locked),
                  banned=set(memory.banned_ids if opts.banned is None else opts.banned))
    names = dict(zip(setup.players["id"], setup.players["web_name"]))
    chip_mode = opts.wildcard or opts.free_hit
    try:
        baseline = optimize(team_state, forecast, setup.players, max_transfers=0,
                            **{**common, "locked": set(), "banned": set()})
        result = optimize(team_state, forecast, setup.players,
                          horizon=1 if opts.free_hit else None,
                          unlimited_transfers=chip_mode, **common)
        values, picks = _chip_plan(setup, opts, team_state, common)
    except OptimizationError as exc:
        raise EngineError(f"Optimiser failed: {exc}") from exc

    rec = build_recommendation(result, setup.players, forecast, state.squad, state.selling_prices,
                               baseline=baseline, fixtures=setup.fixtures, teams=setup.teams,
                               bank=team_state.bank)
    gws = values.weeks if values else list(range(setup.planning_gw, setup.planning_gw + opts.horizon))
    advice = chip_outlook(picks, values, setup.chips,
                          fixture_calendar(setup.fixtures, setup.teams, gws), names=names)

    if record:
        memory.record_recommendation(setup.planning_gw, rec, names, advice)
        memory.save()
    return Plan(rec, setup, team_state, forecast, advice,
                {"free_transfers": ft_src, "bank": bank_src}, model.ratings, result, baseline, picks)


def _chip_plan(setup: Setup, opts: PlanOptions, team_state: TeamState,
               common: dict) -> tuple[ChipValues | None, list[ChipPick]]:
    """Value the open chips week by week up to their expiry and schedule them.

    Looks past the user's horizon: a chip that expires after GW19 has to be
    planned against every week left before then.
    """
    open_chips = [c for c in setup.chips if c.get("status") == "available"]
    if not open_chips:
        return None, []
    first = setup.planning_gw
    last = max(c["window"][1] for c in open_chips)
    chip_end = min(last, first + LOOKAHEAD_CAP - 1, 38)
    weeks = list(range(first, chip_end + 1))
    has_wc = setup.chip_available("wildcard")
    # A Wildcard's haul can run past the chip window, so forecast that far.
    forecast_end = min(38, chip_end + (WILDCARD_WEEKS - 1 if has_wc else 0))
    forecast = ExpectedPointsModel(
        players=setup.players, history=setup.history, fixtures=setup.fixtures,
        teams=setup.teams, current_gw=setup.current_gw, horizon=forecast_end - first + 1,
        scoring=setup.scoring,
    ).predict()
    players = setup.players
    base = optimize(team_state, block(forecast, first, len(weeks)), players, **common)
    wildcards = None
    if has_wc:
        wildcards = {}
        for g in weeks:
            haul = block(forecast, g, WILDCARD_WEEKS)
            wc = optimize(team_state, haul, players, unlimited_transfers=True, **common)
            normal = optimize(team_state, haul, players, **common)
            wildcards[g] = (wc, wildcard_gain(wc, normal, forecast,
                                              team_state.free_transfers, common["ft_value"]))
    free_hits = ({g: optimize(team_state, single_week(forecast, g), players,
                              unlimited_transfers=True, **FREE_HIT_SETTINGS) for g in weeks}
                 if setup.chip_available("freehit") else None)
    values = chip_values(base, forecast, wildcards, free_hits)
    fixed = {"wildcard": first} if opts.wildcard else {"freehit": first} if opts.free_hit else {}
    return values, schedule_chips(values, setup.chips, fixed)


def build_plan(db: str, memory_file: str | Path, manager_id: int, opts: PlanOptions) -> Plan:
    return plan_from_setup(sync_setup(db, memory_file, manager_id), opts)


# -- Views shared by CLI and API ----------------------------------------------

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
