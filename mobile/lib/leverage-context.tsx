import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { usePlays } from '@/lib/plays';

interface LeverageInfo {
  value: number;
  detail: LeverageDetail | null;
}

interface LeverageContextValue {
  /** GPP leverage for a player on the DFS model's slate, by DK draftable id or name + team. */
  lookup: (p: { id?: number | null; name?: string | null; team?: string | null }) => LeverageInfo | null;
  /** Ask for the data (the first badge on screen does); loads the GPP plays once per slate. */
  request: () => void;
}

const LeverageContext = createContext<LeverageContextValue | null>(null);
const nameKey = (name?: string | null, team?: string | null) => `${(name ?? '').toLowerCase()}|${(team ?? '').toUpperCase()}`;

/**
 * Tournament (large-field GPP) leverage for every player on the current DFS
 * model slate, shared app-wide so a leverage badge can follow a player's
 * name anywhere he's listed. Nothing loads until a badge asks.
 */
export function LeverageProvider({ children }: { children: ReactNode }) {
  const [wanted, setWanted] = useState(false);
  const { data } = usePlays('gpp', wanted);
  const maps = useMemo(() => {
    const byId = new Map<number, LeverageInfo>();
    const byName = new Map<string, LeverageInfo>();
    for (const p of data?.available ? data.players : []) {
      if (p.leverage == null) continue;
      const info = { value: p.leverage, detail: p.leverage_detail ?? null };
      byId.set(p.id, info);
      byName.set(nameKey(p.name, p.team), info);
    }
    return { byId, byName };
  }, [data]);
  const lookup = useCallback<LeverageContextValue['lookup']>(
    (p) => (p.id != null ? maps.byId.get(p.id) : undefined) ?? maps.byName.get(nameKey(p.name, p.team)) ?? null,
    [maps],
  );
  const request = useCallback(() => setWanted(true), []);
  return <LeverageContext.Provider value={{ lookup, request }}>{children}</LeverageContext.Provider>;
}

export function useLeverage(): LeverageContextValue {
  const ctx = useContext(LeverageContext);
  if (!ctx) throw new Error('useLeverage must be used inside <LeverageProvider>');
  return ctx;
}
