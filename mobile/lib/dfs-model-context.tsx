import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { getDfsModel } from '@/lib/api';
import { useWeek } from '@/lib/week-context';

interface DfsModelContextValue {
  model: DfsModel | null;
  loading: boolean;
  error: string | null;
  /** The Classic slate the model is for; null = the server's default (Sunday Main). */
  slateId: string | null;
  selectSlate: (slateId: string) => void;
  refresh: () => void;
}

const DfsModelContext = createContext<DfsModelContextValue | null>(null);

/**
 * The DFS model, shared by the DFS Model, Cash and GPP tabs so it's fetched
 * once per slate (the server takes several seconds to build it). Pull to
 * refresh refetches the current slate.
 */
export function DfsModelProvider({ children }: { children: ReactNode }) {
  const { season, week } = useWeek();
  const [slateId, setSlateId] = useState<string | null>(null);
  const [models, setModels] = useState<Record<string, DfsModel>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refreshing, setRefreshing] = useState<Record<string, number>>({});

  const key = season && week ? `${season}:${week}:${slateId ?? 'default'}` : '';
  const model = key ? models[key] ?? null : null;
  const error = key ? errors[key] ?? null : null;
  const loading = Boolean(key) && ((!model && !error) || Boolean(refreshing[key]));

  useEffect(() => {
    if (!key || !season || !week) return;
    if (models[key] && !refreshing[key]) return;
    let cancelled = false;
    getDfsModel(season, week, slateId)
      .then((m) => {
        if (cancelled) return;
        setModels((all) => ({ ...all, [key]: m }));
        setErrors(({ [key]: _drop, ...rest }) => rest);
      })
      .catch((e) => !cancelled && setErrors((all) => ({ ...all, [key]: e instanceof Error ? e.message : String(e) })))
      .finally(() => !cancelled && setRefreshing(({ [key]: _done, ...rest }) => rest));
    return () => {
      cancelled = true;
    };
    // models is read only to skip refetching what's already loaded
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, refreshing[key]]);

  // Once the server picks its default slate, key the chips to it.
  const resolvedSlateId = slateId ?? model?.slate?.slate_id ?? null;

  const selectSlate = useCallback((id: string) => setSlateId(id), []);
  const refresh = useCallback(() => {
    if (key) setRefreshing((all) => ({ ...all, [key]: Date.now() }));
  }, [key]);

  return (
    <DfsModelContext.Provider value={{ model, loading, error, slateId: resolvedSlateId, selectSlate, refresh }}>
      {children}
    </DfsModelContext.Provider>
  );
}

export function useDfsModel(): DfsModelContextValue {
  const ctx = useContext(DfsModelContext);
  if (!ctx) throw new Error('useDfsModel must be used inside <DfsModelProvider>');
  return ctx;
}
