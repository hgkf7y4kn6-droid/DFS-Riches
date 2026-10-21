import { useAuth, useUser } from '@clerk/expo';
import { usePathname } from 'expo-router';
import { type ReactNode, useCallback, useEffect, useRef } from 'react';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';

import { POSTHOG_HOST, POSTHOG_KEY } from '@/constants/config';

type Client = {
  screen(name: string): unknown;
  identify(id: string, props?: Record<string, string>): unknown;
  reset(): unknown;
  captureException(error: unknown, props?: Record<string, string>): unknown;
};

// PostHog is a large module: it loads as its own chunk after the app renders,
// so it never delays first paint. Calls made before then wait for it, in order.
let client: Promise<Client | null> | null = null;
function send(fn: (c: Client) => unknown) {
  if (!POSTHOG_KEY) return;
  client ??= import('posthog-react-native')
    // Error tracking: uncaught errors and unhandled promise rejections go to PostHog too.
    .then(
      ({ PostHog }) =>
        new PostHog(POSTHOG_KEY!, {
          host: POSTHOG_HOST,
          errorTracking: { autocapture: { uncaughtExceptions: true, unhandledRejections: true } },
        }) as unknown as Client,
    )
    .catch(() => null);
  client.then((c) => c && fn(c));
}

/** A one-off analytics event (no-op without a PostHog key). */
export function track(event: string, properties?: Record<string, string | number | boolean>) {
  send((c) => (c as Client & { capture(e: string, p?: object): unknown }).capture(event, properties));
}

/** A caught error (e.g. one a screen's error boundary showed) for PostHog's error tracking. */
export function captureError(error: unknown, where?: string) {
  send((c) => c.captureException(error, where ? { where } : undefined));
}

/**
 * An onScroll handler that reports how far down a screen the user got:
 * `scroll_depth` with the screen and 25 / 50 / 75 / 100 (each once per
 * visit to the screen), to see where people stop reading.
 */
export function useScrollDepth(screen: string) {
  const reached = useRef(0);
  const pathname = usePathname();
  useEffect(() => {
    reached.current = 0;
  }, [pathname]);
  return useCallback(
    (e: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
      const scrollable = contentSize.height - layoutMeasurement.height;
      if (scrollable <= 0) return;
      const pct = Math.min(100, Math.floor(((contentOffset.y / scrollable) * 100) / 25) * 25);
      if (pct <= reached.current) return;
      reached.current = pct;
      track('scroll_depth', { screen, percent: pct });
    },
    [screen],
  );
}

/** Screen views on every route change, and the signed-in Clerk user as the
 *  PostHog person (reset on sign-out so devices don't share a person). */
function Tracking() {
  const pathname = usePathname();
  const { isLoaded, isSignedIn, userId } = useAuth();
  const { user } = useUser();
  const email = user?.primaryEmailAddress?.emailAddress;
  const wasSignedIn = useRef(false);

  useEffect(() => {
    if (pathname) send((c) => c.screen(pathname));
  }, [pathname]);

  useEffect(() => {
    if (!isLoaded) return;
    if (isSignedIn && userId) send((c) => c.identify(userId, email ? { email } : undefined));
    else if (wasSignedIn.current) send((c) => c.reset());
    wasSignedIn.current = !!isSignedIn;
  }, [isLoaded, isSignedIn, userId, email]);

  return null;
}

export function AnalyticsProvider({ children }: { children: ReactNode }) {
  return (
    <>
      {POSTHOG_KEY ? <Tracking /> : null}
      {children}
    </>
  );
}
