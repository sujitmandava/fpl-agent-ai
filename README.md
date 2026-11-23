# FPL Agent AI

A Fantasy Premier League planner: it pulls FPL data, forecasts expected points from underlying stats, optimises transfers, lineup, captain and chips, and shows the results in a web app or the terminal. Anyone can use it: enter an FPL team ID and it plans from FPL's public data. No login, and it never touches your FPL account; you make the moves yourself.

## Architecture

```
fpl_agent/
├── data_ingest/      # FPL API client, JSON→DataFrame normalisation, SQLite storage
├── forecast/         # xPts model (minutes, xG/xA, DC, team ratings) + backtest
├── optimizer/        # Mixed-Integer Linear Program (MILP) via PuLP
├── planner/          # Recommendation assembly: transfers, lineup, captain, rationale
├── engine.py         # sync → forecast → optimise; shared by CLI and API
├── league.py         # mini-league standings, rivals' squads/chips, effective ownership, head-to-head
├── memory.py         # persistent memory of your team, transfers, chips, preferences
├── api.py            # JSON API for the web app (FastAPI)
└── cli/              # Click-based command-line interface with Rich output
```

## Quick start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

You need an FPL team ID. It's the number in your Points page link:
`fantasy.premierleague.com/entry/<ID>/event/…`. Everything comes from FPL's
public API, so no login is needed. Public data can't see transfers you've
already made for the next deadline; if you've made some, set your free
transfers and bank in the Memory tab (or `memory set-ft` / `memory set-bank`).

### 2. Run the web app (new)

The web app in `web/` is the product being built for others to use: a landing
page where anyone enters their team ID, and a phone-first Plan screen that
draws your moves on a tactics board against your mini-league rival. It talks
to the planning engine through a small JSON API.

```bash
python fpl_agent.py api              # JSON API on http://127.0.0.1:8000
cd web && pnpm install && pnpm dev   # web app on http://localhost:3000
```

The web app proxies `/api/*` to `FPL_API_URL` (default `http://127.0.0.1:8000`).
Settings such as locked and banned players stay in the visitor's browser and
are sent with each request. Plan is built in full; League, Squad, Players and
More aren't built yet; the terminal covers most of them meanwhile.

| Endpoint | Returns |
|---|---|
| `GET /api/team/{id}/plan` | The full plan as JSON. Query: `horizon`, `chip` (`none`/`wildcard`/`freehit`), `free_transfers`, `bank`, `ft_value`, `bench_weight`, `consistency`, `league`, `rival`, `locked`, `banned` (comma-separated ids), `fresh` |
| `GET /api/model-check` | Backtest summary against the points-per-game baseline |

### 3. Or use the terminal

```bash
python fpl_agent.py recommend --manager-id 1234567   # or -m; or set FPL_MANAGER_ID
```

Every run refreshes players and fixtures, re-fetches per-match history when the
cache is older than 6 hours, syncs your setup into memory, and prints:

- transfers with xPts gain for next GW and over the horizon
- the next-GW XI and bench with the stats behind each pick (opponent, expected
  minutes, xG/90, xA/90, defensive-contribution %, clean-sheet %)
- captain, vice, projected points, and the gain compared with making no transfers
- a **chip plan**: every chip left in the current window (GW1–19, then
  GW20–38) gets its own week before it expires, since unused chips are lost
  and only one can be played per gameweek. It looks ahead to the window's end
  (up to 8 GWs), not just your horizon. A Free Hit is pure one-week points
  (no locks, bans or preferences). A Wildcard squad is built for a 5-week haul
  and credited with the hits it avoids and the free transfers it keeps. A Bench
  Boost, Triple Captain or Free Hit later in that haul is valued on the
  rebuilt squad

Useful options:

| Option | Meaning |
|--------|---------|
| `--horizon 6` | Gameweeks to plan over |
| `--wildcard` / `--free-hit` | Plan with that chip active (checked against your available chips) |
| `--free-transfers N` / `--bank 1.5` | One-off overrides (use `memory set-ft` to persist) |
| `--ft-value 1.0` | Points a saved free transfer is worth (raise it to make fewer, surer moves) |
| `--bench-weight 0.1` | How much bench players' EP counts |

### 4. Agent memory

The agent keeps a persistent memory of each team in `memory/<team id>.json`
(readable JSON, gitignored; set `FPL_MEMORY_DIR` to move the folder). It
survives cache rebuilds and is updated on every `recommend`, or with
`status --sync`. There's no login, so on a shared server anyone who opens a
team ID can see and change that team's memory.

The examples below assume `FPL_MANAGER_ID` is set; otherwise add `-m <ID>`
(for `memory`, before the subcommand: `memory -m 1234567 lock Haaland`).

```bash
python fpl_agent.py status                 # team, free transfers, bank, chips, notes, leagues
python fpl_agent.py status --sync          # refresh from the API first

python fpl_agent.py memory set-ft 4 --reason "made 1 transfer already"   # until the deadline passes
python fpl_agent.py memory set-bank 0.5
python fpl_agent.py memory lock Haaland    # always keep / must buy
python fpl_agent.py memory ban "Le Fee"    # never buy (sell if owned); accents optional
python fpl_agent.py memory unlock Haaland
python fpl_agent.py memory note "Saving Free Hit for the GW blank"
python fpl_agent.py memory clear-overrides
```

Precedence: command-line flag → memory override → value from the API.
Overrides are tied to the next deadline and expire after it. If the FPL API
is unreachable, the agent plans from the last snapshot in memory. Chips are
tracked per window (GW1–19 / GW20–38) with played / available / expired status.

### 5. Your mini-league

```bash
python fpl_agent.py league                 # standings, rivals' captains and chips, you vs the leader
python fpl_agent.py league --rival "isak"  # compare with someone else
```

The web app's **League** screen shows the same, plus who owns what in your league
(effective ownership counts captains double) and the differentials on each side.
League effective ownership also appears next to close-call transfer options.

### 6. Check the model

```bash
python fpl_agent.py backtest               # walk-forward accuracy on played gameweeks
python fpl_agent.py hypotheses             # re-test open hypotheses; run after each gameweek
```

## Modules

### `data_ingest`

| Component | Purpose |
|-----------|---------|
| `api_client.py` | HTTP wrapper for the public FPL endpoints (`/bootstrap-static/`, `/fixtures/`, `/element-summary/{id}/`, `/entry/{id}/…`). |
| `models.py` | SQLite schema (tables: `players`, `teams`, `fixtures`, `player_history`, `gameweeks`, `your_team`). |
| `store.py` | Fetch → normalise → upsert orchestration with pandas. |

### `forecast`

`ExpectedPointsModel` predicts expected points (xPts) per player per fixture, scored with the season's rules from the API (`game_config.scoring`):

| Component | Source |
|-----------|--------|
| Appearance | P(play), P(60+ mins), expected minutes from recent team matches |
| Goals, assists | Role: share of the team's xG/xA while on the pitch (recency-weighted, shrunk toward position average) × team's expected goals in the fixture; plus 15% of recent finishing above/below xG |
| Clean sheet, goals conceded | Negative binomial on goals expected against, from team ratings (calibrated; Poisson under-predicted clean sheets) |
| Defensive contribution | Rate of hitting the DC threshold in 60+ min games, detected by rebuilding each match's points from the scoring rules |
| Saves (GK), bonus, yellow cards | Per-90 rates, adjusted for fixture |
| Availability | `chance_of_playing_next_round`, fading over 4 GWs; departed players 0 |

`team_ratings.py` fits attack/defence ratings per team from a 70/30 blend of xG and goals, weighting recent matches more ("team form"), adjusting for opponent strength, and using FPL's team strength numbers as the early-season prior. Blank gameweeks score 0; double gameweeks sum both fixtures.

`backtest.py` runs a walk-forward check against a points-per-game baseline.

**[docs/MODEL.md](docs/MODEL.md)** explains every stat, which points it feeds, where it lives in the code, and the latest backtest results.

### `optimizer`

Solves a MILP with PuLP that picks the squad, a starting XI and a captain for every gameweek in the horizon:
- **Objective:** discounted Σ (XI points + captain points + 0.1 × bench points) − 4 × hits − value of free transfers used.
- **Constraints:** 15 players, 2/5/5/3, ≤3 per club, budget (selling prices for kept players), and a valid formation every gameweek.
- Raises `OptimizationError` if the solver doesn't reach an optimal solution.

### `planner`

`build_recommendation()` converts raw optimizer output into:
- Transfer list (sell/buy with prices), with **close calls**: near-equal alternatives within ~1 xPt over the horizon that you could afford instead
- Starting XI / bench / bench order
- Captain & vice-captain
- Expected-points delta and text rationale

## Running tests

```bash
pytest -v
```

Tests cover:
- API client responses (mocked HTTP)
- SQLite schema creation and idempotent upserts
- Forecast output shape, injury penalties, fixture boosts
- Optimizer constraint satisfaction (squad size, positions, budget, club limits)

## Environment variables

| Variable | Description |
|----------|-------------|
| `FPL_MANAGER_ID` | Optional team ID so the CLI doesn't need `--manager-id` |
| `FPL_DB` | SQLite cache path (rebuilt automatically on a new season or schema change) |
| `FPL_MEMORY_DIR` | Folder for per-team memory files (default `memory/`) |
| `FPL_LEAGUE_ID` | Mini-league to track (default: your first private classic league) |
| `FPL_FREE_TRANSFERS`, `FPL_BANK` | Optional overrides; normally read from the API |

## License

MIT
