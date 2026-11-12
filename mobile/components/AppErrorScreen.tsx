import { useEffect } from 'react';
import { Pressable, Text, View } from 'react-native';

import { captureError } from '@/lib/analytics';

/**
 * What a crash looks like: a calm message and a way back, instead of a
 * blank screen. The error goes to PostHog's error tracking. Used as the
 * root layout's ErrorBoundary (Expo Router).
 */
export default function AppErrorScreen({ error, retry }: { error: Error; retry: () => Promise<void> }) {
  useEffect(() => {
    captureError(error, 'error_boundary');
  }, [error]);
  return (
    <View className="auth-gate px-8">
      <Text className="brand-title">
        <Text className="brand-accent">Riches</Text> Analytics
      </Text>
      <Text className="intro-title mt-6 text-center">Something went wrong</Text>
      <Text className="intro-text text-center">
        Sorry about that. It&apos;s been reported. Try again, and if it keeps happening, pull to refresh or reopen the app.
      </Text>
      <Pressable className="btn mt-4 px-8" onPress={() => retry()} accessibilityRole="button">
        <Text className="btn-text">Try again</Text>
      </Pressable>
    </View>
  );
}
