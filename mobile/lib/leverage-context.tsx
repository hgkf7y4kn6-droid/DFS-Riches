import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import LeverageExplainer, { type LeverageExplanation } from '@/components/LeverageExplainer';
import { useAccountSync } from '@/lib/account-sync';
import { getSlateLeverage } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

interface LeverageInfo {
  value: number;
  detail: LeverageDetail | null;
}

/** A player to look up: DraftKings id (Showdown Captain and Flex ids differ) or name + team, in `slateId`'s leverage. */
interface LeverageQuery {
  id?: number | null;
  name?: string | null;
  team?: string | null;
  /** The slate the player is listed on; defaults to the slate selected on Home / Lineups. */
  slateId?: string | null;
}

interface LeverageContextValue {
  /** Large-field GPP leverage (Classic) or Captain / Flex leverage (Showdown) for a player on a slate. */
  lookup: (p: LeverageQuery) => LeverageInfo | null;
  /** Ask for a slate's leverage (the first badge on screen does; defaults to the selected slate). Loads once per slate. */
  request: (slateId?: string | null) => void;
  /** Open the explainer for a leverage number (tapping a badge). */
  explain: (e: LeverageExplanation) => void;
}

const LeverageContext = createContext<LeverageContextValue | null>(null);
const nameKey = (name?: string | null, team?: string | null) => `${(name ?? '').toLowerCase()}|${(team ?? '').toUpperCase()}`;

interface SlateMaps {
  byId: Map<number, LeverageInfo>;
  byName: Map<string, LeverageInfo>;
}

/**
 * Leverage for every player on a slate, tied to the slate (not to whichever slate the DFS tabs have open) and shared
 * app-wide so a leverage badge can follow a player's name anywhere he's listed. A Showdown player has two ids, Captain
 * and Flex, each with its own number; a lookup by name alone gets his Flex number. Nothing loads until a badge asks.
 */
export function LeverageProvider({ children }: { children: ReactNode }) {
  const { season, week, selectedSlate } = useWeek();
  const { locked } = useAccountSync();
  const isLocked = locked('leverage');
  const defaultSlate = selectedSlate?.slate_id ?? null;
  // Keys are season:week:slate; held in state so React re-renders when a slate's leverage arrives.
  const [wanted, setWanted] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<Record<string, SlateLeverage>>({});
  const started = useRef(new Set<string>());
  const keyFor = useCallback(
    (slateId?: string | null) => {
      const id = slateId ?? defaultSlate;
      return season && week && id ? `${season}:${week}:${id}` : null;
    },
    [season, week, defaultSlate],
  );

  useEffect(() => {
    if (isLocked) return;
    for (const key of wanted) {
      if (started.current.has(key)) continue;
      started.current.add(key);
      const [s, w, ...rest] = key.split(':');
      getSlateLeverage(Number(s), Number(w), rest.join(':'))
        .then((d) => setLoaded((prev) => ({ ...prev, [key]: d })))
        .catch(() => started.current.delete(key));       // try again the next time a badge asks
    }
  }, [wanted, isLocked]);

  const maps = useMemo(() => {
    const out: Record<string, SlateMaps> = {};
    for (const [key, sl] of Object.entries(loaded)) {
      if (!sl.available) continue;
      const byId = new Map<number, LeverageInfo>();
      const byName = new Map<string, LeverageInfo>();
      const players = (sl.players ?? {}) as SlateLeverage['players'];
      // Resolved from a name alone, a Showdown player is his Flex number: set Captain rows first, Flex rows over them.
      const rows = Object.entries(players).sort(([, a], [, b]) => Number(a.slot === 'FLEX') - Number(b.slot === 'FLEX'));
      for (const [id, p] of rows) {
        const info = { value: p.leverage, detail: p.leverage_detail ?? null };
        byId.set(Number(id), info);
        byName.set(nameKey(p.name, p.team), info);
      }
      out[key] = { byId, byName };
    }
    return out;
  }, [loaded]);

  const lookup = useCallback<LeverageContextValue['lookup']>(
    (p) => {
      const key = keyFor(p.slateId);
      const m = key ? maps[key] : undefined;
      if (!m) return null;
      return (p.id != null ? m.byId.get(p.id) : undefined) ?? m.byName.get(nameKey(p.name, p.team)) ?? null;
    },
    [maps, keyFor],
  );
  const request = useCallback(
    (slateId?: string | null) => {
      const key = keyFor(slateId);
      if (key) setWanted((prev) => (prev.includes(key) ? prev : [...prev, key]));
    },
    [keyFor],
  );
  // One explainer for every badge on screen.
  const [shown, setShown] = useState<LeverageExplanation | null>(null);
  const explain = useCallback((e: LeverageExplanation) => setShown(e), []);
  return (
    <LeverageContext.Provider value={{ lookup, request, explain }}>
      {children}
      <LeverageExplainer shown={shown} onClose={() => setShown(null)} />
    </LeverageContext.Provider>
  );
}

export function useLeverage(): LeverageContextValue {
  const ctx = useContext(LeverageContext);
  if (!ctx) throw new Error('useLeverage must be used inside <LeverageProvider>');
  return ctx;
}
