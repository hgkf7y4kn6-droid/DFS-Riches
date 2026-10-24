import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { useAccountSync } from '@/lib/account-sync';
import { track } from '@/lib/analytics';
import { getProPicks, saveProPicks } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

interface ProPicksValue {
  /** This week's Pro Picks (the NFL's current week, whatever week the app is viewing). */
  state: ProPicksState | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  /** Saves the rankings; resolves to an error message, or null when saved. */
  save: (picks: Partial<Record<PickPosition, number[]>>, name: string) => Promise<string | null>;
  /** The full-screen picks editor (components/ProPicksEditor), opened from the Home card or the reminder. */
  editorOpen: boolean;
  setEditorOpen: (open: boolean) => void;
}

const ProPicksContext = createContext<ProPicksValue | null>(null);

/** Weekly Pro Picks for the signed-in user (app/competition.py on the server). */
export function ProPicksProvider({ children }: { children: ReactNode }) {
  const { current } = useWeek();
  const { userId } = useAccountSync();
  const [state, setState] = useState<ProPicksState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  // Loading while the newest request (week, account, refresh) hasn't answered yet.
  const requestKey = current && userId ? `${current.season}:${current.week}:${userId}:${nonce}` : null;
  const [answeredKey, setAnsweredKey] = useState<string | null>(null);
  const loading = requestKey != null && answeredKey !== requestKey;

  useEffect(() => {
    if (!current || !userId || !requestKey) return;
    let cancelled = false;
    getProPicks(current.season, current.week)
      .then((s) => {
        if (cancelled) return;
        setState(s);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setAnsweredKey(requestKey));
    return () => {
      cancelled = true;
    };
  }, [current, userId, requestKey]);

  const save = useCallback(
    async (picks: Partial<Record<PickPosition, number[]>>, name: string) => {
      if (!state) return 'Pro Picks are still loading.';
      try {
        const { mine } = await saveProPicks(state.season, state.week, picks, name);
        const first = !state.mine;
        setState((s) => (s ? { ...s, mine, entrants: s.entrants + (first ? 1 : 0) } : s));
        track('pro_picks_saved', { first, ranked: Object.values(picks).reduce((n, ids) => n + (ids?.length ?? 0), 0) });
        return null;
      } catch (e) {
        return (e as Error).message;
      }
    },
    [state],
  );

  const value = useMemo(
    () => ({ state, loading, error, refresh: () => setNonce((n) => n + 1), save, editorOpen, setEditorOpen }),
    [state, loading, error, save, editorOpen],
  );
  return <ProPicksContext.Provider value={value}>{children}</ProPicksContext.Provider>;
}

export function useProPicks(): ProPicksValue {
  const ctx = useContext(ProPicksContext);
  if (!ctx) throw new Error('useProPicks must be used inside ProPicksProvider');
  return ctx;
}

export const PICK_POSITIONS: PickPosition[] = ['QB', 'RB', 'WR', 'TE', 'DST'];

/** How many players the entry ranks, out of every spot. */
export function rankedCount(state: ProPicksState | null, picks?: Partial<Record<PickPosition, number[]>>): { ranked: number; total: number } {
  const sizes = state?.sizes;
  const total = sizes ? PICK_POSITIONS.reduce((n, p) => n + sizes[p], 0) : 0;
  const ranked = PICK_POSITIONS.reduce((n, p) => n + (picks?.[p]?.length ?? 0), 0);
  return { ranked, total };
}
