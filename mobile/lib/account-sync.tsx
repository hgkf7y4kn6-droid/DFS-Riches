import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '@clerk/expo';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { getAccount, putAccountDoc } from '@/lib/api';

type Status = 'signed-out' | 'loading' | 'synced' | 'saving' | 'offline' | 'error';

interface AccountSyncValue {
  userId: string | null;
  status: Status;
  error: string | null;
  master: boolean;
  storage: AccountData['storage'] | null;
  lastSynced: string | null;
  /** The account's copy of each document, loaded once per sign-in (null until then). */
  remote: AccountData['data'] | null;
  push: (key: SyncKey, value: unknown) => void;
  /** Pull the account's latest copy again (e.g. after changes on another device). */
  refresh: () => void;
}

const AccountSyncContext = createContext<AccountSyncValue | null>(null);
const LINKED = (key: SyncKey) => `dfsriches:sync-linked:${key}`;
const PUSH_DELAY_MS = 800;

/**
 * Keeps saved lineups, contest entries, pool tags and settings on the
 * signed-in user's account (the server stores them in Neon Postgres, with a
 * compact copy in Clerk metadata), so they follow the user to any device.
 * Signed out, everything stays on the device as before.
 */
export function AccountSyncProvider({ children }: { children: ReactNode }) {
  const { isSignedIn, userId, getToken } = useAuth();
  // Held per user id, so signing out or switching accounts never shows stale data.
  const [account, setAccount] = useState<AccountData | null>(null);
  const [failure, setFailure] = useState<{ userId: string; message: string } | null>(null);
  const [saving, setSaving] = useState(0);
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const timers = useRef<Partial<Record<SyncKey, ReturnType<typeof setTimeout>>>>({});
  const me = isSignedIn && userId ? userId : null;
  // Clerk's getToken changes identity between renders; read it through a ref
  // so the account isn't re-fetched on every render.
  const tokenRef = useRef(getToken);
  useEffect(() => {
    tokenRef.current = getToken;
  }, [getToken]);

  useEffect(() => {
    if (!me) return;
    let cancelled = false;
    tokenRef.current()
      .then((token) => {
        if (!token) throw new Error('no session token');
        return getAccount(token);
      })
      .then((a) => {
        if (cancelled) return;
        setAccount(a);
        setFailure(null);
        setLastSynced(new Date().toISOString());
      })
      .catch((e) => !cancelled && setFailure({ userId: me, message: e instanceof Error ? e.message : String(e) }));
    return () => {
      cancelled = true;
    };
  }, [me, nonce]);

  const mine = account && account.user_id === me ? account : null;

  const push = useCallback(
    (key: SyncKey, value: unknown) => {
      if (!me || mine?.storage === 'none') return;
      const pending = timers.current[key];
      if (pending) clearTimeout(pending);
      timers.current[key] = setTimeout(async () => {
        setSaving((n) => n + 1);
        try {
          const token = await tokenRef.current();
          if (!token) throw new Error('no session token');
          await putAccountDoc(token, key, value, new Date().toISOString());
          setFailure(null);
          setLastSynced(new Date().toISOString());
        } catch (e) {
          setFailure({ userId: me, message: e instanceof Error ? e.message : String(e) });
        } finally {
          setSaving((n) => n - 1);
        }
      }, PUSH_DELAY_MS);
    },
    [me, mine?.storage],
  );

  const value = useMemo<AccountSyncValue>(() => {
    const err = failure && failure.userId === me ? failure.message : null;
    const status: Status = !me
      ? 'signed-out'
      : err
        ? 'error'
        : saving > 0
          ? 'saving'
          : !mine
            ? 'loading'
            : mine.storage === 'none'
              ? 'offline'
              : 'synced';
    return {
      userId: me,
      status,
      error: err ?? (mine?.storage === 'none' ? 'Account storage is not set up on the server yet.' : null),
      master: mine?.master ?? false,
      storage: mine?.storage ?? null,
      lastSynced,
      remote: mine ? mine.data : null,
      push,
      refresh: () => setNonce((n) => n + 1),
    };
  }, [me, failure, saving, mine, lastSynced, push]);

  return <AccountSyncContext.Provider value={value}>{children}</AccountSyncContext.Provider>;
}

export function useAccountSync() {
  const ctx = useContext(AccountSyncContext);
  if (!ctx) throw new Error('useAccountSync must be used inside AccountSyncProvider');
  return ctx;
}

/**
 * Ties one locally-saved document to the signed-in account.
 *
 * On sign-in: the first time this device syncs with that account, what's on
 * the device is merged into the account's copy (nothing is lost); after that
 * the account's copy wins when the app opens, so deletions on one device stay
 * deleted everywhere. Local changes are then pushed to the account.
 */
export function useSyncedDoc<T>(
  key: SyncKey,
  value: T,
  loaded: boolean,
  apply: (value: T) => void,
  merge: (local: T, remote: T) => T,
) {
  const { userId, remote, push } = useAccountSync();
  const appliedFor = useRef<string | null>(null);
  const lastJson = useRef<string | null>(null);

  useEffect(() => {
    if (!userId) {
      appliedFor.current = null;
      return;
    }
    if (!remote || !loaded || appliedFor.current === userId) return;
    appliedFor.current = userId;
    lastJson.current = null;
    const doc = remote[key];
    AsyncStorage.getItem(LINKED(key))
      .catch(() => null)
      .then((linked) => {
        let next = value;
        if (doc && linked === userId) next = doc.value as T;                  // account copy wins
        else if (doc) next = merge(value, doc.value as T);                    // first sync on this device
        lastJson.current = JSON.stringify(next);
        if (doc && JSON.stringify(value) !== lastJson.current) apply(next);
        if (!doc || linked !== userId) push(key, next);
        AsyncStorage.setItem(LINKED(key), userId).catch(() => {});
      });
    // value is read at sign-in time only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, remote, loaded, key]);

  useEffect(() => {
    if (!userId || appliedFor.current !== userId || lastJson.current === null) return;
    const json = JSON.stringify(value);
    if (json === lastJson.current) return;
    lastJson.current = json;
    push(key, value);
  }, [userId, value, key, push]);
}
