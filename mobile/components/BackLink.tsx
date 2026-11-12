import { router } from 'expo-router';
import { Pressable, Text } from 'react-native';

/** "‹ Back" for screens opened from a link rather than the tab bar. */
export default function BackLink() {
  return (
    <Pressable
      className="mb-2 self-start py-1"
      onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}
      accessibilityRole="button"
      accessibilityLabel="Back">
      <Text className="link-text text-sm">‹ Back</Text>
    </Pressable>
  );
}
