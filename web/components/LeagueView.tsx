"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { usePlan } from "@/lib/usePlan";
import type { League, Plan, PlayerCard, Rival } from "@/lib/types";
import { firstName, fixed, pct, signed, signedInt } from "@/lib/format";
import { Failure, Skeleton, Stake } from "./PlanView";
import { useTeamStatus } from "./Shell";
import OptionsSheet from "./OptionsSheet";
import RaceBoard, { raceSeries } from "./RaceBoard";
import ps from "./PlanView.module.css";
import styles from "./LeagueView.module.css";

const CHIP_NAMES: Record<string, string> = {
  "3xc": "Triple Captain", bboost: "Bench Boost", freehit: "Free Hit", wildcard: "Wildcard", manager: "Assistant Manager",
};
const chipName = (c: string) => CHIP_NAMES[c] ?? c;

export default function LeagueView({ teamId }: { teamId: number }) {
  const { plan, error, loading, settings, update, refresh } = usePlan(teamId);
  const { setMissing } = useTeamStatus();
  const missing = !plan && error?.status === 404;
  useEffect(() => setMissing(missing), [missing, setMissing]);
  const [optionsOpen, setOptionsOpen] = useState(false);

  if (!plan) {
    if (error) return <Failure error={error} retry={refresh} />;
    return <Skeleton />;
  }

  const league = plan.league;
  const rival = league?.rival ?? null;
  const pickRival = (entry: number) => update({ rival: entry });
  const pickLeague = (id: number) => update({ league: id, rival: null });

  return (
    <div className={ps.page}>
      <div className={ps.brandRow}>
        <Link href="/" className={ps.wordmark}>FPL Agent</Link>
        <button type="button" className={ps.optionsBtn} onClick={() => setOptionsOpen(true)}>
          <SlidersHorizontal size={17} aria-hidden /> Options
        </button>
      </div>
      <header className={ps.top}>
        <div className={ps.title}>
          <h1>{league?.name ?? "Your mini-league"}</h1>
          <p>
            {league ? `Standings after GW${league.gw}` : (plan.team.name ?? `Team ${teamId}`)}
            <span className={ps.status} aria-live="polite">{loading ? " · updating…" : ""}</span>
          </p>
        </div>
        <button type="button" className={`${ps.optionsBtn} ${ps.optionsWide}`} onClick={() => setOptionsOpen(true)}>
          <SlidersHorizontal size={17} aria-hidden /> Options
        </button>
      </header>

      {error && <p className={ps.inlineError} role="alert">{error.message}</p>}

      <Stake plan={plan} onRival={pickRival} onLeague={pickLeague} detail={false} />

      {!league ? (
        <NoLeague />
      ) : (
        <>
          <div className={ps.work}>
            <div className={ps.boardCol}>
              {rival ? (
                <RaceBoard rival={rival} drawKey={`${rival.entry}-${plan.gameweek.horizon.length}`} />
              ) : (
                <div className={ps.emptyBoard} aria-hidden><span>No rival on the board yet</span></div>
              )}
            </div>
            {rival && <HeadToHead plan={plan} league={league} rival={rival} />}
          </div>

          <div className={ps.below}>
            <Standings plan={plan} league={league} rival={rival} onPick={pickRival} />
            {rival && <GapPlayers plan={plan} rival={rival} />}
            {rival && <ByGameweek plan={plan} rival={rival} />}
            <Ownership plan={plan} league={league} />
          </div>
        </>
      )}

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

// -- The plate ------------------------------------------------------------------

function HeadToHead({ plan, league, rival }: { plan: Plan; league: League; rival: Rival }) {
  const name = firstName(rival.manager_name);
  const pl = (id: number | null | undefined): PlayerCard | undefined => (id == null ? undefined : plan.players[id]);
  const next = rival.by_gw[0];
  const yourC = pl(plan.captain);
  const theirC = pl(next?.their_captain);
  const { projection } = raceSeries(rival);
  const end = projection[projection.length - 1];
  const yourChips = plan.chips.filter((c) => c.status === "available").map((c) => c.label);

  return (
    <section className={ps.plate} aria-labelledby="h2h">
      <div className={ps.plateHead}>
        <h2 id="h2h">Head to head</h2>
        <p>vs {name}</p>
      </div>

      <div className={ps.row}>
        <div className={ps.rowMain}>
          <span className={ps.what}>Captains, GW{next?.gw ?? plan.gameweek.next}</span>
          <span className={ps.proof}>
            You: {yourC?.name ?? "—"} · {name}&apos;s likely: {theirC?.name ?? "—"}
            {rival.captain != null && ` · ${name} captained ${pl(rival.captain)?.name ?? "someone else"} in GW${league.gw}`}
          </span>
          <span className={ps.stance}>
            {yourC && theirC && yourC.id === theirC.id
              ? "Same captain: it cancels out"
              : "Different captains: this is where the week swings"}
          </span>
        </div>
      </div>

      <div className={ps.row}>
        <div className={ps.rowMain}>
          <span className={ps.what}>{name}&apos;s chips</span>
          <span className={ps.proof}>
            {rival.active_chip ? `Played ${chipName(rival.active_chip)} in GW${league.gw} · ` : ""}
            {rival.chips_now.length ? `Left: ${rival.chips_now.join(", ")}` : "None left until the next window"}
          </span>
          <span className={ps.stance}>{chipStance(rival.chips_now, yourChips, name)}</span>
        </div>
      </div>

      <div className={ps.row}>
        <div className={ps.rowMain}>
          <span className={ps.what}>You share {rival.shared.length} of 15</span>
          <span className={ps.proof}>
            The other {rival.mine_only.length} on your side and {rival.theirs_only.length} on {name}&apos;s decide the gap. They&apos;re listed below.
          </span>
        </div>
      </div>

      <dl className={ps.totals}>
        <div><dt>Edge per GW</dt><dd className="cond">{signed(rival.edge_per_gw)}</dd></div>
        <div><dt>Gap after GW{end.gw}</dt><dd className="cond">{projection.length > 1 ? signedInt(Math.round(end.gap)) : "—"}</dd></div>
        <div><dt>Finish above</dt><dd className="cond">{pct(rival.p_ahead)}</dd></div>
      </dl>
      <p className={ps.totalsNote}>
        Both squads held. Finish chance is rough: the gap plus that edge against a ±{fixed(rival.weekly_sd, 0)}-point
        weekly swing, {rival.remaining} GWs left.
      </p>
    </section>
  );
}

function chipStance(theirs: string[], yours: string[], name: string) {
  const onlyThem = theirs.filter((c) => !yours.includes(c));
  const onlyYou = yours.filter((c) => !theirs.includes(c));
  if (!onlyThem.length && !onlyYou.length) return "Same chips as you: no edge either way";
  return [
    onlyYou.length ? `Only you: ${onlyYou.join(", ")}` : null,
    onlyThem.length ? `Only ${name}: ${onlyThem.join(", ")}` : null,
  ].filter(Boolean).join(" · ");
}

// -- Below the fold -------------------------------------------------------------

function Standings({ plan, league, rival, onPick }: {
  plan: Plan; league: League; rival: Rival | null; onPick: (entry: number) => void;
}) {
  const pick = (entry: number) => {
    onPick(entry);
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" });
  };
  return (
    <section className={`${ps.section} ${styles.full}`} aria-labelledby="standings">
      <h2 id="standings">Standings</h2>
      <p className={ps.caption}>
        Tap a manager to race against them.
        {league.partial ? ` A big league: only the top managers and you are loaded (${league.loaded} in all).` : ""}
      </p>
      <div className={ps.tableWrap}>
        <table className={ps.table}>
          <thead>
            <tr>
              <th scope="col" className={ps.num}>#</th>
              <th scope="col">Manager</th>
              <th scope="col" className={`${ps.num} ${ps.wide}`}>GW{league.gw}</th>
              <th scope="col" className={ps.num}>Total</th>
              <th scope="col" className={ps.num}>Gap</th>
              <th scope="col" className={ps.wide}>Chips left</th>
            </tr>
          </thead>
          <tbody>
            {league.standings.map((s) => {
              const isRival = rival?.entry === s.entry;
              const cap = s.captain != null ? plan.players[s.captain]?.name : null;
              const sub = [
                s.team_name,
                cap ? `C ${cap}` : null,
                s.active_chip ? `${chipName(s.active_chip)} played` : null,
              ].filter(Boolean).join(" · ");
              return (
                <tr key={s.entry} className={s.is_me ? styles.meRow : isRival ? styles.rivalRow : undefined}>
                  <td className={ps.num}>{s.rank}</td>
                  <td className={styles.who}>
                    {s.is_me ? (
                      <span className={styles.name}>{s.manager_name} <span className={styles.youTag}>You</span></span>
                    ) : (
                      <button type="button" className={styles.pick} aria-pressed={isRival} onClick={() => pick(s.entry)}>
                        {isRival && <i className={styles.disc} aria-hidden>{firstName(s.manager_name).charAt(0).toUpperCase()}</i>}
                        {s.manager_name}
                        {isRival && <span className="sr-only"> (your rival)</span>}
                      </button>
                    )}
                    <span className={styles.sub}>{sub}</span>
                  </td>
                  <td className={`${ps.num} ${ps.wide}`}>{s.gw_points}</td>
                  <td className={ps.num}>{s.total.toLocaleString("en-GB")}</td>
                  <td className={ps.num}>{s.is_me ? "—" : signedInt(-s.gap)}</td>
                  <td className={`${ps.wide} ${styles.chips}`}>{s.chips_now.length ? s.chips_now.join(", ") : "None"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className={ps.caption}>Gap is their total minus yours. Captains and chips are from the GW{league.gw} deadline; picks become public only after each deadline.</p>
    </section>
  );
}

function GapPlayers({ plan, rival }: { plan: Plan; rival: Rival }) {
  const n = plan.gameweek.horizon.length;
  const name = firstName(rival.manager_name);
  return (
    <section className={`${ps.section} ${styles.full}`} aria-labelledby="gap-players">
      <h2 id="gap-players">Where the gap comes from</h2>
      <p className={ps.caption}>The players only one of you owns. Shared players score for both of you and cancel out.</p>
      <div className={styles.twoUp}>
        <PlayerList title="Only you" ids={rival.mine_only} plan={plan} n={n} />
        <PlayerList title={`Only ${name}`} ids={rival.theirs_only} plan={plan} n={n} />
      </div>
    </section>
  );
}

function PlayerList({ title, ids, plan, n }: { title: string; ids: number[]; plan: Plan; n: number }) {
  const rows = ids.map((id) => plan.players[id]).filter(Boolean)
    .sort((a, b) => (b.xpts_horizon ?? 0) - (a.xpts_horizon ?? 0));
  const total = rows.reduce((t, p) => t + (p.xpts_horizon ?? 0), 0);
  return (
    <div className={ps.tableWrap}>
      <table className={ps.table}>
        <caption className={styles.tableTitle}>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Player</th>
            <th scope="col" className={ps.num}>xPts {n} GW</th>
            <th scope="col" className={ps.num}>League EO</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={3} className={styles.empty}>Nobody: identical squads</td></tr>}
          {rows.map((p) => (
            <tr key={p.id}>
              <td>{p.name} <span className={styles.meta}>{p.pos} · {p.team}</span></td>
              <td className={ps.num}>{fixed(p.xpts_horizon)}</td>
              <td className={ps.num}>{p.league_eo == null ? "—" : `${Math.round(p.league_eo)}%`}</td>
            </tr>
          ))}
        </tbody>
        {rows.length > 0 && (
          <tfoot className={styles.foot}>
            <tr><th scope="row">Together</th><td className={ps.num}>{fixed(total)}</td><td /></tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

function ByGameweek({ plan, rival }: { plan: Plan; rival: Rival }) {
  const name = firstName(rival.manager_name);
  const pl = (id: number | null) => (id == null ? "—" : plan.players[id]?.name ?? "—");
  const { history } = raceSeries(rival);
  const gapAfter = new Map(history.map((p) => [p.gw, p.gap]));
  const played = [...rival.weekly].reverse();
  return (
    <section className={`${ps.section} ${styles.full}`} aria-labelledby="race-by-gw">
      <h2 id="race-by-gw">Gameweek by gameweek</h2>
      <p className={ps.caption}>The race board in figures: what each of you scored, then what the model expects with today&apos;s squads held.</p>
      <div className={ps.tableWrap}>
        <table className={ps.table}>
          <thead>
            <tr>
              <th scope="col">GW</th>
              <th scope="col" className={ps.num}>You</th>
              <th scope="col" className={ps.num}>{name}</th>
              <th scope="col" className={ps.num}>Edge</th>
              <th scope="col" className={ps.wide}>Your C</th>
              <th scope="col" className={ps.wide}>{name}&apos;s likely C</th>
              <th scope="col" className={ps.num}>Gap after</th>
            </tr>
          </thead>
          <tbody>
            <tr className={styles.group}><th scope="rowgroup" colSpan={7}>Projected, next {rival.by_gw.length} GWs</th></tr>
            {[...rival.by_gw].reverse().map((g) => (
              <tr key={`p${g.gw}`}>
                <td>GW{g.gw}</td>
                <td className={ps.num}>{fixed(g.you)}</td>
                <td className={ps.num}>{fixed(g.them)}</td>
                <td className={ps.num}>{signed(g.edge)}</td>
                <td className={ps.wide}>{pl(g.your_captain)}</td>
                <td className={ps.wide}>{pl(g.their_captain)}</td>
                <td className={ps.num}>{projectedGap(rival, g.gw)}</td>
              </tr>
            ))}
          </tbody>
          <tbody>
            <tr className={styles.group}><th scope="rowgroup" colSpan={7}>Played</th></tr>
            {played.map((w) => (
              <tr key={`h${w.gw}`}>
                <td>GW{w.gw}</td>
                <td className={ps.num}>{w.you}</td>
                <td className={ps.num}>{w.them}</td>
                <td className={ps.num}>{signedInt(w.you - w.them)}</td>
                <td className={ps.wide} />
                <td className={ps.wide} />
                <td className={ps.num}>{signedInt(gapAfter.get(w.gw) ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={ps.caption}>
        Played points are after hits. Projected weeks pick the best XI and captain from each squad as it stands; a different
        captain is where a week swings.
      </p>
    </section>
  );
}

function projectedGap(rival: Rival, gw: number) {
  const p = raceSeries(rival).projection.find((x) => x.gw === gw);
  return p ? signedInt(Math.round(p.gap)) : "—";
}

function Ownership({ plan, league }: { plan: Plan; league: League }) {
  const { rivals, rows } = league.ownership;
  const mine = new Set([...plan.lineup.xi, ...plan.lineup.bench]);
  if (rows.length === 0) return null;
  return (
    <section className={`${ps.section} ${styles.full}`} aria-labelledby="owned">
      <h2 id="owned">Who your league owns</h2>
      <div className={ps.tableWrap}>
        <table className={ps.table}>
          <thead>
            <tr>
              <th scope="col">Player</th>
              <th scope="col" className={ps.num}>Owned</th>
              <th scope="col" className={ps.num}>League EO</th>
              <th scope="col">You</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 15).map((r) => {
              const p = plan.players[r.id];
              return (
                <tr key={r.id}>
                  <td>
                    {p?.name ?? r.id} <span className={styles.meta}>{p?.pos}{r.captains ? ` · C ×${r.captains}` : ""}</span>
                  </td>
                  <td className={ps.num}>{r.owners}/{rivals}</td>
                  <td className={ps.num}>{r.eo == null ? "—" : `${Math.round(r.eo)}%`}</td>
                  <td>{p?.owned ? "Yes" : mine.has(r.id) ? "Buying" : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className={ps.caption}>
        Among the {rivals} rivals loaded, you excluded. C ×3 means three of them captained him. EO counts a captain twice and a benched player zero: above 100%, a
        player you don&apos;t own costs you ground every time he scores.
      </p>
    </section>
  );
}

function NoLeague() {
  return (
    <div className={styles.noLeague}>
      <div className={ps.emptyBoard} aria-hidden><span>No league on the board</span></div>
      <div className={styles.noLeagueText}>
        <h2>This team isn&apos;t in a private league yet</h2>
        <p>
          Join or create a classic league on the FPL site, then come back. The race, your rivals&apos; captains and chips,
          and who your league owns will appear here.
        </p>
      </div>
    </div>
  );
}
