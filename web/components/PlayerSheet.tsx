"use client";

import { Lock, Ban } from "lucide-react";
import type { PlayerCard } from "@/lib/types";
import { firstName, fixed, money, pct } from "@/lib/format";
import Sheet from "./Sheet";
import styles from "./PlayerSheet.module.css";

interface Props {
  player: PlayerCard | null;
  horizon: number[];
  rivalName: string | null;
  locked: boolean;
  banned: boolean;
  onToggleLock: () => void;
  onToggleBan: () => void;
  onClose: () => void;
}

export default function PlayerSheet({
  player, horizon, rivalName, locked, banned, onToggleLock, onToggleBan, onClose,
}: Props) {
  const p = player;
  return (
    <Sheet open={!!p} onClose={onClose} title={p ? p.name : "Player"}>
      {p && (
        <div className={styles.wrap}>
          <p className={styles.sub}>
            {p.full_name} · {p.team} · {p.pos} · {money(p.price)}
            {p.selling_price != null && p.selling_price !== p.price && <> (sells for {money(p.selling_price)})</>}
          </p>

          {p.news && <p className={styles.news}>{p.news}</p>}

          <div className={styles.headline}>
            <div>
              <span className={`${styles.big} cond`}>{fixed(p.xpts_next)}</span>
              <span className={styles.cap}>expected points next GW · {p.fixture}{p.games_next > 1 ? ` (${p.games_next} games)` : ""}</span>
            </div>
            <div>
              <span className={`${styles.big} cond`}>{fixed(p.xpts_horizon)}</span>
              <span className={styles.cap}>over {horizon.length} GWs</span>
            </div>
          </div>

          <dl className={styles.stats}>
            <div><dt>xMins</dt><dd>{fixed(p.xmins, 0)}</dd></div>
            <div><dt>xG/90</dt><dd>{fixed(p.xg90, 2)}</dd></div>
            <div><dt>xA/90</dt><dd>{fixed(p.xa90, 2)}</dd></div>
            <div><dt>DC chance</dt><dd>{p.dc_rate == null ? "—" : pct(p.dc_rate)}</dd></div>
            <div><dt>Clean sheet</dt><dd>{pct(p.cs_next)}</dd></div>
            <div><dt>Return chance</dt><dd>{pct(p.p_return_next)}</dd></div>
            <div><dt>Returned in</dt><dd>{p.returns ?? "—"}</dd></div>
            <div><dt>Owned overall</dt><dd>{p.selected_by == null ? "—" : `${p.selected_by.toFixed(1)}%`}</dd></div>
            <div><dt>League EO</dt><dd>{p.league_eo == null ? "—" : `${Math.round(p.league_eo)}%`}</dd></div>
          </dl>

          <table className={styles.gws}>
            <caption>Expected points by gameweek</caption>
            <thead><tr>{horizon.map((g) => <th key={g} scope="col">GW{g}</th>)}</tr></thead>
            <tbody><tr>{horizon.map((g) => <td key={g}>{fixed(p.xpts_by_gw[g])}</td>)}</tr></tbody>
          </table>

          {rivalName && (
            <p className={styles.rival}>
              {p.rival_owns
                ? `${firstName(rivalName)} owns him too, so his points don't change the gap.`
                : `${firstName(rivalName)} doesn't own him: his points move the gap.`}
            </p>
          )}

          <div className={styles.actions}>
            <button type="button" aria-pressed={locked} onClick={onToggleLock} className={styles.toggle}>
              <Lock size={16} aria-hidden /> {locked ? "Always keep: on" : "Always keep"}
            </button>
            <button type="button" aria-pressed={banned} onClick={onToggleBan} className={styles.toggle}>
              <Ban size={16} aria-hidden /> {banned ? "Never pick: on" : "Never pick"}
            </button>
          </div>
          <p className={styles.hint}>Saved in this browser. The plan re-solves when you change them.</p>
        </div>
      )}
    </Sheet>
  );
}
