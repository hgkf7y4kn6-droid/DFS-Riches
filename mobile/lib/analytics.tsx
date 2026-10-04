import { useAuth, useUser } from '@clerk/expo';
import { usePathname } from 'expo-router';
import { type ReactNode, useEffect, useRef } from 'react';

import { POSTHOG_HOST, POSTHOG_KEY } from '@/constants/config';

type Client = { screen(name: string): unknown; identify(id: string, props?: Record<string, string>): unknown; reset(): unknown };

// PostHog is a large module: it loads as its own chunk after the app renders,
// so it never delays first paint. Calls made before then wait for it, in order.
let client: Promise<Client | null> | null = null;
function send(fn: (c: Client) => unknown) {
  if (!POSTHOG_KEY) return;
  client ??= import('posthog-react-native')
    .then(({ PostHog }) => new PostHog(POSTHOG_KEY!, { host: POSTHOG_HOST }) as Client)
    .catch(() => null);
  client.then((c) => c && fn(c));
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
