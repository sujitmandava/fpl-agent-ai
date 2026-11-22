"use client";

import { AlertTriangle } from "lucide-react";
import type { Move, PlayerCard, Pos } from "@/lib/types";
import { counterName, firstName, fixed, signed } from "@/lib/format";
import styles from "./Board.module.css";

// Board coordinates: 100 wide × 118 tall. A lane on the left holds players
// going out; the pitch runs GK (top) to forwards; subs sit in a band at the foot.
const W = 100;
const H = 118;
const LANE_X = 8.5;
const PITCH = { x0: 19, x1: 99 };
const ROW_Y: Record<Pos, number> = { GK: 12, DEF: 35, MID: 58, FWD: 81 };
const BENCH_Y = 107.5;
const R = 5.4; // counter radius in board units (arrows stop at the rim)

type Spot = { id: number; x: number; y: number; bench?: boolean };

function spread(ids: number[], y: number, bench = false): Spot[] {
  const span = PITCH.x1 - PITCH.x0;
  return ids.map((id, i) => ({ id, x: PITCH.x0 + ((i + 0.5) * span) / ids.length, y, bench }));
}

function layout(xi: number[], bench: number[], players: Record<string, PlayerCard>, incoming: Set<number>) {
  const rows: Record<Pos, number[]> = { GK: [], DEF: [], MID: [], FWD: [] };
  for (const id of xi) {
    const p = players[id];
    if (p) rows[p.pos].push(id);
  }
  // New signings stand nearest the "Out" lane, so each arrow stays short and
  // never crosses the rest of the row.
  for (const pos of Object.keys(rows) as Pos[]) {
    rows[pos].sort((a, b) => Number(incoming.has(b)) - Number(incoming.has(a)));
  }
  const spots = [
    ...(Object.keys(rows) as Pos[]).flatMap((pos) => spread(rows[pos], ROW_Y[pos])),
    ...spread(bench, BENCH_Y, true),
  ];
  return new Map(spots.map((s) => [s.id, s]));
}

function arrowPath(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const start = { x: a.x + ux * R, y: a.y + uy * R };
  const end = { x: b.x - ux * (R + 1.2), y: b.y - uy * (R + 1.2) };
  // Bow the stroke like a hand-drawn arc.
  const bow = Math.min(9, len * 0.22);
  const c = { x: (start.x + end.x) / 2 + uy * bow, y: (start.y + end.y) / 2 - ux * bow };
  // Arrowhead along the curve's end tangent.
  const tx = end.x - c.x;
  const ty = end.y - c.y;
  const tl = Math.hypot(tx, ty) || 1;
  const hx = tx / tl;
  const hy = ty / tl;
  const head = 3.2;
  const left = { x: end.x - hx * head - hy * head * 0.7, y: end.y - hy * head + hx * head * 0.7 };
  const right = { x: end.x - hx * head + hy * head * 0.7, y: end.y - hy * head - hx * head * 0.7 };
  const mid = { x: 0.25 * start.x + 0.5 * c.x + 0.25 * end.x, y: 0.25 * start.y + 0.5 * c.y + 0.25 * end.y };
  return {
    d: `M ${start.x} ${start.y} Q ${c.x} ${c.y} ${end.x} ${end.y}`,
    head: `M ${left.x} ${left.y} L ${end.x} ${end.y} L ${right.x} ${right.y}`,
    mid,
  };
}

const pctX = (x: number) => `${(x / W) * 100}%`;
const pctY = (y: number) => `${(y / H) * 100}%`;

interface Props {
  players: Record<string, PlayerCard>;
  xi: number[];
  bench: number[];
  moves: Move[];
  captain: number;
  vice: number;
  rivalName: string | null;
  horizon: number;
  selected: number | null;
  drawKey: string;
  onSelectMove: (index: number | null) => void;
  onOpenPlayer: (id: number) => void;
}

export default function Board({
  players, xi, bench, moves, captain, vice, rivalName, horizon,
  selected, drawKey, onSelectMove, onOpenPlayer,
}: Props) {
  const spots = layout(xi, bench, players, new Set(moves.map((m) => m.in)));
  const rivalInitial = rivalName ? firstName(rivalName).charAt(0).toUpperCase() : null;

  // Players going out sit in the lane, level with their replacement.
  const ghosts: Spot[] = [];
  const perRow = new Map<number, number>();
  moves.forEach((m) => {
    const target = spots.get(m.in);
    const y = target ? target.y : BENCH_Y;
    const k = perRow.get(y) ?? 0;
    perRow.set(y, k + 1);
    ghosts.push({ id: m.out, x: LANE_X, y: y + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 12.5 });
  });

  const incoming = new Map(moves.map((m, i) => [m.in, i]));
  const outgoing = new Map(moves.map((m, i) => [m.out, i]));

  const counter = (spot: Spot, ghost = false) => {
    const p = players[spot.id];
    if (!p) return null;
    const moveIndex = ghost ? outgoing.get(p.id) : incoming.get(p.id);
    const isIn = !ghost && moveIndex !== undefined;
    const lifted = selected !== null && moveIndex === selected;
    const blank = p.games_next === 0;
    const doubt = p.chance_next !== null && p.chance_next < 100;
    const role = p.id === captain && !spot.bench ? "C" : p.id === vice && !spot.bench ? "V" : null;
    const label = [
      p.name,
      `${p.team}, ${p.fixture}`,
      `${fixed(p.xpts_next)} expected points`,
      ghost ? "going out" : isIn ? "coming in" : spot.bench ? "on the bench" : null,
      role === "C" ? "captain" : role === "V" ? "vice-captain" : null,
      p.rival_owns && rivalName ? `${firstName(rivalName)} also owns` : null,
      doubt ? `${p.chance_next}% chance of playing` : null,
      blank ? "no fixture this gameweek" : p.games_next > 1 ? `${p.games_next} fixtures this gameweek` : null,
    ].filter(Boolean).join(", ");

    return (
      <button
        key={`${ghost ? "out" : "in"}-${p.id}`}
        type="button"
        className={[
          styles.counter,
          ghost ? styles.out : isIn ? styles.incoming : styles.mine,
          spot.bench ? styles.benchCounter : "",
          blank ? styles.blank : "",
          lifted ? styles.lifted : "",
        ].join(" ")}
        style={{ left: pctX(spot.x), top: pctY(spot.y) }}
        aria-label={label}
        onClick={() => {
          if (moveIndex !== undefined) onSelectMove(moveIndex);
          onOpenPlayer(p.id);
        }}
      >
        <span className={styles.magnet}>
          <span className={`${styles.xpts} cond`}>{blank ? "—" : fixed(p.xpts_next)}</span>
          {role && <span className={role === "C" ? styles.armband : styles.vice}>{role}</span>}
          {p.games_next > 1 && <span className={styles.double}>×{p.games_next}</span>}
          {p.rival_owns && rivalInitial && !ghost && <span className={styles.shared}>{rivalInitial}</span>}
          {doubt && (
            <span className={styles.doubt}>
              <AlertTriangle size={9} strokeWidth={3} aria-hidden />
            </span>
          )}
        </span>
        <span className={`${styles.name} cond`}>{counterName(p.name)}</span>
      </button>
    );
  };

  return (
    <figure className={styles.frame} aria-label="Your lineup on the tactics board">
      <div className={styles.board}>
        <svg className={styles.lines} viewBox={`0 0 ${W} ${H}`} aria-hidden>
          <rect x={PITCH.x0 - 1} y={2} width={PITCH.x1 - PITCH.x0 + 1} height={91} rx={1.5} />
          <line x1={PITCH.x0 - 1} y1={47.5} x2={PITCH.x1} y2={47.5} />
          <circle cx={(PITCH.x0 + PITCH.x1) / 2} cy={47.5} r={8} />
          <rect x={41} y={2} width={36} height={12} />
          <rect x={41} y={81} width={36} height={12} />
          <line className={styles.laneRule} x1={16.5} y1={3} x2={16.5} y2={115} />
          <line className={styles.benchRule} x1={PITCH.x0 - 1} y1={96} x2={PITCH.x1} y2={96} />
        </svg>

        <span className={`${styles.tag} ${styles.tagOut}`} style={{ left: pctX(LANE_X), top: pctY(3.5) }}>Out</span>
        <span className={`${styles.tag} ${styles.tagSubs}`} style={{ left: pctX(PITCH.x0 + 1), top: pctY(97.5) }}>Subs</span>

        <svg className={styles.ink} viewBox={`0 0 ${W} ${H}`} aria-hidden key={drawKey}>
          {moves.map((m, i) => {
            const from = ghosts[i];
            const to = spots.get(m.in);
            if (!from || !to) return null;
            const a = arrowPath(from, to);
            const dim = selected !== null && selected !== i;
            return (
              <g key={`${m.out}-${m.in}`} className={`${styles.arrow} ${dim ? styles.dim : ""} ${selected === i ? styles.on : ""}`}
                 style={{ animationDelay: `${120 + i * 140}ms` }}>
                <path d={a.d} pathLength={1} />
                <path d={a.head} pathLength={1} />
              </g>
            );
          })}
        </svg>

        {moves.map((m, i) => {
          const from = ghosts[i];
          const to = spots.get(m.in);
          if (!from || !to) return null;
          // Write the gain above the stroke, clear of both counters.
          const lx = (from.x + to.x) / 2;
          const ly = Math.min(from.y, to.y) - R - 4.5;
          return (
            <span
              key={`gain-${m.in}`}
              className={`${styles.gain} ${selected !== null && selected !== i ? styles.dim : ""}`}
              style={{ left: pctX(lx), top: pctY(ly) }}
              aria-hidden
            >
              {signed(m.gain_horizon)}
            </span>
          );
        })}

        {moves.length === 0 && (
          <span className={styles.note} style={{ left: pctX(LANE_X), top: pctY(40) }} aria-hidden>
            Roll it
          </span>
        )}

        {[...spots.values()].map((s) => counter(s))}
        {ghosts.map((g) => counter(g, true))}
      </div>

      <figcaption className={styles.key}>
        <span><b className="cond">5.5</b> expected points next GW</span>
        {moves.length > 0 && <span><i className={styles.keyArrow} aria-hidden /> gain over {horizon} GWs</span>}
        {rivalInitial && <span><i className={styles.keyShared}>{rivalInitial}</i> {firstName(rivalName!)} owns him too</span>}
      </figcaption>
    </figure>
  );
}
