# FPL Agent AI

An agentic workflow that automates **data ingestion, forecasting, squad optimisation, and decision execution** for Fantasy Premier League.

## Architecture

```
fpl_agent/
├── data_ingest/      # FPL API client, JSON→DataFrame normalisation, SQLite storage
├── forecast/         # Expected-points model (weighted form + fixture difficulty)
├── optimizer/        # Mixed-Integer Linear Program (MILP) via PuLP
├── planner/          # Recommendation assembly: transfers, lineup, captain, rationale
├── cli/              # Click-based command-line interface with Rich output
└── browser_exec/     # Playwright automation to apply recommendations on the FPL website
```

## Quick start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# For browser automation only:
playwright install chromium
```

### 2. Pull latest data

```bash
python fpl_agent.py refresh
```

This fetches the bootstrap-static payload, all fixtures, and per-match history for the top 300 players, then stores everything in `fpl_agent.db` (SQLite).

### 3. Generate recommendations

```bash
python fpl_agent.py recommend \
  --manager-id 123456 \
  --email you@example.com \
  --password yourpassword \
  --horizon 6 \
  --free-transfers 1 \
  --bank 15
```

**Output includes:**

- Recommended transfers (sell/buy with prices)
- Starting XI and bench order
- Captain & vice-captain pick
- Expected-points delta
- Natural-language rationale

> **Tip:** Set `FPL_EMAIL` and `FPL_PASSWORD` environment variables to avoid passing credentials on the command line.

### 4. Apply via browser (optional)

```bash
python fpl_agent.py apply \
  --manager-id 123456 \
  --email you@example.com \
  --password yourpassword \
  --no-headless
```

This launches a Chromium browser, logs into the FPL site, makes the recommended transfers, sets the lineup, and confirms.

## Modules

### `data_ingest`

| Component | Purpose |
|-----------|---------|
| `api_client.py` | HTTP wrapper for public (`/bootstrap-static/`, `/fixtures/`, `/element-summary/{id}/`) and authenticated (`/my-team/{id}/`, `/entry/{id}/transfers/`) FPL endpoints. |
| `models.py` | SQLite schema (tables: `players`, `teams`, `fixtures`, `player_history`, `gameweeks`, `your_team`). |
| `store.py` | Fetch → normalise → upsert orchestration with pandas. |

### `forecast`

`ExpectedPointsModel` produces a DataFrame with columns `player_id, expected_points_gw9, …, expected_points_gw14, total_expected_points, variance`.

Approach:
1. Exponentially-weighted moving average of recent per-GW points.
2. Fixture-difficulty adjustment (FDR-based multiplier).
3. Availability penalty (`chance_of_playing_next_round`).

### `optimizer`

Solves a MILP with PuLP:
- **Objective:** maximise total expected points minus transfer-hit costs.
- **Constraints:** 15 players, 2 GK / 5 DEF / 5 MID / 3 FWD, budget cap, max 3 per club, transfer-balance linking.

### `planner`

`build_recommendation()` converts raw optimizer output into:
- Transfer list (sell/buy with prices)
- Starting XI / bench / bench order
- Captain & vice-captain
- Expected-points delta and text rationale

### `browser_exec`

Playwright automation that:
1. Logs in to the FPL website.
2. Executes transfers on the Transfers page.
3. Sets lineup on the Pick Team page.
4. Verifies each step and returns a list of `StepResult` objects.

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
| `FPL_EMAIL` | FPL account email (alternative to `--email`) |
| `FPL_PASSWORD` | FPL account password (alternative to `--password`) |

## License

MIT
