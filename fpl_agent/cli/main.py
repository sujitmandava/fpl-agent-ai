"""CLI entry-point for the FPL Agent.

All options read from a .env file (or exported environment variables)
so you can simply run:

    python fpl_agent.py ui               # open the dashboard in your browser
    python fpl_agent.py recommend        # plan transfers, lineup, captain, chips
    python fpl_agent.py status           # what the agent remembers about your team
    python fpl_agent.py memory --help    # overrides, locked/banned players, notes
    python fpl_agent.py backtest         # check forecast accuracy on past gameweeks

Command-line flags override memory, which overrides values read from the API.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import click
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fpl_agent import engine
from fpl_agent.data_ingest import FPLStore
from fpl_agent.engine import POS, EngineError, Plan, PlanOptions
from fpl_agent.forecast.backtest import backtest as run_backtest
from fpl_agent.memory import AgentMemory

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

console = Console()
logger = logging.getLogger("fpl_agent")


class _Group(click.Group):
    """Turns EngineError into a clean CLI error message."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except EngineError as exc:
            raise click.ClickException(str(exc)) from exc


@click.group(cls=_Group)
@click.option("--db", envvar="FPL_DB", default="fpl_agent.db", show_default=True,
              help="Path to SQLite cache.")
@click.option("--memory", "memory_path", envvar="FPL_MEMORY", default="fpl_memory.json",
              show_default=True, help="Path to the agent's memory file.")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, db: str, memory_path: str, verbose: bool) -> None:
    """FPL Agent AI – agentic Fantasy Premier League assistant."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["memory"] = memory_path


# -- refresh ------------------------------------------------------------------

@cli.command()
@click.option("--top-n", envvar="FPL_TOP_N", type=int, default=0, show_default=True,
              help="Limit history fetch to the top N players (0 = everyone who has played).")
@click.pass_context
def refresh(ctx: click.Context, top_n: int) -> None:
    """Pull latest data from the FPL API and store in SQLite."""
    store = FPLStore(db_path=ctx.obj["db"])
    console.print("[bold cyan]Refreshing bootstrap & fixtures…[/]")
    store.refresh_all()
    console.print("[bold cyan]Fetching player histories…[/]")
    n = store.refresh_all_player_histories(top_n=top_n or None)
    store.close()
    console.print(f"[bold green]Data refresh complete ({n} player histories).[/]")


# -- plan ---------------------------------------------------------------------

_plan_options = [
    click.option("--manager-id", envvar="FPL_MANAGER_ID", type=int,
                 default=engine.DEFAULT_MANAGER_ID, show_default=True, help="FPL manager ID."),
    click.option("--refresh-token", envvar="FPL_REFRESH_TOKEN", default=None,
                 help="FPL login token copied from your browser (see README)."),
    click.option("--horizon", envvar="FPL_HORIZON", type=click.IntRange(1, 8), default=6,
                 show_default=True, help="Forecast horizon in gameweeks."),
    click.option("--free-transfers", envvar="FPL_FREE_TRANSFERS", type=click.IntRange(0, 5),
                 default=None, help="One-off override (to persist one: `memory set-ft`)."),
    click.option("--bank", envvar="FPL_BANK", type=float, default=None,
                 help="One-off bank override in £m (to persist one: `memory set-bank`)."),
    click.option("--wildcard", is_flag=True, help="Plan with your Wildcard active."),
    click.option("--free-hit", is_flag=True, help="Plan a one-week Free Hit squad."),
    click.option("--bench-weight", type=float, default=0.1, show_default=True,
                 help="How much bench players' EP counts (auto-sub value)."),
    click.option("--ft-value", type=float, default=1.0, show_default=True,
                 help="Points a saved free transfer is worth (higher = fewer, surer moves)."),
]


def plan_options(f):
    for opt in reversed(_plan_options):
        f = opt(f)
    return f


def sync_setup(db: str, memory_path: str, manager_id: int,
               refresh_token: str | None) -> engine.Setup:
    with console.status("Refreshing FPL data…"):
        setup = engine.sync_setup(db, memory_path, manager_id, refresh_token)
    for note in setup.notes:
        if note.startswith("Login failed"):
            console.print(f"[yellow]{note}[/]")
    return setup


def build_plan(db: str, memory_path: str, manager_id: int, refresh_token: str | None,
               **opts) -> Plan:
    setup = sync_setup(db, memory_path, manager_id, refresh_token)
    with console.status("Optimising…"):
        return engine.plan_from_setup(setup, PlanOptions(**opts))

# -- recommend ----------------------------------------------------------------

@cli.command()
@plan_options
@click.pass_context
def recommend(ctx: click.Context, **kwargs) -> None:
    """Generate transfer, lineup, captain and chip recommendations."""
    plan = build_plan(ctx.obj["db"], ctx.obj["memory"], **kwargs)
    _print_header(plan)
    _print_recommendation(plan)


def _print_header(plan: Plan) -> None:
    s, mem = plan.setup, plan.setup.memory.data
    mgr = mem.get("manager", {})
    title = mgr.get("team_name") or f"Manager {mgr.get('id')}"
    rank = f" · rank {mgr['overall_rank']:,}" if mgr.get("overall_rank") else ""
    console.print(f"[bold]{title}[/]{rank} · planning GW{s.planning_gw}")
    console.print(
        f"[dim]Free transfers {plan.team_state.free_transfers} ({plan.sources['free_transfers']}) · "
        f"bank £{plan.team_state.bank / 10:.1f}m ({plan.sources['bank']}) · "
        f"budget £{plan.team_state.total_budget / 10:.1f}m[/]"
    )
    avail = [f"{c['label']} (≤GW{c['window'][1]})" for c in s.chips if c["status"] == "available"]
    console.print(f"[dim]Chips available: {', '.join(avail) or 'none'}[/]")
    locked = ", ".join(p["name"] for p in mem.get("locked", []))
    banned = ", ".join(p["name"] for p in mem.get("banned", []))
    if locked or banned:
        console.print(f"[dim]Locked: {locked or '—'} · Banned: {banned or '—'}[/]")
    for note in s.notes + s.state.notes:
        console.print(f"[dim]· {note}[/]")
    for n in mem.get("notes", []):
        console.print(f"[dim]· Note: {n['text']}[/]")


def _print_recommendation(plan: Plan) -> None:
    rec, players, fc = plan.rec, plan.setup.players, plan.forecast.set_index("player_id")
    name = dict(zip(players["id"], players["web_name"]))
    pos = dict(zip(players["id"], players["element_type"]))
    team = dict(zip(players["id"], players["team_id"]))
    short = dict(zip(plan.setup.teams["id"], plan.setup.teams["short_name"]))
    opp = engine.next_opponents(plan.setup.fixtures, plan.setup.teams, rec.next_gw or plan.setup.planning_gw)

    if rec.transfers:
        t = Table(title="Recommended Transfers", show_lines=True)
        for col, kw in [("Pos", {}), ("OUT", {"style": "red"}), ("Sell", {"justify": "right"}),
                        ("IN", {"style": "green"}), ("Buy", {"justify": "right"}),
                        ("ΔxPts next", {"justify": "right"}), ("ΔxPts horizon", {"justify": "right"})]:
            t.add_column(col, **kw)
        for tr in rec.transfers:
            t.add_row(tr.position, tr.sell_name, f"£{tr.sell_price:.1f}m", tr.buy_name,
                      f"£{tr.buy_price:.1f}m", f"{tr.ep_gain_next:+.1f}", f"{tr.ep_gain_horizon:+.1f}")
        console.print(t)
    else:
        console.print("[green]No transfers recommended. Save the free transfer.[/]")

    gw = f"GW{rec.next_gw}" if rec.next_gw else "Next GW"
    xi = Table(title=f"Starting XI – {gw}")
    for col, kw in [("Pos", {}), ("Player", {}), ("Opp", {}), ("Mins", {"justify": "right"}),
                    ("xG/90", {"justify": "right"}), ("xA/90", {"justify": "right"}),
                    ("DC%", {"justify": "right"}), ("CS%", {"justify": "right"}),
                    (f"xPts {gw}", {"justify": "right", "style": "bold"}),
                    ("xPts horizon", {"justify": "right"}), ("", {})]:
        xi.add_column(col, **kw)

    def row(pid):
        f = fc.loc[pid] if pid in fc.index else {}
        role = "(C)" if pid == rec.captain_id else ("(V)" if pid == rec.vice_captain_id else "")
        return [POS.get(pos.get(pid, 0), "?"), f"{name.get(pid, pid)} [dim]{short.get(team.get(pid), '')}[/]",
                opp.get(team.get(pid), "—"), f"{f.get('exp_minutes', 0):.0f}",
                f"{f.get('xg90', 0):.2f}", f"{f.get('xa90', 0):.2f}",
                f"{f.get('dc_rate', 0) * 100:.0f}" if pos.get(pid) != 1 else "",
                f"{f.get('cs_next', 0) * 100:.0f}", f"{f.get('expected_points_next', 0):.1f}",
                f"{f.get('total_expected_points', 0):.1f}", role]

    for pid in rec.starting_xi:
        xi.add_row(*row(pid))
    xi.add_section()
    for pid in rec.bench_order:
        xi.add_row(*[f"[dim]{c}[/]" for c in row(pid)])
    console.print(xi)
    console.print("[dim]Bench order as listed (GK slot first). DC% = chance of defensive-contribution "
                  "points in a 60+ min game; CS% = clean-sheet chance.[/]")

    summary = (
        f"Projected {gw}: [bold]{rec.next_gw_points:.1f}[/] (XI + captain)\n"
        f"vs. no transfers, {gw}: [bold]{rec.expected_points_delta:+.1f}[/]"
    )
    if rec.horizon_delta is not None:
        summary += f"\nvs. no transfers, horizon: [bold]{rec.horizon_delta:+.1f}[/]"
    summary += f"\nTransfer hits: {rec.transfer_cost} pts"
    console.print(Panel(summary, title="Summary"))
    console.print(Panel("\n".join(plan.chip_advice), title="Chip outlook", border_style="magenta"))
    console.print(Panel(rec.rationale, title="Rationale", border_style="blue"))


# -- league -------------------------------------------------------------------

SHORT_CHIP = {"Triple Captain": "TC", "Bench Boost": "BB", "Free Hit": "FH", "Wildcard": "WC"}


@cli.command()
@plan_options
@click.option("--league-id", envvar="FPL_LEAGUE_ID", type=int, default=None,
              help="Classic league id (default: your first private league).")
@click.option("--rival", default=None, help="Rival team name to compare with (default: leader, "
                                             "or the closest chaser if you lead).")
@click.pass_context
def league(ctx: click.Context, league_id: int | None, rival: str | None, **kwargs) -> None:
    """Mini-league standings, rivals' chips and captains, and you vs a rival."""
    from fpl_agent.league import head_to_head, league_ownership

    setup = sync_setup(ctx.obj["db"], ctx.obj["memory"], kwargs.pop("manager_id"),
                       kwargs.pop("refresh_token"))
    if league_id and (setup.league is None or setup.league.league_id != league_id):
        engine.load_league(setup, league_id)
    lg = setup.league
    if lg is None or lg.mine is None:
        raise click.ClickException("No mini-league loaded. " + " ".join(setup.notes))
    with console.status("Optimising…"):
        plan = engine.plan_from_setup(setup, PlanOptions(**kwargs), record=False)
    name = dict(zip(setup.players["id"], setup.players["web_name"]))
    me = lg.mine

    t = Table(title=f"{lg.name} · after GW{lg.gw}")
    for col in ("#", "Team", "Total", f"GW{lg.gw}", "Gap", "Captain", "Chip", "Chips left now"):
        t.add_column(col, justify="right" if col in ("#", "Total", f"GW{lg.gw}", "Gap") else "left")
    for r in lg.rivals:
        style = "bold" if r.entry == lg.me else ""
        t.add_row(str(r.rank), r.team_name, str(r.total), str(r.gw_points), f"{r.total - me.total:+d}",
                  name.get(r.captain, "—"), r.active_chip or "",
                  " ".join(SHORT_CHIP.get(c, c) for c in r.chips_now) or "none",
                  style=style)
    console.print(t)

    others = [r for r in lg.rivals if r.entry != lg.me]
    target = lg.target
    if rival:
        hits = [r for r in others if rival.lower() in r.team_name.lower()]
        if not hits:
            raise click.ClickException(f"No rival matches '{rival}'.")
        target = hits[0]
    if target is None:
        return
    fc = plan.forecast.set_index("player_id")
    h = head_to_head(lg, target.entry, plan.forecast, setup.players, setup.state.squad, plan.result.gameweeks)
    eo = league_ownership(lg).set_index("player_id")["eo_pct"].to_dict()

    def fmt(ids):
        ids = sorted(ids, key=lambda p: -fc.at[p, "total_expected_points"] if p in fc.index else 0)
        return "\n".join(f"{name.get(p)}  {fc.at[p, 'total_expected_points']:.1f} xPts · "
                         f"league EO {eo.get(p, 0):.0f}%" for p in ids if p in fc.index)

    console.print(Panel(
        f"Gap: [bold]{-h.gap:+d}[/] · your edge {h.edge_per_gw:+.1f} xPts/GW over the next "
        f"{len(h.by_gw)} (both squads held) · weekly swing ±{h.weekly_sd:.0f}\n"
        f"Rough chance to finish above {target.team_name}: [bold]{h.p_ahead:.0%}[/] "
        f"({h.remaining} GWs left)\n"
        f"Shared players: {len(h.shared)}/15. Captains: "
        + ", ".join(f"GW{r.gw} {name.get(r.your_captain)} vs {name.get(r.their_captain)}"
                    for r in h.by_gw.itertuples()),
        title=f"You vs {target.team_name}", border_style="cyan"))
    d = Table(show_header=True)
    d.add_column("Only you have", style="green")
    d.add_column(f"Only {target.team_name} has", style="red")
    d.add_row(fmt(h.mine_only), fmt(h.theirs_only))
    console.print(d)


# -- status & memory ----------------------------------------------------------

@cli.command()
@click.option("--sync", is_flag=True, help="Refresh from the FPL API before showing.")
@click.option("--manager-id", envvar="FPL_MANAGER_ID", type=int,
              default=engine.DEFAULT_MANAGER_ID, show_default=True)
@click.option("--refresh-token", envvar="FPL_REFRESH_TOKEN", default=None)
@click.pass_context
def status(ctx: click.Context, sync: bool, manager_id: int | None,
           refresh_token: str | None) -> None:
    """Show what the agent remembers: team, transfers, bank, chips, preferences."""
    if sync:
        if not manager_id:
            raise click.UsageError("--sync needs --manager-id (or FPL_MANAGER_ID).")
        sync_setup(ctx.obj["db"], ctx.obj["memory"], manager_id, refresh_token)
    _print_memory(AgentMemory(ctx.obj["memory"]))


def _print_memory(memory: AgentMemory) -> None:
    d = memory.data
    if not memory.has_snapshot:
        console.print("[yellow]Memory is empty. Run `recommend` or `status --sync` first.[/]")
        return
    mgr = d.get("manager", {})
    console.print(f"[bold]{mgr.get('team_name') or 'Your team'}[/] (manager {mgr.get('id')}) · "
                  f"season {d.get('season')} · planning GW{d.get('planning_gw')}")
    rank = f"{mgr['overall_rank']:,}" if mgr.get("overall_rank") else "—"
    console.print(f"[dim]Synced {d.get('synced_at')} via {d.get('synced_source')} · "
                  f"overall {mgr.get('overall_points', '—')} pts, rank {rank}[/]")

    t = Table(title="Squad")
    for col in ("Pos", "Player", "Team", "Bought", "Sell", "Now"):
        t.add_column(col, justify="right" if col in ("Bought", "Sell", "Now") else "left")
    order = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
    fmt = lambda v: f"£{v / 10:.1f}m" if v else "—"  # noqa: E731
    for p in sorted(d["squad"], key=lambda p: order.get(p["pos"], 9)):
        t.add_row(p["pos"], p["name"], p["team"], fmt(p.get("purchase_price")),
                  fmt(p["selling_price"]), fmt(p["now_cost"]))
    console.print(t)

    overrides = d.get("overrides", {})
    ft = d.get("free_transfers")
    ft_line = f"{ft}" + (f" → override {overrides['free_transfers']['value']}" if "free_transfers" in overrides else "")
    bank = d.get("bank") or 0
    bank_line = f"£{bank / 10:.1f}m" + (f" → override £{overrides['bank']['value'] / 10:.1f}m"
                                         if "bank" in overrides else "")
    console.print(f"Free transfers: [bold]{ft_line}[/] · Bank: [bold]{bank_line}[/]")

    c = Table(title="Chips")
    for col in ("Chip", "Window", "Status"):
        c.add_column(col)
    style = {"available": "green", "played": "dim", "expired": "red", "upcoming": "cyan"}
    for chip in d.get("chips", []):
        st = chip["status"] + (f" (GW{chip['event']})" if chip.get("event") else "")
        c.add_row(chip["label"], f"GW{chip['window'][0]}–{chip['window'][1]}",
                  f"[{style.get(chip['status'], '')}]{st}[/]")
    console.print(c)

    if d.get("locked") or d.get("banned"):
        console.print("Locked: " + (", ".join(p["name"] for p in d["locked"]) or "—"))
        console.print("Banned: " + (", ".join(p["name"] for p in d["banned"]) or "—"))
    for i, n in enumerate(d.get("notes", [])):
        console.print(f"Note {i}: {n['text']} [dim]({n['added_at'][:10]})[/]")
    leagues = mgr.get("leagues", [])
    if leagues:
        console.print("Mini-leagues: " + ", ".join(f"{lg['name']} (#{lg['rank']})" for lg in leagues))
    if d.get("recommendations"):
        last = d["recommendations"][-1]
        moves = ", ".join(f"{t['out']} → {t['in']}" for t in last["transfers"]) or "no transfers"
        console.print(f"[dim]Last recommendation (GW{last['gw']}, {last['created_at'][:16]}): "
                      f"{moves}; captain {last['captain']}.[/]")
    console.print(f"[dim]Memory file: {memory.path.resolve()}[/]")


@cli.group()
def memory() -> None:
    """Edit what the agent remembers (overrides, locked/banned players, notes)."""


def _load_players(ctx) -> pd.DataFrame:
    store = FPLStore(db_path=ctx.obj["db"])
    try:
        players = store.players_df()
        teams = store.teams_df()
    finally:
        store.close()
    if players.empty:
        raise click.ClickException("No player data cached. Run `recommend` or `refresh` first.")
    return players.merge(teams[["id", "short_name"]].rename(columns={"id": "team_id"}),
                         on="team_id", how="left")

def find_player(players: pd.DataFrame, query: str) -> tuple[int, str]:
    return engine.find_player(players, query)


def _planning_gw(mem: AgentMemory, ctx) -> int:
    gw = mem.data.get("planning_gw")
    if gw:
        return int(gw)
    store = FPLStore(db_path=ctx.obj["db"])
    try:
        return store.current_gameweek() + 1
    finally:
        store.close()


@memory.command("set-ft")
@click.argument("count", type=click.IntRange(0, 5))
@click.option("--reason", default="", help="Why (e.g. 'made 1 transfer already').")
@click.pass_context
def memory_set_ft(ctx, count: int, reason: str) -> None:
    """Remember free transfers for the next deadline (expires after it)."""
    mem = AgentMemory(ctx.obj["memory"])
    gw = _planning_gw(mem, ctx)
    mem.set_override("free_transfers", count, gw, reason)
    mem.save()
    console.print(f"Free transfers for GW{gw} set to {count}.")


@memory.command("set-bank")
@click.argument("amount", type=float)
@click.option("--reason", default="")
@click.pass_context
def memory_set_bank(ctx, amount: float, reason: str) -> None:
    """Remember the bank (in £m) for the next deadline (expires after it)."""
    mem = AgentMemory(ctx.obj["memory"])
    gw = _planning_gw(mem, ctx)
    mem.set_override("bank", int(round(amount * 10)), gw, reason)
    mem.save()
    console.print(f"Bank for GW{gw} set to £{amount:.1f}m.")


@memory.command("clear-overrides")
@click.pass_context
def memory_clear_overrides(ctx) -> None:
    """Forget free-transfer and bank overrides."""
    mem = AgentMemory(ctx.obj["memory"])
    mem.clear_overrides()
    mem.save()
    console.print("Overrides cleared.")


@memory.command("lock")
@click.argument("players", nargs=-1, required=True)
@click.pass_context
def memory_lock(ctx, players: tuple[str, ...]) -> None:
    """Keep (or force-buy) these players in every plan."""
    _set_pref(ctx, players, "lock")


@memory.command("ban")
@click.argument("players", nargs=-1, required=True)
@click.pass_context
def memory_ban(ctx, players: tuple[str, ...]) -> None:
    """Never buy these players (and sell them if owned)."""
    _set_pref(ctx, players, "ban")


@memory.command("unlock")
@click.argument("players", nargs=-1, required=True)
@click.pass_context
def memory_unlock(ctx, players: tuple[str, ...]) -> None:
    """Remove players from the locked/banned lists."""
    _set_pref(ctx, players, "unlock")


def _set_pref(ctx, queries: tuple[str, ...], action: str) -> None:
    mem = AgentMemory(ctx.obj["memory"])
    players = _load_players(ctx)
    for q in queries:
        pid, name = find_player(players, q)
        if action == "lock":
            mem.lock(pid, name)
            console.print(f"Locked {name}.")
        elif action == "ban":
            mem.ban(pid, name)
            console.print(f"Banned {name}.")
        else:
            console.print(f"{'Removed' if mem.unlock(pid) else 'No preference for'} {name}.")
    mem.save()


@memory.command("note")
@click.argument("text", required=False)
@click.option("--remove", type=int, default=None, help="Delete note by number (see `status`).")
@click.pass_context
def memory_note(ctx, text: str | None, remove: int | None) -> None:
    """Add a free-text note (e.g. 'Saving Free Hit for the GW blank')."""
    mem = AgentMemory(ctx.obj["memory"])
    if remove is not None:
        try:
            gone = mem.remove_note(remove)
        except IndexError:
            raise click.ClickException(f"No note {remove}.")
        console.print(f"Removed: {gone['text']}")
    elif text:
        mem.add_note(text)
        console.print("Noted.")
    else:
        raise click.UsageError("Give note text or --remove N.")
    mem.save()


@memory.command("show")
@click.pass_context
def memory_show(ctx) -> None:
    """Same as `status` (no sync)."""
    _print_memory(AgentMemory(ctx.obj["memory"]))


# -- backtest -----------------------------------------------------------------

@cli.command()
@click.option("--horizon", type=click.IntRange(1, 6), default=3, show_default=True)
@click.option("--windows", type=click.IntRange(1, 20), default=4, show_default=True,
              help="Number of past cutoffs to test.")
@click.pass_context
def backtest(ctx: click.Context, horizon: int, windows: int) -> None:
    """Measure forecast accuracy on gameweeks already played."""
    store = FPLStore(db_path=ctx.obj["db"])
    try:
        players, history = store.players_df(), store.player_history_df()
        fixtures, teams = store.fixtures_df(), store.teams_df()
        scoring, gw = store.scoring_rules(), store.current_gameweek()
    finally:
        store.close()
    if history.empty:
        raise click.ClickException("No history cached. Run `refresh` first.")
    last_done = gw - 1 if not fixtures[fixtures["event"] == gw]["finished"].fillna(0).all() else gw
    cutoffs = [c for c in range(last_done - horizon - windows + 1, last_done - horizon + 1) if c >= 3]
    if not cutoffs:
        raise click.ClickException("Not enough completed gameweeks to backtest yet.")
    with console.status("Backtesting…"):
        res = run_backtest(players, history, fixtures, teams, scoring, cutoffs, horizon)
    t = Table(title=f"Backtest: cutoffs GW{cutoffs[0]}–{cutoffs[-1]}, predicting {horizon} GWs ahead")
    for col in res.columns:
        t.add_column(col)
    for r in res.itertuples(index=False):
        t.add_row(*[str(v) for v in r])
    console.print(t)
    if not res.empty:
        m = res.set_index("model")
        mae_m, mae_b = m.at["xpts", "mae"], m.at["ppg_baseline", "mae"]
        top = [c for c in res.columns if c.startswith("top")][0]
        console.print(
            f"Typical miss: [bold]{mae_m:.1f}[/] pts per player-week vs {mae_b:.1f} for "
            f"'each player scores his average so far'. The model's top picks really scored "
            f"[bold]{m.at['xpts', top]:.1f}[/] pts each vs {m.at['ppg_baseline', top]:.1f}.")
    console.print("[dim]Lower MAE and higher correlation are better. topN_actual_avg is the real "
                  "average score of the model's top picks each gameweek.[/]")

# -- ui -----------------------------------------------------------------------

@cli.command()
@click.option("--port", type=int, default=8501, show_default=True)
@click.pass_context
def ui(ctx: click.Context, port: int) -> None:
    """Open the dashboard (suggestions, team, players, fixtures, memory)."""
    app = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    env = {**os.environ, "FPL_DB": ctx.obj["db"], "FPL_MEMORY": ctx.obj["memory"]}
    # Headless skips Streamlit's first-run email prompt, which blocks (or exits
    # without a TTY); open the browser ourselves once the server answers.
    cmd = [sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port),
           "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    url = f"http://localhost:{port}"

    def open_when_ready() -> None:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{url}/_stcore/health", timeout=1)
                webbrowser.open(url)
                return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        subprocess.run(cmd, env=env, check=False)
    except KeyboardInterrupt:
        pass


# -- Standalone runner --------------------------------------------------------

if __name__ == "__main__":
    cli()
