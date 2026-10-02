import { ActivityIndicator, Text, View } from 'react-native';

import { useThemeColors } from '@/constants/theme';

/** Loading spinner, error or empty message for a section; null when there's data to show. */
export default function StatusView({ loading, error, empty }: { loading?: boolean; error?: string | null; empty?: string | null }) {
  const colors = useThemeColors();
  if (loading) {
    return (
      <View className="py-4">
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }
  if (error) return <Text className="error-text">{error}</Text>;
  if (empty) return <Text className="empty-text">{empty}</Text>;
  return null;
}
