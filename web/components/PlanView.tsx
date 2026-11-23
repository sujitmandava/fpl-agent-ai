"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SlidersHorizontal, ChevronRight } from "lucide-react";
import type { ApiError } from "@/lib/api";
import { usePlan } from "@/lib/usePlan";
import type { Move, Plan, PlayerCard } from "@/lib/types";
import { deadline, firstName, fixed, ordinal, pct, signed, signedInt } from "@/lib/format";
import Board, { Bench } from "./Board";
import TeamForm from "./TeamForm";
import { useTeamStatus } from "./Shell";
import PlayerSheet from "./PlayerSheet";
import OptionsSheet from "./OptionsSheet";
import styles from "./PlanView.module.css";

export default function PlanView({ teamId }: { teamId: number }) {
  const { plan, error, loading, settings, update, refresh } = usePlan(teamId);
  const { setMissing } = useTeamStatus();
  const missing = !plan && error?.status === 404;
  useEffect(() => setMissing(missing), [missing, setMissing]);
  const [selected, setSelected] = useState<number | null>(null);
  const [openPlayer, setOpenPlayer] = useState<number | null>(null);
  const [optionsOpen, setOptionsOpen] = useState(false);

  // A new plan can have different moves; drop a stale selection.
  useEffect(() => setSelected(null), [plan]);

  const drawKey = useMemo(
    () => (plan ? plan.moves.map((m) => `${m.out}-${m.in}`).join("|") + plan.lineup.xi.join(",") : ""),
    [plan],
  );

  if (!plan) {
    if (error) return <Failure error={error} retry={refresh} />;
    return <Skeleton />;
  }

  const players = plan.players;
  const league = plan.league;
  const rival = league?.rival ?? null;
  const rivalName = rival?.manager_name ?? null;
  const horizon = plan.gameweek.horizon;
  const pl = (id: number | null | undefined): PlayerCard | undefined => (id == null ? undefined : players[id]);

  const toggle = (key: "locked" | "banned", id: number) => {
    const other = key === "locked" ? "banned" : "locked";
    const has = settings[key].includes(id);
    update({
      [key]: has ? settings[key].filter((x) => x !== id) : [...settings[key], id],
      [other]: settings[other].filter((x) => x !== id),
    });
  };

  return (
    <div className={styles.page}>
      <div className={styles.brandRow}>
        <Link href="/" className={styles.wordmark}>FPL Agent</Link>
        <button type="button" className={styles.optionsBtn} onClick={() => setOptionsOpen(true)}>
          <SlidersHorizontal size={17} aria-hidden /> Options
        </button>
      </div>
      <header className={styles.top}>
        <div className={styles.title}>
          <h1>{plan.team.name ?? `Team ${teamId}`}</h1>
          <p>
            GW{plan.gameweek.planning} · deadline {deadline(plan.gameweek.deadline)}
            <span className={styles.status} aria-live="polite">{loading ? " · re-planning…" : ""}</span>
          </p>
        </div>
        <button type="button" className={`${styles.optionsBtn} ${styles.optionsWide}`} onClick={() => setOptionsOpen(true)}>
          <SlidersHorizontal size={17} aria-hidden /> Options
        </button>
      </header>

      {error && <p className={styles.inlineError} role="alert">{error.message}</p>}
      {plan.notes.length > 0 && (
        <ul className={styles.notes}>{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      )}

      <Stake plan={plan} onRival={(entry) => update({ rival: entry })} onLeague={(id) => update({ league: id, rival: null })} />

      <div className={styles.work}>
        <div className={styles.boardCol}>
          <Board
            players={players}
            xi={plan.lineup.xi}
            moves={plan.moves}
            captain={plan.captain}
            vice={plan.vice_captain}
            rivalName={rivalName}
            horizon={horizon.length}
            selected={selected}
            drawKey={drawKey}
            onSelectMove={(i) => setSelected((cur) => (cur === i ? null : i))}
            onOpenPlayer={setOpenPlayer}
          />
        </div>

        <section className={styles.plate} aria-labelledby="this-week">
          <div className={styles.plateHead}>
            <h2 id="this-week">This week</h2>
            <p>
              {plan.budget.free_transfers} FT · £{plan.budget.bank.toFixed(1)}m in bank
            </p>
          </div>

          {plan.moves.length === 0 ? (
            <p className={styles.roll}>No transfer clears the bar. Save it: you&apos;ll have more to spend next week.</p>
          ) : (
            <ol className={styles.moves}>
              {plan.moves.map((m, i) => (
                <MoveRow key={`${m.out}-${m.in}`} move={m} out={pl(m.out)} inn={pl(m.in)} rivalName={rivalName}
                         horizon={horizon.length} selected={selected === i}
                         onSelect={() => { setSelected(i); setOpenPlayer(m.in); }} />
              ))}
            </ol>
          )}

          <CaptainRow plan={plan} rivalName={rivalName} onOpen={setOpenPlayer} />

          <div className={styles.row}>
            <div className={styles.rowMain}>
              <span className={styles.what}>{settings.chip === "wildcard" ? "Wildcard on" : settings.chip === "freehit" ? "Free Hit on" : "Chips: hold"}</span>
              <span className={styles.proof}>
                {settings.chip === "none" ? "Best weeks for each chip are below." : "Planned with your chip active."}
              </span>
            </div>
          </div>

          <dl className={styles.totals}>
            <div><dt>GW{plan.gameweek.next} gain</dt><dd className="cond">{signed(plan.summary.delta_next)}</dd></div>
            <div><dt>{horizon.length}-GW gain</dt><dd className="cond">{signed(plan.summary.delta_horizon)}</dd></div>
            <div><dt>GW{plan.gameweek.next} projected</dt><dd className="cond">{fixed(plan.summary.next_gw_points)}</dd></div>
          </dl>
          <p className={styles.totalsNote}>
            Gains are against making no transfers{plan.summary.hits > 0 ? `, after a −${plan.summary.hits} hit` : ""}.
          </p>
        </section>

        <div className={styles.benchCol}>
          <Bench players={players} bench={plan.lineup.bench} moves={plan.moves} rivalName={rivalName} onOpenPlayer={setOpenPlayer} />
        </div>
      </div>

      <div className={styles.below}>
        <CloseCalls moves={plan.moves} players={players} />

        <section className={styles.section} aria-labelledby="chips">
          <h2 id="chips">Chip outlook</h2>
          <ul className={styles.list}>{plan.chip_advice.map((a) => <li key={a}>{a}</li>)}</ul>
        </section>

        <section className={styles.section} aria-labelledby="by-gw">
          <h2 id="by-gw">Plan by gameweek</h2>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">GW</th><th scope="col">Captain</th>
                  <th scope="col" className={styles.num}>XI xPts</th>
                  <th scope="col" className={`${styles.num} ${styles.wide}`}>Bench</th>
                  {rival && (
                    <th scope="col" className={styles.num}>
                      Edge<span className={styles.wideInline}> vs {firstName(rival.manager_name)}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {plan.plan_by_gw.map((g) => {
                  const edge = rival?.by_gw.find((r) => r.gw === g.gw)?.edge ?? null;
                  return (
                    <tr key={g.gw}>
                      <td>GW{g.gw}</td>
                      <td>{pl(g.captain)?.name ?? "—"}</td>
                      <td className={styles.num}>{fixed(g.xi_points)}</td>
                      <td className={`${styles.num} ${styles.wide}`}>{fixed(g.bench_points)}</td>
                      {rival && <td className={styles.num}>{signed(edge)}</td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className={styles.caption}>Holds the recommended squad; the XI and captain are re-picked each week.</p>
        </section>

        <details className={styles.why}>
          <summary>Why this plan <ChevronRight size={16} aria-hidden /></summary>
          <pre>{plan.rationale}</pre>
        </details>
      </div>

      <PlayerSheet
        player={pl(openPlayer) ?? null}
        horizon={horizon}
        rivalName={rivalName}
        locked={openPlayer != null && settings.locked.includes(openPlayer)}
        banned={openPlayer != null && settings.banned.includes(openPlayer)}
        onToggleLock={() => openPlayer != null && toggle("locked", openPlayer)}
        onToggleBan={() => openPlayer != null && toggle("banned", openPlayer)}
        onClose={() => setOpenPlayer(null)}
      />
      <OptionsSheet
        open={optionsOpen}
        settings={settings}
        chips={plan.chips}
        publicFreeTransfers={plan.budget.free_transfers_source === "public" ? plan.budget.free_transfers : null}
        publicBank={plan.budget.bank_source === "public" ? plan.budget.bank : null}
        onChange={update}
        onRefresh={() => { refresh(); setOptionsOpen(false); }}
        onClose={() => setOptionsOpen(false)}
      />
    </div>
  );
}

export function Stake({ plan, onRival, onLeague, detail = true }: {
  plan: Plan; onRival: (e: number) => void; onLeague: (id: number) => void;
  /** Edge and finish chance beside the figure; off where a plate already sets them. */
  detail?: boolean;
}) {
  const league = plan.league;
  const rival = league?.rival;

  if (!league || !rival) {
    return (
      <section className={styles.stake}>
        <p className={`${styles.figure} cond`}>{plan.team.overall_points ?? "—"}</p>
        <div className={styles.stakeText}>
          <p><b>points so far</b>{plan.team.overall_rank ? ` · overall rank ${plan.team.overall_rank.toLocaleString("en-GB")}` : ""}</p>
          <p>Join a private classic league on the FPL site to plan against your rivals.</p>
        </div>
      </section>
    );
  }

  const others = league.standings.filter((s) => !s.is_me);
  const behind = rival.gap < 0;
  return (
    <section className={styles.stake} aria-label="Your mini-league position">
      <p className={`${styles.figure} cond ${behind ? styles.behind : rival.gap > 0 ? styles.ahead : ""}`}>
        {signedInt(rival.gap)}
      </p>
      <div className={styles.stakeText}>
        <p>
          <b>{behind ? "behind" : rival.gap > 0 ? "ahead of" : "level with"} </b>
          <label className={styles.rivalPick}>
            <span className="sr-only">Compare with</span>
            <select value={rival.entry} onChange={(e) => onRival(Number(e.target.value))}>
              {others.map((s) => (
                <option key={s.entry} value={s.entry}>{s.manager_name}</option>
              ))}
            </select>
          </label>
          {" · "}{ordinal(league.my_rank)} of {league.size}
        </p>
        {(detail || plan.leagues.length > 1) && <p>
          {detail && <>Edge {signed(rival.edge_per_gw)}/GW · {pct(rival.p_ahead)} to finish above</>}
          {plan.leagues.length > 1 && (
            <>
              {detail && " · "}
              <label className={styles.rivalPick}>
                <span className="sr-only">League</span>
                <select value={league.id} onChange={(e) => onLeague(Number(e.target.value))}>
                  {plan.leagues.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            </>
          )}
        </p>}
      </div>
    </section>
  );
}

function MoveRow({ move, out, inn, rivalName, horizon, selected, onSelect }: {
  move: Move; out?: PlayerCard; inn?: PlayerCard; rivalName: string | null; horizon: number;
  selected: boolean; onSelect: () => void;
}) {
  if (!out || !inn) return null;
  const stance = rivalName
    ? inn.rival_owns
      ? `${firstName(rivalName)} owns ${inn.name}: cover`
      : `${firstName(rivalName)} doesn't: differential`
    : null;
  return (
    <li>
      <button type="button" className={`${styles.row} ${styles.moveBtn}`} aria-pressed={selected} onClick={onSelect}>
        <span className={styles.rowMain}>
          <span className={styles.what}>{out.name} <span aria-label="to">→</span> {inn.name}</span>
          <span className={styles.proof}>
            {inn.fixture} · {fixed(inn.xmins, 0)} mins · xG/90 {fixed(inn.xg90, 2)} · xA/90 {fixed(inn.xa90, 2)}
            {inn.returns ? ` · returned ${inn.returns}` : ""}
          </span>
          {stance && <span className={styles.stance}>{stance}</span>}
        </span>
        <span className={styles.gainCol}>
          <span className={`${styles.gain} cond`}>{signed(move.gain_horizon)}</span>
          <span className={styles.gainCap}>{horizon} GWs</span>
        </span>
      </button>
    </li>
  );
}

function CaptainRow({ plan, rivalName, onOpen }: { plan: Plan; rivalName: string | null; onOpen: (id: number) => void }) {
  const c = plan.players[plan.captain];
  const v = plan.players[plan.vice_captain];
  const rivalCap = plan.league?.rival?.captain;
  if (!c) return null;
  const stance = rivalName
    ? rivalCap === plan.captain
      ? `Same captain as ${firstName(rivalName)}: it cancels out`
      : `${firstName(rivalName)} captains ${plan.players[rivalCap ?? -1]?.name ?? "someone else"}: your swing pick`
    : null;
  return (
    <button type="button" className={`${styles.row} ${styles.moveBtn}`} onClick={() => onOpen(c.id)}>
      <span className={styles.rowMain}>
        <span className={styles.what}>Captain {c.name}</span>
        <span className={styles.proof}>{c.fixture} · vice {v?.name ?? "—"}</span>
        {stance && <span className={styles.stance}>{stance}</span>}
      </span>
      <span className={styles.gainCol}>
        <span className={`${styles.gain} cond`}>{fixed(c.xpts_next)}</span>
        <span className={styles.gainCap}>xPts</span>
      </span>
    </button>
  );
}

function CloseCalls({ moves, players }: { moves: Move[]; players: Record<string, PlayerCard> }) {
  const rows = moves.flatMap((m) => m.alternatives.map((a) => ({ m, a, p: players[a.id], pick: players[m.in] })));
  if (rows.length === 0) return null;
  return (
    <section className={styles.section} aria-labelledby="close-calls">
      <h2 id="close-calls">Close calls</h2>
      <p className={styles.caption}>
        Near-equal options you could afford instead. When it&apos;s this close, a low league EO is a differential; a high one is cover.
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Instead of</th><th scope="col">Option</th>
              <th scope="col" className={styles.num}>xPts diff</th>
              <th scope="col" className={`${styles.num} ${styles.wide}`}>Price diff</th>
              <th scope="col" className={styles.num}>League EO</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ m, a, p, pick }) => (
              <tr key={`${m.in}-${a.id}`}>
                <td>{pick?.name}</td>
                <td>{p?.name ?? a.id}</td>
                <td className={styles.num}>{signed(a.delta)}</td>
                <td className={`${styles.num} ${styles.wide}`}>{a.price != null && m.buy_price != null ? signed(a.price - m.buy_price) : "—"}</td>
                <td className={styles.num}>{p?.league_eo == null ? "—" : `${Math.round(p.league_eo)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function Skeleton() {
  return (
    <div className={styles.page} aria-busy="true">
      <header className={styles.top}>
        <div className={styles.title}><h1 className={styles.ghostText}>Loading your team</h1><p>Fetching the latest FPL data…</p></div>
      </header>
      <div className={styles.work}>
        <div className={styles.boardCol}><div className={styles.boardGhost} /></div>
        <div className={`${styles.plate} ${styles.plateGhost}`} />
      </div>
    </div>
  );
}

export function Failure({ error, retry }: { error: ApiError; retry: () => void }) {
  const notFound = error.status === 404;
  return (
    <div className={styles.failure}>
      <Link href="/" className={styles.wordmark}>FPL Agent</Link>
      <div className={styles.emptyBoard} aria-hidden>
        <span>No counters on the board</span>
      </div>
      <div role="alert" className={styles.failureText}>
        <h1>{notFound ? "No team with that ID" : "Couldn't load your plan"}</h1>
        <p>{error.message}</p>
      </div>
      {notFound ? (
        <TeamForm compact />
      ) : (
        <div className={styles.failureActions}>
          <button type="button" onClick={retry}>Try again</button>
          <Link href="/">Back to the start</Link>
        </div>
      )}
    </div>
  );
}
