"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { ArrowRight } from "lucide-react";
import { parseTeamId } from "@/lib/api";
import { lastTeam } from "@/lib/settings";
import styles from "./TeamForm.module.css";

export default function TeamForm({ autoFocus = false, compact = false }: { autoFocus?: boolean; compact?: boolean }) {
  const router = useRouter();
  const id = useId();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<{ id: number; name: string | null } | null>(null);

  useEffect(() => setRecent(lastTeam()), []);

  return (
    <div className={`${styles.wrap} ${compact ? styles.compact : ""}`}>
      <form
        className={styles.form}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const team = parseTeamId(value);
          if (!team) {
            setError("That isn't a team ID. It's the number in your Points page link: fantasy.premierleague.com/entry/1234567/…");
            return;
          }
          setError(null);
          setBusy(true);
          router.push(`/team/${team}`);
        }}
      >
        <label htmlFor={id} className={styles.label}>Your FPL team ID</label>
        <div className={styles.row}>
          <input
            id={id}
            className={styles.input}
            inputMode="text"
            autoComplete="off"
            spellCheck={false}
            autoFocus={autoFocus}
            placeholder="1234567, or paste your Points page link"
            value={value}
            aria-invalid={!!error}
            aria-describedby={error ? `${id}-err` : undefined}
            onChange={(e) => { setValue(e.target.value); if (error) setError(null); }}
          />
          <button type="submit" className={styles.submit} disabled={busy}>
            {busy ? "Opening…" : "Plan my week"} <ArrowRight size={18} aria-hidden />
          </button>
        </div>
        {error && <p id={`${id}-err`} className={styles.error} role="alert">{error}</p>}
      </form>
      {recent && !compact && (
        <p className={styles.recent}>
          Or go back to <Link href={`/team/${recent.id}`}>{recent.name ?? `team ${recent.id}`}</Link>
        </p>
      )}
    </div>
  );
}
