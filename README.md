# FPL Agent AI

A Fantasy Premier League planner: it pulls FPL data, forecasts expected points from underlying stats, optimises transfers, lineup, captain and chips, and shows the results in a local dashboard or the terminal. It never touches your FPL account; you make the moves yourself.

## Architecture

```
fpl_agent/
├── data_ingest/      # FPL API client, JSON→DataFrame normalisation, SQLite storage
├── forecast/         # xPts model (minutes, xG/xA, DC, team ratings) + backtest
├── optimizer/        # Mixed-Integer Linear Program (MILP) via PuLP
├── planner/          # Recommendation assembly: transfers, lineup, captain, rationale
├── engine.py         # sync → forecast → optimise; shared by CLI and dashboard
├── league.py         # mini-league standings, rivals' squads/chips, effective ownership, head-to-head
├── memory.py         # persistent memory of your team, transfers, chips, preferences
├── ui/app.py         # Streamlit dashboard
└── cli/              # Click-based command-line interface with Rich output
```

## Quick start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The team ID defaults to 7588693 (`DEFAULT_MANAGER_ID` in `fpl_agent/engine.py`); set `FPL_MANAGER_ID` in `.env` to use another (see `.env.example`).

#### Logging in (optional, recommended)

Without a login the agent rebuilds free transfers and selling prices from
public data and can't see transfers you've already made this gameweek. FPL
moved sign-in to `account.premierleague.com`, which blocks scripted
email/password logins, so the agent uses the token your browser already has:

1. Log in at <https://fantasy.premierleague.com>.
2. Open DevTools → **Application** → **Local Storage** → `https://fantasy.premierleague.com`.
3. Click the key starting with `oidc.user:` and copy its whole value (or run
   `copy(localStorage[Object.keys(localStorage).find(k => k.startsWith('oidc.user:'))])`
   in the Console).
4. Paste it into `.env` in single quotes: `FPL_REFRESH_TOKEN='{"id_token":...}'`.

The token rotates on every use. The agent saves the newest one to
`.fpl_auth.json` (git-ignored, readable only by you), so you paste it once.
Paste a fresh one if it expires (around 30 days unused) or after logging out
everywhere. Using it may sign your browser out of FPL; log in there again.

### 2. Open the dashboard

```bash
python fpl_agent.py ui            # opens http://localhost:8501
```

| Tab | What it shows |
|---|---|
| **Suggestions** | Projected points, gain vs. no transfers, recommended transfers with close-call alternatives, XI + bench with the stats behind each pick, captain/vice, chip outlook, per-GW plan |
| **League** | Mini-league standings, rivals' captains and chips, you vs a rival (gap, expected edge, rough chance to finish above, differentials), league effective ownership |
| **My team** | Squad with purchase/selling prices and xPts, chip status by window, mini-league ranks, saved plans |
| **Players** | Every player's forecast: filter by position, team, price, minutes; xG/90, xA/90, share of team xG, finishing form, DC%, CS%, xPts per GW, xPts/£m, league EO |
| **Fixtures** | Team × GW grid coloured by expected goals or clean-sheet chance from the model's team ratings; ratings and recent form |
| **Memory** | Free-transfer/bank overrides, locked and banned players, notes (same file the CLI uses) |
| **Model check** | Walk-forward backtest vs. a points-per-game baseline |

The sidebar sets horizon, Wildcard/Free Hit (only if available), one-off free
transfers or bank, and how cautious transfers should be. Changing options
re-solves from cached data without calling the API again; **Refresh from FPL**
re-syncs.

### 3. Or use the terminal

```bash
python fpl_agent.py recommend --manager-id 7588693
```

Every run refreshes players and fixtures, re-fetches per-match history when the
cache is older than 6 hours, syncs your setup into memory, and prints:

- transfers with xPts gain for next GW and over the horizon
- the next-GW XI and bench with the stats behind each pick (opponent, expected
  minutes, xG/90, xA/90, defensive-contribution %, clean-sheet %)
- captain, vice, projected points, and the gain compared with making no transfers
- a **chip outlook**: double/blank gameweeks, and the best gameweek for each
  available chip within its window, with expiry warnings

Useful options:

| Option | Meaning |
|--------|---------|
| `--horizon 6` | Gameweeks to plan over |
| `--wildcard` / `--free-hit` | Plan with that chip active (checked against your available chips) |
| `--free-transfers N` / `--bank 1.5` | One-off overrides (use `memory set-ft` to persist) |
| `--ft-value 1.0` | Points a saved free transfer is worth (raise it to make fewer, surer moves) |
| `--bench-weight 0.1` | How much bench players' EP counts |

### 4. Agent memory

The agent keeps a persistent memory of your setup in `fpl_memory.json`
(readable JSON, gitignored; set `FPL_MEMORY` to move it). It survives cache
rebuilds and is updated on every `recommend`, or with `status --sync`.

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

The dashboard's **League** tab shows the same, plus who owns what in your league
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
| `api_client.py` | HTTP wrapper for public (`/bootstrap-static/`, `/fixtures/`, `/element-summary/{id}/`) and authenticated (`/my-team/{id}/`, `/entry/{id}/transfers/`) FPL endpoints. |
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
| `FPL_REFRESH_TOKEN` | FPL login token from your browser (alternative to `--refresh-token`; see Logging in) |
| `FPL_AUTH_FILE` | Where the rotated token is kept (default `.fpl_auth.json`) |
| `FPL_MANAGER_ID` | Your FPL manager ID (default 7588693) |
| `FPL_DB` | SQLite cache path (rebuilt automatically on a new season or schema change) |
| `FPL_MEMORY` | Agent memory file (default `fpl_memory.json`) |
| `FPL_LEAGUE_ID` | Mini-league to track (default: your first private classic league) |
| `FPL_FREE_TRANSFERS`, `FPL_BANK` | Optional overrides; normally read from the API |

## License

MIT
