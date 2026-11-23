"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchPlan } from "./api";
import { rememberTeam, useTeamSettings } from "./settings";
import type { Plan } from "./types";

/** The team's plan for its saved settings; re-fetches when they change. The API
 *  caches finished plans, so switching between sections doesn't re-solve. */
export function usePlan(teamId: number) {
  const { settings, update, ready } = useTeamSettings(teamId);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [fresh, setFresh] = useState(0);

  useEffect(() => {
    if (!ready) return;
    const ctrl = new AbortController();
    setLoading(true);
    fetchPlan(teamId, settings, ctrl.signal, fresh > 0)
      .then((p) => {
        setPlan(p);
        setError(null);
        rememberTeam(teamId, p.team.name);
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof ApiError ? e : new ApiError(String(e), 0));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [teamId, settings, ready, fresh]);

  const refresh = useCallback(() => setFresh((n) => n + 1), []);
  return { plan, error, loading, settings, update, refresh };
}
