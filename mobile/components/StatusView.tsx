import { Pressable, Text, View } from 'react-native';

import { SkeletonRows } from '@/components/Skeleton';

/**
 * A section's loading placeholder, error (with "Try again" when it can
 * retry) or empty message; null when there's data to show.
 */
export default function StatusView({
  loading,
  error,
  empty,
  onRetry,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: string | null;
  onRetry?: () => void;
}) {
  if (loading) return <SkeletonRows rows={3} />;
  if (error) {
    return (
      <View className="items-center py-3">
        <Text className="error-text py-0">{error}</Text>
        {onRetry ? (
          <Pressable className="btn-outline mt-2 px-6" onPress={onRetry} accessibilityRole="button">
            <Text className="btn-outline-text">Try again</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }
  if (empty) return <Text className="empty-text">{empty}</Text>;
  return null;
}
