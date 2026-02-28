"""CLI entry-point for the FPL Agent.

All options read from a .env file (or exported environment variables)
so you can simply run:

    python fpl_agent.py refresh
    python fpl_agent.py recommend
    python fpl_agent.py apply

Command-line flags still override .env values when supplied explicitly.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fpl_agent.data_ingest import FPLClient, FPLStore
from fpl_agent.forecast import ExpectedPointsModel
from fpl_agent.optimizer import optimize
from fpl_agent.optimizer.milp import TeamState
from fpl_agent.planner import build_recommendation

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

console = Console()
logger = logging.getLogger("fpl_agent")


@click.group()
@click.option("--db", envvar="FPL_DB", default="fpl_agent.db", show_default=True,
              help="Path to SQLite database.")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, db: str, verbose: bool) -> None:
    """FPL Agent AI – agentic Fantasy Premier League assistant."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    ctx.ensure_object(dict)
    ctx.obj["db"] = db


# -- refresh ------------------------------------------------------------------

@cli.command()
@click.option("--top-n", envvar="FPL_TOP_N", type=int, default=300, show_default=True,
              help="Number of players to fetch history for.")
@click.pass_context
def refresh(ctx: click.Context, top_n: int) -> None:
    """Pull latest data from the FPL API and store in SQLite."""
    store = FPLStore(db_path=ctx.obj["db"])
    console.print("[bold cyan]Refreshing bootstrap & fixtures…[/]")
    store.refresh_all()
    console.print(f"[bold cyan]Fetching player history (top {top_n})…[/]")
    store.refresh_all_player_histories(top_n=top_n)
    store.close()
    console.print("[bold green]Data refresh complete.[/]")


# -- recommend ----------------------------------------------------------------

@cli.command()
@click.option("--manager-id", envvar="FPL_MANAGER_ID", type=int, required=True,
              help="FPL manager ID.")
@click.option("--email", envvar="FPL_EMAIL", default=None,
              help="FPL login email.")
@click.option("--password", envvar="FPL_PASSWORD", default=None,
              help="FPL login password.")
@click.option("--horizon", envvar="FPL_HORIZON", type=int, default=6, show_default=True,
              help="Forecast horizon in gameweeks.")
@click.option("--free-transfers", envvar="FPL_FREE_TRANSFERS", type=int, default=1,
              show_default=True, help="Available free transfers.")
@click.option("--bank", envvar="FPL_BANK", type=float, default=0.0, show_default=True,
              help="Bank balance in £m (e.g. 1.5 for £1.5m).")
@click.pass_context
def recommend(
    ctx: click.Context,
    manager_id: int,
    email: str | None,
    password: str | None,
    horizon: int,
    free_transfers: int,
    bank: float,
) -> None:
    """Generate transfer, lineup, and captain recommendations."""
    db = ctx.obj["db"]
    client = FPLClient()

    # Attempt authenticated login; non-fatal if it fails — public endpoints suffice.
    if email and password:
        try:
            client.login(email, password)
        except Exception as exc:
            console.print(f"[yellow]Auth login failed ({exc}). Using public endpoints.[/]")

    store = FPLStore(client=client, db_path=db)

    if store.players_df().empty:
        console.print("[yellow]No local data. Running refresh first…[/]")
        store.refresh_all()

    # Fetch current squad — falls back to public endpoint automatically.
    try:
        store.refresh_my_team(manager_id)
    except Exception as exc:
        console.print(f"[yellow]Could not fetch your team: {exc}[/]")

    players = store.players_df()
    history = store.player_history_df()
    fixtures = store.fixtures_df()
    teams = store.teams_df()
    your_team = store.your_team_df()
    current_gw = store.current_gameweek()

    if your_team.empty:
        console.print(
            "[red]No team data available. Check your FPL_MANAGER_ID in .env.[/]"
        )
        store.close()
        sys.exit(1)

    current_squad = your_team["player_id"].tolist()
    selling_prices = dict(zip(your_team["player_id"], your_team["selling_price"]))

    # Auto-fetch bank from API if the user left it at the default 0.
    bank_int = int(round(bank * 10))
    if bank_int == 0:
        api_bank = store.get_manager_bank(manager_id)
        if api_bank is not None:
            bank_int = int(api_bank)
            console.print(f"[dim]Bank auto-detected from API: £{bank_int / 10:.1f}m[/]")

    team_state = TeamState(
        current_squad=current_squad,
        selling_prices=selling_prices,
        bank=bank_int,
        free_transfers=free_transfers,
    )

    console.print(f"[bold cyan]Forecasting over {horizon} gameweeks from GW{current_gw}…[/]")
    model = ExpectedPointsModel(
        players=players,
        history=history,
        fixtures=fixtures,
        teams=teams,
        current_gw=current_gw,
        horizon=horizon,
    )
    forecast = model.predict()

    console.print("[bold cyan]Running optimiser…[/]")
    opt_result = optimize(team_state, forecast, players, horizon=horizon)

    rec = build_recommendation(opt_result, players, forecast, current_squad, selling_prices)

    _print_recommendation(rec, players, forecast)
    store.close()


def _print_recommendation(rec, players, forecast) -> None:
    """Pretty-print the recommendation using Rich."""
    pid_to_name = dict(zip(players["id"], players["web_name"]))
    pid_to_ep = dict(zip(forecast["player_id"], forecast["total_expected_points"]))
    pid_to_pos = dict(zip(players["id"], players["element_type"]))
    pos_map = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

    if rec.transfers:
        t_table = Table(title="Recommended Transfers", show_lines=True)
        t_table.add_column("Pos", style="bold")
        t_table.add_column("OUT", style="red")
        t_table.add_column("Price", justify="right")
        t_table.add_column("IN", style="green")
        t_table.add_column("Price", justify="right")
        for t in rec.transfers:
            t_table.add_row(
                t.position, t.sell_name, f"£{t.sell_price:.1f}m",
                t.buy_name, f"£{t.buy_price:.1f}m",
            )
        console.print(t_table)
    else:
        console.print("[green]No transfers recommended.[/]")

    xi_table = Table(title="Starting XI", show_lines=True)
    xi_table.add_column("Pos")
    xi_table.add_column("Player")
    xi_table.add_column("EP", justify="right")
    xi_table.add_column("Role")

    for pid in rec.starting_xi:
        pos = pos_map.get(pid_to_pos.get(pid, 0), "?")
        name = pid_to_name.get(pid, str(pid))
        ep = pid_to_ep.get(pid, 0)
        role = ""
        if pid == rec.captain_id:
            role = "© Captain"
        elif pid == rec.vice_captain_id:
            role = "VC"
        xi_table.add_row(pos, name, f"{ep:.1f}", role)
    console.print(xi_table)

    bench_names = [pid_to_name.get(pid, str(pid)) for pid in rec.bench_order]
    console.print(f"[dim]Bench order: {', '.join(bench_names)}[/]")

    console.print(
        Panel(
            f"Expected points delta: [bold]{rec.expected_points_delta:+.1f}[/]\n"
            f"Transfer hits: {rec.transfer_cost} pts",
            title="Summary",
        )
    )

    console.print(Panel(rec.rationale, title="Rationale", border_style="blue"))


# -- apply (browser automation) -----------------------------------------------

@cli.command()
@click.option("--manager-id", envvar="FPL_MANAGER_ID", type=int, required=True,
              help="FPL manager ID.")
@click.option("--email", envvar="FPL_EMAIL", required=True,
              help="FPL login email.")
@click.option("--password", envvar="FPL_PASSWORD", required=True,
              help="FPL login password.")
@click.option("--headless/--no-headless", envvar="FPL_HEADLESS", default=True,
              help="Run browser in headless mode.")
@click.option("--horizon", envvar="FPL_HORIZON", type=int, default=6, show_default=True,
              help="Forecast horizon in gameweeks.")
@click.option("--free-transfers", envvar="FPL_FREE_TRANSFERS", type=int, default=1,
              show_default=True, help="Available free transfers.")
@click.option("--bank", envvar="FPL_BANK", type=float, default=0.0, show_default=True,
              help="Bank balance in £m (e.g. 1.5 for £1.5m).")
@click.pass_context
def apply(
    ctx: click.Context,
    manager_id: int,
    email: str,
    password: str,
    headless: bool,
    horizon: int,
    free_transfers: int,
    bank: float,
) -> None:
    """Apply the recommendation to the FPL website via browser automation."""
    from fpl_agent.browser_exec import FPLBrowserExecutor

    db = ctx.obj["db"]
    client = FPLClient()

    if email and password:
        try:
            client.login(email, password)
        except Exception as exc:
            console.print(f"[yellow]Auth login failed ({exc}). Using public endpoints for data.[/]")

    store = FPLStore(client=client, db_path=db)

    if store.players_df().empty:
        store.refresh_all()

    try:
        store.refresh_my_team(manager_id)
    except Exception as exc:
        console.print(f"[yellow]Could not fetch your team: {exc}[/]")

    players = store.players_df()
    history = store.player_history_df()
    fixtures = store.fixtures_df()
    teams = store.teams_df()
    your_team = store.your_team_df()
    current_gw = store.current_gameweek()

    current_squad = your_team["player_id"].tolist()
    selling_prices = dict(zip(your_team["player_id"], your_team["selling_price"]))

    bank_int = int(round(bank * 10))
    if bank_int == 0:
        api_bank = store.get_manager_bank(manager_id)
        if api_bank is not None:
            bank_int = int(api_bank)

    team_state = TeamState(
        current_squad=current_squad,
        selling_prices=selling_prices,
        bank=bank_int,
        free_transfers=free_transfers,
    )

    model = ExpectedPointsModel(
        players=players, history=history, fixtures=fixtures,
        teams=teams, current_gw=current_gw, horizon=horizon,
    )
    forecast = model.predict()
    opt_result = optimize(team_state, forecast, players, horizon=horizon)
    rec = build_recommendation(opt_result, players, forecast, current_squad, selling_prices)

    console.print("[bold cyan]Launching browser automation…[/]")
    executor = FPLBrowserExecutor(email, password, headless=headless)
    results = executor.execute(rec)

    for r in results:
        status = "[green]OK[/]" if r.success else "[red]FAIL[/]"
        console.print(f"  {status} {r.step}: {r.message}")

    store.close()


# -- Standalone runner --------------------------------------------------------

if __name__ == "__main__":
    cli()
