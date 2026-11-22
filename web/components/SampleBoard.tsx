"use client";

import { useState } from "react";
import Board from "./Board";
import {
  SAMPLE_CAPTAIN, SAMPLE_MOVES, SAMPLE_PLAYERS, SAMPLE_RIVAL, SAMPLE_VICE, SAMPLE_XI,
} from "@/lib/sample";
import { fixed } from "@/lib/format";
import styles from "./SampleBoard.module.css";

/** The landing page's demonstration board. Tapping a counter shows its stat line. */
export default function SampleBoard() {
  const [selected, setSelected] = useState<number | null>(0);
  const [focus, setFocus] = useState<number>(8);
  const p = SAMPLE_PLAYERS[focus];

  return (
    <div className={styles.wrap}>
      <p className={styles.badge}>Sample team</p>
      <Board
        players={SAMPLE_PLAYERS}
        xi={SAMPLE_XI}
        moves={SAMPLE_MOVES}
        captain={SAMPLE_CAPTAIN}
        vice={SAMPLE_VICE}
        rivalName={SAMPLE_RIVAL}
        horizon={6}
        selected={selected}
        drawKey="sample"
        large
        onSelectMove={(i) => setSelected(i)}
        onOpenPlayer={(id) => {
          setFocus(id);
          if (id !== 8 && id !== 12) setSelected(null);
        }}
      />
      <p className={styles.readout} aria-live="polite">
        <b>{p.name}</b> · {p.fixture} · {fixed(p.xpts_next)} xPts · {fixed(p.xmins, 0)} mins · xG/90 {fixed(p.xg90, 2)}
        {p.news ? ` · ${p.news}` : ""}
      </p>
    </div>
  );
}
