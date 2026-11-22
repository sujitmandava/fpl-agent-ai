"use client";

import { useCallback, useEffect, useState } from "react";

// Per-team settings live in this browser only (there are no accounts).
export interface TeamSettings {
  horizon: number;
  chip: "none" | "wildcard" | "freehit";
  freeTransfers: number | null; // one-off override; null = from public data
  bank: number | null;          // £m; null = from public data
  ftValue: number;
  benchWeight: number;
  consistency: number;
  locked: number[];
  banned: number[];
  league: number | null;
  rival: number | null;
}

export const DEFAULT_SETTINGS: TeamSettings = {
  horizon: 6,
  chip: "none",
  freeTransfers: null,
  bank: null,
  ftValue: 1,
  benchWeight: 0.1,
  consistency: 0.5,
  locked: [],
  banned: [],
  league: null,
  rival: null,
};

const key = (teamId: number) => `fpl-agent:team:${teamId}`;

function read(teamId: number): TeamSettings {
  try {
    const raw = window.localStorage.getItem(key(teamId));
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

/** Settings for one team, persisted to localStorage when it's available. */
export function useTeamSettings(teamId: number) {
  const [settings, setSettings] = useState<TeamSettings>(DEFAULT_SETTINGS);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSettings(read(teamId));
    setReady(true);
  }, [teamId]);

  const update = useCallback(
    (patch: Partial<TeamSettings>) => {
      setSettings((prev) => {
        const next = { ...prev, ...patch };
        try {
          window.localStorage.setItem(key(teamId), JSON.stringify(next));
        } catch {
          /* private mode or storage blocked: keep it for this visit only */
        }
        return next;
      });
    },
    [teamId],
  );

  return { settings, update, ready };
}

/** Remember the last team opened, so the landing page can offer it again. */
export function rememberTeam(teamId: number, name: string | null) {
  try {
    window.localStorage.setItem("fpl-agent:last-team", JSON.stringify({ id: teamId, name }));
  } catch {
    /* ignore */
  }
}

export function lastTeam(): { id: number; name: string | null } | null {
  try {
    const raw = window.localStorage.getItem("fpl-agent:last-team");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
