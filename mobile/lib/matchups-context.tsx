import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { getDefenseVsPosition } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

const MODE_KEY = 'dfsriches:matchup-mode:v1';

export interface Matchup extends MatchupMetrics {
  /** The team being ranked: the defense, or for a DST the opposing offense. */
  team: string;
  position: string;
  games: number;
  teams: number;
  effLabel: string;
  mode: MatchupMode;
}

interface MatchupsValue {
  mode: MatchupMode;
  setMode: (mode: MatchupMode) => void;
  data: DefenseVsPosition | null;
  /** The opponent's rank against this position in the current mode; null if unknown. */
  lookup: (opponent: string | null | undefined, position: string | null | undefined) => Matchup | null;
}

const MatchupsContext = createContext<MatchupsValue | null>(null);

/**
 * Defense-vs-position ranks for the current week, loaded once, and the
 * user's choice of raw or strength-of-schedule adjusted (saved on the device).
 */
export function MatchupsProvider({ children }: { children: ReactNode }) {
  const { season, week } = useWeek();
  const [mode, setModeState] = useState<MatchupMode>('raw');
  const [fetched, setFetched] = useState<{ key: string; data: DefenseVsPosition } | null>(null);
  const key = season && week ? `${season}:${week}` : '';

  useEffect(() => {
    AsyncStorage.getItem(MODE_KEY)
      .then((m) => (m === 'adj' || m === 'raw') && setModeState(m))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!season || !week || fetched?.key === key) return;
    let cancelled = false;
    getDefenseVsPosition(season, week)
      .then((d) => !cancelled && setFetched({ key, data: d }))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [season, week, key, fetched?.key]);

  const data = fetched?.key === key ? fetched.data : null;
  const value = useMemo<MatchupsValue>(
    () => ({
      mode,
      setMode: (m) => {
        setModeState(m);
        AsyncStorage.setItem(MODE_KEY, m).catch(() => {});
      },
      data,
      lookup: (opponent, position) => {
        const pos = (position ?? '').toUpperCase();
        const opp = (opponent ?? '').toUpperCase();
        const entry = data?.teams[opp]?.[pos];
        if (!data || !entry) return null;
        return {
          ...entry[mode],
          team: opp,
          position: pos,
          games: entry.games,
          teams: data.league[pos]?.teams ?? 32,
          effLabel: data.efficiency[pos] ?? 'eff',
          mode,
        };
      },
    }),
    [mode, data],
  );

  return <MatchupsContext.Provider value={value}>{children}</MatchupsContext.Provider>;
}

export function useMatchups() {
  const ctx = useContext(MatchupsContext);
  if (!ctx) throw new Error('useMatchups must be used inside MatchupsProvider');
  return ctx;
}

export const ordinal = (n: number) => {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`;
};

export type MatchupTone = 'soft' | 'neutral' | 'tough';

/** Ranks run 1 (allows the least) to 32 (allows the most). Soft = top third by what they allow; tough = bottom third. */
export function matchupTone(rank: number, teams: number): MatchupTone {
  if (rank > teams - Math.round(teams / 3)) return 'soft';
  if (rank <= Math.round(teams / 3)) return 'tough';
  return 'neutral';
}

/** Matchup strength for sorting: the average of the points and efficiency ranks (higher = softer). */
export const matchupScore = (m: { fp_rank: number; eff_rank: number }) => (m.fp_rank + m.eff_rank) / 2;
