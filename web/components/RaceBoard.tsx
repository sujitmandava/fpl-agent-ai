"use client";

import type { CSSProperties } from "react";
import type { Rival } from "@/lib/types";
import { firstName, signed, signedInt } from "@/lib/format";
import styles from "./RaceBoard.module.css";

// Board coordinates: 100 wide × 62 tall. The rival is the level line; your gap
// to them is the marker line, above it when you're ahead.
const W = 100;
const H = 62;
const PLOT = { x0: 13.5, x1: 89, y0: 7, y1: 50 };
const AXIS_Y = 56.5;

type Pt = { gw: number; gap: number };

/** The race: your cumulative gap after each gameweek, then the projection. */
export function raceSeries(rival: Rival) {
  const diffs = rival.weekly.map((w) => w.you - w.them);
  // A manager who joined late has no points for early weeks; start the line
  // where it has to so it ends on the real standings gap.
  let gap = rival.gap - diffs.reduce((a, b) => a + b, 0);
  const history: Pt[] = [];
  if (rival.weekly.length) {
    history.push({ gw: rival.weekly[0].gw - 1, gap });
    rival.weekly.forEach((w, i) => {
      gap += diffs[i];
      history.push({ gw: w.gw, gap });
    });
  } else {
    history.push({ gw: 0, gap: rival.gap });
  }
  const now = history[history.length - 1];
  const sd = rival.weekly_sd ?? 12;
  const projection: (Pt & { spread: number })[] = [{ ...now, spread: 0 }];
  let k = 0;
  for (const g of rival.by_gw) {
    if (g.gw <= now.gw || g.edge == null) continue;
    k += 1;
    const last = projection[projection.length - 1];
    projection.push({ gw: g.gw, gap: last.gap + g.edge, spread: sd * Math.sqrt(k) });
  }
  return { history, projection, now };
}

function niceStep(range: number) {
  for (const s of [5, 10, 20, 25, 50, 100, 200]) if (range / s <= 4) return s;
  return 500;
}

export default function RaceBoard({ rival, drawKey }: { rival: Rival; drawKey: string }) {
  const { history, projection, now } = raceSeries(rival);
  const end = projection[projection.length - 1];
  const name = firstName(rival.manager_name);
  const initial = name.charAt(0).toUpperCase();

  const values = [0, ...history.map((p) => p.gap), ...projection.flatMap((p) => [p.gap - p.spread, p.gap + p.spread])];
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const pad = Math.max(4, (hi - lo) * 0.08);
  lo -= pad;
  hi += pad;
  const gw0 = history[0].gw;
  const gw1 = Math.max(end.gw, gw0 + 1);
  const x = (gw: number) => PLOT.x0 + ((gw - gw0) / (gw1 - gw0)) * (PLOT.x1 - PLOT.x0);
  const y = (v: number) => PLOT.y1 - ((v - lo) / (hi - lo)) * (PLOT.y1 - PLOT.y0);
  const path = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"} ${x(p.gw).toFixed(2)} ${y(p.gap).toFixed(2)}`).join(" ");

  const step = niceStep(hi - lo);
  const grid: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) if (v !== 0) grid.push(v);

  const span = gw1 - gw0;
  const every = span > 24 ? 6 : span > 12 ? 4 : span > 6 ? 2 : 1;
  const ticks = new Set<number>([now.gw, end.gw]);
  for (let g = gw0 + 1; g < gw1; g++) if (g % every === 0 && Math.abs(g - now.gw) >= every / 2 && Math.abs(g - end.gw) >= every / 2) ticks.add(g);
  if (gw0 >= 1) ticks.add(gw0);

  const band = projection.length > 1
    ? [
        ...projection.map((p) => `${x(p.gw).toFixed(2)},${y(p.gap + p.spread).toFixed(2)}`),
        ...[...projection].reverse().map((p) => `${x(p.gw).toFixed(2)},${y(p.gap - p.spread).toFixed(2)}`),
      ].join(" ")
    : null;

  // The weekly edge, written past today's magnet on the side of the line away
  // from level, so it never sits on the magnet or the level line.
  const away = now.gap >= 0 ? -1 : 1;
  const notePos: CSSProperties | null = projection.length > 1 && rival.edge_per_gw != null
    ? {
        left: pct(Math.min(x(now.gw) + 2, PLOT.x1 - 27), W),
        top: pct(Math.max(PLOT.y0 + 3, Math.min(AXIS_Y - 5, y(now.gap) + away * 10)), H),
      }
    : null;

  const worst = history.reduce((a, b) => (b.gap < a.gap ? b : a));
  const best = history.reduce((a, b) => (b.gap > a.gap ? b : a));
  const summary = [
    `After GW${now.gw} you are ${gapWords(now.gap, name)}.`,
    history.length > 2 ? `Your best point was ${gapWords(best.gap, name)} after GW${best.gw}; your worst, ${gapWords(worst.gap, name)} after GW${worst.gw}.` : "",
    projection.length > 1 ? `With both squads held, the model projects ${gapWords(Math.round(end.gap), name)} after GW${end.gw}, give or take ${Math.round(end.spread)} points.` : "",
  ].join(" ");

  return (
    <figure className={styles.frame} aria-labelledby="race-summary">
      <div className={styles.board} key={drawKey}>
        <svg className={styles.ink} viewBox={`0 0 ${W} ${H}`} aria-hidden>
          <g className={styles.grid}>
            {grid.map((v) => <line key={v} x1={PLOT.x0} x2={PLOT.x1} y1={y(v)} y2={y(v)} />)}
            <line className={styles.today} x1={x(now.gw)} x2={x(now.gw)} y1={PLOT.y0 - 3} y2={PLOT.y1 + 2} />
          </g>
          <line className={styles.level} x1={PLOT.x0} x2={PLOT.x1 + 4} y1={y(0)} y2={y(0)} />
          {band && <polygon className={styles.band} points={band} />}
          {projection.length > 1 && <path className={styles.projection} d={path(projection)} />}
          <path className={styles.history} d={path(history)} pathLength={1} />
        </svg>

        {grid.map((v) => (
          <span key={v} className={styles.yTick} style={{ top: pct(y(v), H), right: pct(W - PLOT.x0 + 1.5, W) }}>{signedInt(v)}</span>
        ))}
        <span className={styles.yTick} style={{ top: pct(y(0), H), right: pct(W - PLOT.x0 + 1.5, W) }}>Level</span>

        {[...ticks].sort((a, b) => a - b).map((g) => (
          <span key={g} className={`${styles.xTick} ${g === now.gw ? styles.nowTick : ""}`} style={{ left: pct(x(g), W), top: pct(AXIS_Y, H) }}>
            GW{g}
          </span>
        ))}
        {projection.length > 1 && (
          <span className={styles.zone} style={{ left: pct(x(now.gw) + 1.5, W), top: pct(PLOT.y0 - 5, H) }}>Projected</span>
        )}

        <span className={styles.rivalDisc} style={{ left: pct(PLOT.x1 + 6, W), top: pct(y(0), H) }} aria-hidden>{initial}</span>
        <span className={styles.you} style={{ left: pct(x(now.gw), W), top: pct(y(now.gap), H) }} aria-hidden />
        {notePos && <span className={styles.note} style={notePos} aria-hidden>{signed(rival.edge_per_gw)} a week</span>}
      </div>
      <figcaption className={styles.key}>
        <span><i className={styles.keyYou} aria-hidden /> you, after GW{now.gw}</span>
        <span><i className={styles.keyHistory} aria-hidden /> your gap after each GW</span>
        {projection.length > 1 && <span><i className={styles.keyProjection} aria-hidden /> projected, both squads held</span>}
        <span><i className={styles.keyRival} aria-hidden>{initial}</i> level with {name}</span>
        <span id="race-summary" className="sr-only">Race against {rival.manager_name}. {summary}</span>
      </figcaption>
    </figure>
  );
}

const pct = (v: number, of: number) => `${(v / of) * 100}%`;

function gapWords(gap: number, name: string) {
  if (gap === 0) return `level with ${name}`;
  return `${Math.abs(gap)} points ${gap < 0 ? "behind" : "ahead of"} ${name}`;
}
