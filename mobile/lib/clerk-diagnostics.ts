import { Platform } from 'react-native';

// Why the sign-in service (Clerk's script) hasn't loaded: script load failures and
// page errors are recorded from the start (capture phase -- load errors don't bubble).
const errors: string[] = [];
if (Platform.OS === 'web' && typeof window !== 'undefined') {
  window.addEventListener(
    'error',
    (e) => {
      const src = (e.target as HTMLScriptElement | null)?.src;
      if (src && src.includes('clerk')) errors.push(`script failed: ${src.split('/npm/')[1] ?? src}`);
      else if (e.message && /clerk/i.test(`${e.message} ${e.filename}`)) errors.push(`error: ${e.message}`.slice(0, 160));
    },
    true,
  );
  window.addEventListener('unhandledrejection', (e) => {
    const msg = String((e.reason as Error)?.message ?? e.reason ?? '');
    if (/clerk/i.test(msg)) errors.push(`rejection: ${msg}`.slice(0, 160));
  });
}

/** A compact snapshot for the "still connecting" notice and analytics. */
export function clerkDiagnostics(status: string | undefined): Record<string, string | number | boolean> {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return { status: status ?? 'unknown' };
  const scripts = (performance.getEntriesByType('resource') as PerformanceResourceTiming[])
    .filter((r) => r.name.includes('clerk') && /\.js($|\?)/.test(r.name))
    .map((r) => `${r.name.split('/npm/')[1] ?? r.name} ${Math.round(r.duration)}ms ${r.transferSize}B${'responseStatus' in r ? ` ${(r as { responseStatus?: number }).responseStatus}` : ''}`);
  const w = window as unknown as { Clerk?: { loaded?: boolean; status?: string } };
  return {
    status: status ?? 'unknown',
    clerk_global: w.Clerk ? `present loaded=${Boolean(w.Clerk.loaded)} status=${w.Clerk.status ?? '?'}` : 'missing',
    scripts: scripts.join(' | ') || 'none requested',
    errors: errors.join(' | ') || 'none',
    cookies: navigator.cookieEnabled,
    ua: navigator.userAgent,
  };
}
