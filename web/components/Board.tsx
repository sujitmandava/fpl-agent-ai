"use client";

import { AlertTriangle, ArrowRight } from "lucide-react";
import type { CSSProperties } from "react";
import type { Move, PlayerCard, Pos } from "@/lib/types";
import { counterName, firstName, fixed, signed } from "@/lib/format";
import styles from "./Board.module.css";

// Board coordinates: 100 wide × 98 tall. A lane on the left holds players going
// out; the pitch runs GK (top) to forwards. Subs live in their own strip.
const W = 100;
const H = 98;
const LANE_X = 8.5;
const PITCH = { x0: 19, x1: 99 };
const ROW_Y: Record<Pos, number> = { GK: 12, DEF: 35, MID: 58, FWD: 81 };
const R = 5.4; // counter radius in board units (arrows stop at the rim)

type Spot = { id: number; x: number; y: number };

function layout(xi: number[], players: Record<string, PlayerCard>, incoming: Set<number>) {
  const rows: Record<Pos, number[]> = { GK: [], DEF: [], MID: [], FWD: [] };
  for (const id of xi) {
    const p = players[id];
    if (p) rows[p.pos].push(id);
  }
  const spots: Spot[] = [];
  const span = PITCH.x1 - PITCH.x0;
  for (const pos of Object.keys(rows) as Pos[]) {
    // New signings stand nearest the "Out" lane, so each arrow stays short.
    const ids = rows[pos].sort((a, b) => Number(incoming.has(b)) - Number(incoming.has(a)));
    ids.forEach((id, i) => spots.push({ id, x: PITCH.x0 + ((i + 0.5) * span) / ids.length, y: ROW_Y[pos] }));
  }
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
  const bow = Math.min(9, len * 0.22); // bow the stroke like a hand-drawn arc
  const c = { x: (start.x + end.x) / 2 + uy * bow, y: (start.y + end.y) / 2 - ux * bow };
  const tx = end.x - c.x;
  const ty = end.y - c.y;
  const tl = Math.hypot(tx, ty) || 1;
  const hx = tx / tl;
  const hy = ty / tl;
  const head = 3.2;
  const left = { x: end.x - hx * head - hy * head * 0.7, y: end.y - hy * head + hx * head * 0.7 };
  const right = { x: end.x - hx * head + hy * head * 0.7, y: end.y - hy * head - hx * head * 0.7 };
  return {
    d: `M ${start.x} ${start.y} Q ${c.x} ${c.y} ${end.x} ${end.y}`,
    head: `M ${left.x} ${left.y} L ${end.x} ${end.y} L ${right.x} ${right.y}`,
  };
}

const pctX = (x: number) => `${(x / W) * 100}%`;
const pctY = (y: number) => `${(y / H) * 100}%`;

// -- One magnet -----------------------------------------------------------------

type Kind = "mine" | "incoming" | "out";

interface CounterProps {
  p: PlayerCard;
  kind: Kind;
  role?: "C" | "V" | null;
  small?: boolean;
  rivalName: string | null;
  lifted?: boolean;
  style?: CSSProperties;
  onClick: () => void;
}

function Counter({ p, kind, role = null, small = false, rivalName, lifted = false, style, onClick }: CounterProps) {
  const blank = p.games_next === 0;
  const doubt = p.chance_next !== null && p.chance_next < 100;
  const rivalInitial = rivalName ? firstName(rivalName).charAt(0).toUpperCase() : null;
  const label = [
    p.name,
    `${p.team}, ${p.fixture}`,
    `${fixed(p.xpts_next)} expected points`,
    kind === "out" ? "going out" : kind === "incoming" ? "coming in" : small ? "on the bench" : null,
    role === "C" ? "captain" : role === "V" ? "vice-captain" : null,
    p.rival_owns && rivalName ? `${firstName(rivalName)} also owns` : null,
    doubt ? `${p.chance_next}% chance of playing` : null,
    blank ? "no fixture this gameweek" : p.games_next > 1 ? `${p.games_next} fixtures this gameweek` : null,
  ].filter(Boolean).join(", ");

  return (
    <button
      type="button"
      className={[
        styles.counter, styles[kind], small ? styles.small : "", style ? styles.placed : "",
        blank ? styles.blank : "", lifted ? styles.lifted : "",
      ].join(" ")}
      style={style}
      aria-label={label}
      onClick={onClick}
    >
      <span className={styles.magnet}>
        <span className={`${styles.xpts} cond`}>{blank ? "—" : fixed(p.xpts_next)}</span>
        {role && <span className={role === "C" ? styles.armband : styles.vice}>{role}</span>}
        {p.games_next > 1 && <span className={styles.double}>×{p.games_next}</span>}
        {p.rival_owns && rivalInitial && kind !== "out" && <span className={styles.shared}>{rivalInitial}</span>}
        {doubt && (
          <span className={styles.doubt}>
            <AlertTriangle size={9} strokeWidth={3} aria-hidden />
          </span>
        )}
      </span>
      <span className={`${styles.name} cond`}>{counterName(p.name)}</span>
    </button>
  );
}

// -- The board ------------------------------------------------------------------

interface BoardProps {
  players: Record<string, PlayerCard>;
  xi: number[];
  moves: Move[];
  captain: number;
  vice: number;
  rivalName: string | null;
  horizon: number;
  selected: number | null;
  drawKey: string;
  /** Persuade surfaces write the marker annotations larger. */
  large?: boolean;
  onSelectMove: (index: number | null) => void;
  onOpenPlayer: (id: number) => void;
}

export default function Board({
  players, xi, moves, captain, vice, rivalName, horizon,
  selected, drawKey, large = false, onSelectMove, onOpenPlayer,
}: BoardProps) {
  const spots = layout(xi, players, new Set(moves.map((m) => m.in)));

  // Only moves whose new player starts are drawn here; bench signings show in the subs strip.
  const drawn = moves
    .map((m, i) => ({ m, i, to: spots.get(m.in) }))
    .filter((d): d is { m: Move; i: number; to: Spot } => !!d.to && !!players[d.m.out]);
  const perRow = new Map<number, number>();
  const ghosts = drawn.map(({ to }) => {
    const k = perRow.get(to.y) ?? 0;
    perRow.set(to.y, k + 1);
    return { x: LANE_X, y: to.y + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 12.5 };
  });
  const moveOfIn = new Map(moves.map((m, i) => [m.in, i]));
  const gainLift = large ? 6.5 : 4.5;

  return (
    <figure className={`${styles.frame} ${large ? styles.large : ""}`} aria-label="Your lineup on the tactics board">
      <div className={styles.board}>
        <svg className={styles.lines} viewBox={`0 0 ${W} ${H}`} aria-hidden>
          <rect x={PITCH.x0 - 1} y={2} width={PITCH.x1 - PITCH.x0 + 1} height={91} rx={1.5} />
          <line x1={PITCH.x0 - 1} y1={47.5} x2={PITCH.x1} y2={47.5} />
          <circle cx={(PITCH.x0 + PITCH.x1) / 2} cy={47.5} r={8} />
          <rect x={41} y={2} width={36} height={12} />
          <rect x={41} y={81} width={36} height={12} />
          <line className={styles.laneRule} x1={16.5} y1={3} x2={16.5} y2={95} />
        </svg>

        <span className={styles.tag} style={{ left: pctX(LANE_X), top: pctY(3.5) }}>Out</span>

        <svg className={styles.ink} viewBox={`0 0 ${W} ${H}`} aria-hidden key={drawKey}>
          {drawn.map(({ m, i, to }, k) => {
            const a = arrowPath(ghosts[k], to);
            const dim = selected !== null && selected !== i;
            return (
              <g key={`${m.out}-${m.in}`} className={`${styles.arrow} ${dim ? styles.dim : ""} ${selected === i ? styles.on : ""}`}
                 style={{ animationDelay: `${120 + k * 140}ms` }}>
                <path d={a.d} pathLength={1} />
                <path d={a.head} pathLength={1} />
              </g>
            );
          })}
        </svg>

        {drawn.map(({ m, i, to }, k) => (
          <span
            key={`gain-${m.in}`}
            className={`${styles.gain} ${selected !== null && selected !== i ? styles.dim : ""}`}
            style={{ left: pctX((ghosts[k].x + to.x) / 2), top: pctY(Math.min(ghosts[k].y, to.y) - R - gainLift) }}
            aria-hidden
          >
            {signed(m.gain_horizon)}
          </span>
        ))}

        {moves.length === 0 && (
          <span className={styles.note} style={{ left: pctX(LANE_X), top: pctY(40) }} aria-hidden>Roll it</span>
        )}

        {[...spots.values()].map((s) => {
          const p = players[s.id];
          if (!p) return null;
          const mi = moveOfIn.get(p.id);
          return (
            <Counter
              key={`in-${p.id}`}
              p={p}
              kind={mi !== undefined ? "incoming" : "mine"}
              role={p.id === captain ? "C" : p.id === vice ? "V" : null}
              rivalName={rivalName}
              lifted={selected !== null && mi === selected}
              style={{ left: pctX(s.x), top: pctY(s.y) }}
              onClick={() => { if (mi !== undefined) onSelectMove(mi); onOpenPlayer(p.id); }}
            />
          );
        })}
        {drawn.map(({ m, i }, k) => (
          <Counter
            key={`out-${m.out}`}
            p={players[m.out]}
            kind="out"
            rivalName={rivalName}
            lifted={selected === i}
            style={{ left: pctX(ghosts[k].x), top: pctY(ghosts[k].y) }}
            onClick={() => { onSelectMove(i); onOpenPlayer(m.out); }}
          />
        ))}
      </div>

      <figcaption className={styles.key}>
        <span><b className="cond">5.5</b> expected points next GW</span>
        {moves.length > 0 && <span><i className={styles.keyArrow} aria-hidden /> gain over {horizon} GWs</span>}
        {rivalName && (
          <span><i className={styles.keyShared}>{firstName(rivalName).charAt(0).toUpperCase()}</i> {firstName(rivalName)} owns him too</span>
        )}
      </figcaption>
    </figure>
  );
}

// -- Subs strip -----------------------------------------------------------------

export function Bench({ players, bench, moves, rivalName, onOpenPlayer }: {
  players: Record<string, PlayerCard>;
  bench: number[];
  moves: Move[];
  rivalName: string | null;
  onOpenPlayer: (id: number) => void;
}) {
  const incoming = new Map(moves.map((m) => [m.in, m]));
  return (
    <section className={styles.bench} aria-label="Substitutes in order">
      <h3 className={styles.benchHead}>Subs, in order</h3>
      <ol className={styles.benchRow}>
        {bench.map((id) => {
          const p = players[id];
          if (!p) return null;
          const m = incoming.get(id);
          const out = m ? players[m.out] : undefined;
          return (
            <li key={id} className={styles.benchItem}>
              {out && (
                <>
                  <Counter p={out} kind="out" small rivalName={rivalName} onClick={() => onOpenPlayer(out.id)} />
                  <ArrowRight className={styles.benchArrow} size={16} strokeWidth={2.5} aria-hidden />
                </>
              )}
              <Counter p={p} kind={m ? "incoming" : "mine"} small rivalName={rivalName} onClick={() => onOpenPlayer(id)} />
            </li>
          );
        })}
      </ol>
    </section>
  );
}
