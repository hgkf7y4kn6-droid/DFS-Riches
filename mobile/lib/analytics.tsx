import { useAuth, useUser } from '@clerk/expo';
import { usePathname } from 'expo-router';
import { PostHogProvider, usePostHog } from 'posthog-react-native';
import { type ReactNode, useEffect, useRef } from 'react';

import { POSTHOG_HOST, POSTHOG_KEY } from '@/constants/config';

/** Screen views on every route change, and the signed-in Clerk user as the
 *  PostHog person (reset on sign-out so devices don't share a person). */
function Tracking() {
  const posthog = usePostHog();
  const pathname = usePathname();
  const { isLoaded, isSignedIn, userId } = useAuth();
  const { user } = useUser();
  const email = user?.primaryEmailAddress?.emailAddress;
  const wasSignedIn = useRef(false);

  useEffect(() => {
    if (pathname) posthog.screen(pathname);
  }, [posthog, pathname]);

  useEffect(() => {
    if (!isLoaded) return;
    if (isSignedIn && userId) posthog.identify(userId, email ? { email } : undefined);
    else if (wasSignedIn.current) posthog.reset();
    wasSignedIn.current = !!isSignedIn;
  }, [posthog, isLoaded, isSignedIn, userId, email]);

  return null;
}

export function AnalyticsProvider({ children }: { children: ReactNode }) {
  if (!POSTHOG_KEY) return <>{children}</>;
  return (
    <PostHogProvider apiKey={POSTHOG_KEY} options={{ host: POSTHOG_HOST }} autocapture={{ captureScreens: false }}>
      <Tracking />
      {children}
    </PostHogProvider>
  );
}
