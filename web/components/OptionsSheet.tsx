"use client";

import { ChevronDown, RefreshCw } from "lucide-react";
import type { Chip } from "@/lib/types";
import { DEFAULT_SETTINGS, type TeamSettings } from "@/lib/settings";
import Sheet from "./Sheet";
import styles from "./OptionsSheet.module.css";

interface Props {
  open: boolean;
  settings: TeamSettings;
  chips: Chip[];
  publicFreeTransfers: number | null;
  publicBank: number | null;
  onChange: (patch: Partial<TeamSettings>) => void;
  onRefresh: () => void;
  onClose: () => void;
}

export default function OptionsSheet({
  open, settings: s, chips, publicFreeTransfers, publicBank, onChange, onRefresh, onClose,
}: Props) {
  const available = (name: string) => chips.some((c) => c.name === name && c.status === "available");
  const chipChoices = [
    { value: "none", label: "No chip" },
    ...(available("wildcard") ? [{ value: "wildcard", label: "Wildcard" }] : []),
    ...(available("freehit") ? [{ value: "freehit", label: "Free Hit" }] : []),
  ] as const;

  return (
    <Sheet open={open} onClose={onClose} title="Plan options">
      <form className={styles.form} onSubmit={(e) => e.preventDefault()}>
        <fieldset className={styles.field}>
          <legend>Plan ahead</legend>
          <div className={styles.horizon} role="radiogroup" aria-label="Gameweeks to plan over">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
              <label key={n} className={styles.seg}>
                <input type="radio" name="horizon" checked={s.horizon === n} onChange={() => onChange({ horizon: n })} />
                <span>{n}</span>
              </label>
            ))}
          </div>
          <p className={styles.help}>Gameweeks. Longer favours fixtures; shorter favours this week.</p>
        </fieldset>

        <fieldset className={styles.field}>
          <legend>Chip this week</legend>
          <div className={styles.segment}>
            {chipChoices.map((c) => (
              <label key={c.value} className={styles.seg}>
                <input type="radio" name="chip" checked={s.chip === c.value}
                       onChange={() => onChange({ chip: c.value as TeamSettings["chip"] })} />
                <span>{c.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className={styles.field}>
          <legend>Already made transfers?</legend>
          <p className={styles.help}>
            Public data can&apos;t see moves made for this deadline. If you&apos;ve made some, set what&apos;s left.
          </p>
          <div className={styles.pair}>
            <label className={styles.control}>
              <span>Free transfers</span>
              <select
                value={s.freeTransfers ?? ""}
                onChange={(e) => onChange({ freeTransfers: e.target.value === "" ? null : Number(e.target.value) })}
              >
                <option value="">{publicFreeTransfers ?? "—"} (from FPL)</option>
                {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className={styles.control}>
              <span>Bank (£m)</span>
              <input
                type="number" inputMode="decimal" min={0} max={100} step={0.1}
                placeholder={publicBank != null ? `${publicBank.toFixed(1)} (from FPL)` : ""}
                value={s.bank ?? ""}
                onChange={(e) => onChange({ bank: e.target.value === "" ? null : Number(e.target.value) })}
              />
            </label>
          </div>
        </fieldset>

        <details className={styles.advanced}>
          <summary>Fine-tuning <ChevronDown className={styles.chev} size={18} aria-hidden /></summary>
          <Range label="Value of saving a transfer" hint="Higher means fewer, surer moves." min={0} max={3} step={0.25}
                 value={s.ftValue} onChange={(v) => onChange({ ftValue: v })} />
          <Range label="Bench weight" hint="How much bench points count, for auto-subs." min={0} max={0.5} step={0.05}
                 value={s.benchWeight} onChange={(v) => onChange({ benchWeight: v })} />
          <Range label="Prefer steady returners" hint="0 is pure expected points; higher favours players who return week after week."
                 min={0} max={2} step={0.25} value={s.consistency} onChange={(v) => onChange({ consistency: v })} />
        </details>

        <div className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onRefresh}>
            <RefreshCw size={16} aria-hidden /> Refresh from FPL
          </button>
          <button
            type="button"
            className={styles.link}
            onClick={() => onChange({ ...DEFAULT_SETTINGS, locked: s.locked, banned: s.banned, league: s.league, rival: s.rival })}
          >
            Reset options
          </button>
        </div>
      </form>
    </Sheet>
  );
}

function Range({ label, hint, min, max, step, value, onChange }: {
  label: string; hint: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void;
}) {
  return (
    <label className={styles.range}>
      <span className={styles.rangeHead}><span>{label}</span><output>{value}</output></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <span className={styles.help}>{hint}</span>
    </label>
  );
}
