# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js frontend backed by a Python API. Chosen 2026-11-22 so the interface
isn't limited by Streamlit and can deploy to Vercel (free Hobby plan) as a
demo later. The Python engine (`fpl_agent/`: data ingest, xPts forecast, MILP
optimiser, planner, league layer) stays the source of truth and is exposed as
the API. The current Streamlit dashboard (`fpl_agent/ui/app.py`) is the
functional reference for the rebuild, not its design. The CLI stays for
power users.

## Users

Fantasy Premier League managers, served in layers:

- **Anyone near a deadline** who wants a clear answer: which transfers to make,
  who to captain, whether to play a chip. They should get it in the first view
  without reading a table.
- **Engaged, stats-curious managers** who play every week, know xG and xA, and
  want a second opinion they can check. For them the depth is the point: the
  full player table, fixture grid, head-to-head with rivals and the model check.

The same product serves both. The answer comes first and the evidence sits
underneath, one step away.

## Product Purpose

Enter an FPL team ID and get a plan for the next deadline, worked out from
underlying stats: transfers (with near-equal alternatives), best XI and bench
order, captain and vice, a chip outlook, and a gameweek-by-gameweek plan over
a chosen horizon. It never touches the user's FPL account; they make the moves
themselves.

Success means a manager trusts the plan enough to act on it, understands why,
and gains ground on the people they actually compete with.

## Positioning

Two things set it apart, both decided by the owner:

1. **Built around your mini-league.** It plans to beat your rivals, not just to
   score points overall: league standings, rivals' captains and chips,
   effective ownership inside your league, differentials on each side, your
   expected edge per gameweek, and a rough chance to finish above a chosen
   rival. Close-call transfer options show league ownership, so the user can
   choose cover or a differential.
2. **Explains every pick.** Each transfer, captain and lineup choice comes with
   the stats behind it in plain language: expected minutes, xG/90, xA/90,
   defensive-contribution rate, clean-sheet chance, fixture, and the xPts gain
   over the horizon.

## Operating Context

- Used in the days before each FPL gameweek deadline, often on a phone,
  alongside the official FPL site or app where the user makes the moves.
- Users find their team ID in the Points page URL
  (`fantasy.premierleague.com/entry/<ID>/event/…`). The landing flow accepts
  the ID or the pasted link, and the ID is kept in the page URL so a plan can be
  bookmarked or shared.
- Mini-league comparison depends on the team being in a private classic league.

## Capabilities and Constraints

- **Public data only, no login.** Everything comes from FPL's public API. It
  can't see transfers already made for the next deadline; users can enter their
  free transfers and bank by hand, and these expire after the deadline.
- **No accounts.** A team's saved settings (locked/banned players, notes,
  overrides) are tied to the team ID. On a shared server anyone with the ID can
  see and change them. The hosted version is expected to keep them in the
  visitor's browser instead (not yet built).
- **Shared data, per-user solve.** Player and fixture data and the xPts forecast
  are the same for everyone; only the optimisation depends on the user's squad.
  A full data refresh fetches every player's match history (hundreds of API
  calls), so it must never run while a user waits.
- **User options:** horizon (1–8 GWs), Wildcard or Free Hit (only if
  available), one-off free transfers and bank, value of a saved transfer, bench
  weight, and a consistency preference (favour players who return week after
  week).
- **Terminology in use:** xPts (expected points), xG, xA, xMins, DC
  (defensive contribution), CS (clean sheet), EO (effective ownership, captain
  counts double), hit (−4 transfer), horizon, blank/double gameweek, close call.
- **Undecided:** the product name. "FPL Agent" is a working name; treat it as
  replaceable and don't build identity around it.

## Brand Commitments

- Not affiliated with the Premier League or FPL. No Premier League logos,
  crests, club badges or official branding.
- Plain-language copy: explain stats in words a regular FPL player uses, as
  the current backtest and "How the model works" text already does.

## Evidence on Hand

- Live FPL data (players, fixtures, team ratings, any public team) through the
  engine.
- A walk-forward backtest against a points-per-game baseline, shown in the
  Model check tab and documented in `docs/MODEL.md` (§8), plus open hypotheses
  re-tested weekly (§10).
- Method write-up: `docs/MODEL.md`.
- None of these exist, so they must not be invented: users, testimonials,
  rank-improvement claims, press, or usage numbers.

## Product Principles

1. **Answer first, evidence one step away.** Lead with what to do this
   gameweek; every number that supports it is reachable without hunting.
2. **Your league is the scoreboard.** Frame decisions by how they move you
   against the people you're actually playing.
3. **Show the working.** No pick without a reason a manager can check; say
   plainly when a choice is a close call.
4. **Honest about uncertainty.** Projections are estimates. Show the size of
   the edge and how lumpy FPL scoring is, and never claim certainty.
5. **The user stays in control.** The user makes the moves; locks, bans and
   overrides always win over the model.
