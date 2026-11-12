import { useAuth } from '@clerk/expo';
import { router, usePathname } from 'expo-router';
import { useEffect, useRef } from 'react';

import { track } from '@/lib/analytics';
import { setSessionRejectedHandler } from '@/lib/api';

const COOLDOWN_MS = 10 * 60 * 1000;

/**
 * When the server turns the session down even after a fresh token (it
 * expired or was revoked), sign out and go to sign-in with a "please sign
 * in again" note, returning to this page afterwards. At most once every ten
 * minutes, so a server-side problem can't loop the user through sign-in.
 */
export default function SessionGuard() {
  const { signOut } = useAuth();
  const pathname = usePathname();
  const where = useRef(pathname);
  const last = useRef(0);
  useEffect(() => {
    where.current = pathname;
  }, [pathname]);

  useEffect(() => {
    setSessionRejectedHandler(() => {
      if (Date.now() - last.current < COOLDOWN_MS) return;
      last.current = Date.now();
      track('session_rejected');
      const next = where.current;
      signOut()
        .catch(() => {})
        .finally(() => router.replace({ pathname: '/sign-in', params: { expired: '1', next } }));
    });
    return () => setSessionRejectedHandler(null);
  }, [signOut]);
  return null;
}
