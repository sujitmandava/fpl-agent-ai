# How the model works

This is the reference for what every number in the agent means, which stat
feeds which kind of points, and where in the code each piece lives. It is
written so you can change one part without having to reverse-engineer the
rest.

The pipeline has four stages:

```
FPL API ──► data_ingest ──► forecast ──────────────► optimizer ──► planner ──► CLI / dashboard
            (SQLite)        team ratings              (MILP)       (rationale,       ▲
                            player profiles                         close calls)     │
                            points per fixture                                       │
                                                              league (rivals) ───────┘
```

1. **Team ratings**: how good each team is at scoring and at not conceding.
2. **Player profiles**: each player's habits (minutes, role, defending, bonus…).
3. **Points per fixture**: habits × fixture, one scoring rule at a time.
4. **Optimiser and league layer**: turn xPts into a squad, then show how that
   squad compares with your rivals'.

---

## 1. Inputs

Everything comes from the official FPL API and is cached in `fpl_agent.db`.

| Table | From | Used for |
|---|---|---|
| `players` | `/bootstrap-static/` | position, team, price, injury flag (`chance_of_playing_next_round`), overall ownership |
| `teams` | `/bootstrap-static/` | FPL's own team strength numbers (early-season prior only) |
| `fixtures` | `/fixtures/` | results, home/away, upcoming opponents, blanks and doubles |
| `player_history` | `/element-summary/{id}/` | **one row per player per match**: minutes, goals, assists, xG, xA, saves, bonus, cards, goals conceded, total points |
| `meta.scoring` | `game_config.scoring` | points per action for this season (e.g. a GK goal = 10) |

Only the **current season** is used. Nothing from past seasons enters the
forecast.

---

## 2. Team ratings (`forecast/team_ratings.py`)

Each team gets two numbers, both scaled so 1.00 is league average:

* **Attack** (`att`): higher means it scores more.
* **Defence** (`dfn`): lower means it concedes less.

Expected goals in a fixture:

```
goals for     λ_for     = μ · att[team] · dfn[opponent] · home factor
goals against λ_against = μ · att[opponent] · dfn[team] / home factor
```

| Stat | Role |
|---|---|
| Team xG per match (sum of players' xG) | 70% of each match's "goals" observation (`XG_WEIGHT`) |
| Actual goals | the other 30% |
| Match date | recent matches count more: ×0.92 per gameweek of age (`DECAY`) |
| Opponent | ratings are solved together, so scoring 3 against a bad defence counts for less |
| FPL team strength | prior worth 4 matches (`PRIOR_MATCHES`); matters only early in the season |
| μ, home factor | league average goals per team-match and home advantage, from this season |

**Feeds:** every goal, assist, clean sheet, goals-conceded and save number below.

*Checked:* using 100% xG was very slightly better than 70% in the walk-forward
test (log-loss 0.6049 vs 0.6067), and changing the recency weight made almost
no difference. Both are within noise after 10 gameweeks, so the defaults stay
until there is more data.

---

## 3. Player profiles (`ExpectedPointsModel.player_profiles`)

Each player's habits, from his own match rows this season.

### Common tools

* **Recency weight.** Rates weight each match by 0.92 per gameweek of age
  (`RATE_DECAY`, half-life about 8 GWs).
* **Shrinkage.** Rates are pulled toward the position average among regulars
  (900+ minutes). The pull is worth 270 minutes of play (`SHRINK_MINUTES`), so a
  player with 90 minutes is mostly "average", and one with 900 is mostly
  himself. The prior is discounted 15% (`PRIOR_DISCOUNT`) because fringe players
  are usually worse than regulars.

### What is measured, and what it is for

| Profile value | Built from | Feeds |
|---|---|---|
| `p_play`, `p60`, `exp_minutes` | minutes in the team's last 6 matches, weighted 0.8 per match back (`MINUTES_WINDOW`, `MINUTES_DECAY`) | appearance points; scales everything else; clean sheets need 60+ |
| **`xg_share`** | Σ his xG ÷ Σ (team xG × his minutes/90): his share of the team's chances while he's on the pitch | **goals** |
| **`xa_share`** | the same with xA | **assists** |
| **`finish90`** | recent (goals − xG) per 90, shrunk toward 0 | small adjustment to **goals** |
| `dc_rate` | share of his 60+ minute matches where he earned defensive-contribution points (shrinkage: 4 matches, `SHRINK_MATCHES`) | **DC points** |
| `saves90` | saves per 90 | **save points** (GK) |
| `bonus90` | bonus points per 90 | **bonus** |
| `yc90` | yellow cards per 90 | **card deductions** |
| `xg90`, `xa90` | plain xG/xA per 90 | display only |
| `variance` | variance of his last 8 scores | display only |

**Why role share instead of xG/90.** A player's xG/90 mixes two things: his
role (how much of the team's attack goes through him) and how good the team's
recent opponents were. Share separates them: the role comes from his own
history, and the fixture comes from team ratings. It also notices role changes
sooner (Evanilson went from about 5% to about 38% of Bournemouth's chances
during GW1–8). On accuracy alone it tested about the same as xG/90.

**Finishing.** Over this season's data, about 60% of a player's extra xG
carried into the next three gameweeks, but only 10–15% of his finishing above
xG did. The model carries 15% (`FINISH_WEIGHT`). Raising it to 30% made the
backtest worse.

**Defensive contribution detection.** FPL's history doesn't say directly when
DC points were awarded. The model rebuilds each match's points from every other
rule; the leftover +2 is the DC bonus (`defensive_points_earned`). This works
whatever the thresholds are.

---

## 4. Points per fixture (`ExpectedPointsModel._fixture_points`)

For one player in one fixture, with `frac = exp_minutes / 90`,
`λ_for`/`λ_against` from team ratings, and points per action from the season's
scoring rules:

| Points | Formula | Uses |
|---|---|---|
| Appearance | `p_play × 1 + p60 × (2 − 1)` | minutes |
| Goals | `max(0, xg_share × λ_for × frac + 0.15 × finish90 × frac × att_mult) × pts per goal` | role, finishing form, team attack, opponent defence |
| Assists | `xa_share × λ_for × frac × 3` | role, team attack, opponent defence |
| Clean sheet | `p60 × P(0 conceded) × CS pts` | team defence, opponent attack |
| Goals conceded | `−1 × E[⌊GA/2⌋]` with GA scaled by `frac` (GK/DEF) | team defence, opponent attack |
| Saves (GK) | `E[⌊saves/3⌋]`, saves = `saves90 × frac × (λ_against ÷ team's usual λ_against)` | saves rate, opponent attack |
| Defensive contribution | `dc_rate × p60 × 2` | DC rate, minutes |
| Bonus | `bonus90 × frac × fixture factor`; attackers: √(attack multiplier), GK/DEF: √(CS chance ÷ usual CS chance) | bonus rate, fixture |
| Cards | `yc90 × frac × −1` | card rate |

`att_mult` = how much easier this fixture is to score in than the team's
average fixture.

**Clean sheets use a negative binomial, not Poisson.** `P(0 conceded) =
(k / (k + λ))^k` with `k = 4` (`CS_DISPERSION`). Poisson assumes the team's
true concession rate is known exactly. It isn't, and that uncertainty makes
clean sheets (and heavy defeats) more common than Poisson says. In the
walk-forward test Poisson predicted a 23.8% clean-sheet rate when the real rate
was 28.3%, with weak defences worst (16% predicted, 30% actual). With k = 4 the
average is right, and GK/DEF under-prediction fell from −0.47 to −0.33 points
per player-week. Goals conceded uses the same distribution.

**Per gameweek:** blank = 0, double = sum of both fixtures. Then × availability:
`chance_of_playing_next_round` for the next GW, recovering linearly to 100% over
4 GWs (`RECOVERY_GWS`); players who left the club = 0.

**Players with no minutes this season** fall back to FPL's own `ep_next`.

### Where to change what

| To change… | Edit |
|---|---|
| how much recent form counts | `RATE_DECAY`, `MINUTES_DECAY`, `MINUTES_WINDOW` (`expected_points.py`), `DECAY` (`team_ratings.py`) |
| how fast small samples are trusted | `SHRINK_MINUTES`, `SHRINK_MATCHES`, `PRIOR_DISCOUNT` |
| how much hot finishing is trusted | `FINISH_WEIGHT` |
| clean-sheet odds | `CS_DISPERSION` (lower = more spread; very large = Poisson) |
| xG vs goals for team strength | `XG_WEIGHT` |
| early-season reliance on FPL's strengths | `PRIOR_MATCHES` |
| a new scoring rule | add a line in `_fixture_points` and a profile rate in `player_profiles` |

Always re-run the backtest after a change (`python fpl_agent.py backtest`, or
the dashboard's Model check tab).

---

## 5. Optimiser (`optimizer/milp.py`)

A mixed-integer program chooses the 15-man squad, XI and captain for every
gameweek in the horizon:

```
maximise  Σ_gw 0.85^k · Σ_player xPts · (in XI + is captain + 0.1 × on bench)
          − 4 × hits − ft_value × free transfers used
```

* **0.85 per week** (`DISCOUNT`): later gameweeks are less certain.
* **Bench weight 0.1**: bench points matter a little (auto-subs).
* **ft_value** (default 1): a transfer must be worth more than keeping it in
  the bank; a hit must beat 4 + ft_value.
* **Rules**: budget (selling prices for players you own), 2/5/5/3, ≤3 per club,
  a valid formation every week, locked and banned players from memory.

---

## 6. Planner (`planner/recommend.py`)

Turns the solution into transfers, lineup, captain and a rationale.

**Close calls.** For each player bought, other players at the same position
within **1 xPt over the horizon** (or 5% of his total, whichever is larger) and
affordable with the money left after the plan's transfers. These are listed
because the model can't tell them apart with confidence. The choice between
them is yours, and is where league ownership matters. The 3-per-club rule is not
checked for alternatives. If the captain and vice are within 0.3 xPts, the
rationale says so.

---

## 7. League layer (`league.py`)

Fetched on every sync, from your first private classic league (or
`FPL_LEAGUE_ID`). It loads the top 10 managers plus you.

| Number | Meaning |
|---|---|
| Gap | your total − theirs |
| League own % | share of rivals (excluding you) who own the player |
| **League EO %** | effective ownership: captain counts ×2 (×3 for Triple Captain), bench ×0. Owning a player at league EO e gains you roughly (1 − e) × his points on the average rival |
| Shared players | in both squads; they cancel out between you |
| Edge per GW | your held squad's best XI + captain minus theirs, from the same xPts |
| Weekly swing | standard deviation of your weekly score difference this season |
| Rough chance to finish above | normal approximation: (edge × horizon − gap) ÷ (weekly swing × √GWs left). Ignores future transfers and chips |
| Chips left now / later | per window (GW1–19, GW20–38), from each rival's history |

Rivals' picks become public only after a deadline, so the comparison uses their
squads from the gameweek just locked, held unchanged.

The league layer does **not** change the optimiser yet. It informs your choice
among close calls and captains. Planned next steps: a "prefer differentials vs
the leader" tie-break, and a win-probability mode for the last ~10 gameweeks.

---

## 8. How the model is checked (`forecast/backtest.py`)

Walk-forward: pretend it's an earlier gameweek, hide everything after it, fit
the model, predict the next 1–3 gameweeks, compare with what happened. The
yardstick is "each player scores his average so far".

| Metric | Meaning |
|---|---|
| MAE | average miss per player-week. About 2 points is normal, because FPL scores are lumpy. It rewards under-predicting, so don't use it alone |
| Correlation | how well predictions rank players; about 0.3 per gameweek is normal |
| Top-20 average | real points of the model's top 20 picks each week; the one that matters most for picking a team |
| Bias | predicted − actual on average. The model currently runs about 0.3–0.4 points low |
| Calibration | predicted vs actual by band; matching bars mean forecasts can be taken at face value |

Results at the time of writing (GW1–10 of 2026/27):

| Variant | 1-GW top-20 | 3-GW top-20 | GK/DEF bias (1 GW) |
|---|---|---|---|
| Previous model | 4.89 | 4.28 | −0.47 |
| + role share | 4.94 | 4.25 | −0.47 |
| + finishing 15% | 4.92 | 4.34 | −0.47 |
| + negative-binomial clean sheets | 4.86 | 4.32 | −0.33 |
| **All three (current)** | **4.96** | **4.30** | **−0.34** |

Ten gameweeks is a small sample, and differences of a few hundredths are
noise. The clean-sheet fix is the only change with a clear measured effect;
the other two are kept for their structure and because the research supports
them.

---

## 9. What the model does not know yet

* **Penalty takers.** FPL's xG includes penalties (about 0.76 each), so a
  penalty taker's xG partly reflects a role, not open play. Penalty order isn't
  stored yet.
* **Teammate absences.** When a striker is out, his share should pass to his
  replacement. The share structure allows this, but it isn't done yet.
* **Goalkeeper shot-stopping.** FPL gives xG conceded before the shot, not
  post-shot xG, so a keeper's saving skill can't be separated from luck.
* **Set-piece roles, price changes, bookmaker odds.** Not used.
* **Overall under-prediction** of about 0.3–0.4 points per player-week; worth
  investigating, probably bonus and the prior discount.
