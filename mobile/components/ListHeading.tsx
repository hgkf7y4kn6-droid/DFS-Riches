import { Pressable, Text, View } from 'react-native';

interface Props {
  title: string;
  subtitle?: string;
  /** Button on the right, e.g. "View all". Omit for a heading without one. */
  buttonText?: string;
  onPress?: () => void;
}

/** A section heading with an optional action button, reused above lists. */
export default function ListHeading({ title, subtitle, buttonText, onPress }: Props) {
  return (
    <View className="list-head">
      <View className="flex-1 pr-3">
        <Text className="list-title">{title}</Text>
        {subtitle ? <Text className="list-subtitle">{subtitle}</Text> : null}
      </View>
      {buttonText && onPress ? (
        <Pressable className="list-action" onPress={onPress} accessibilityRole="button" accessibilityLabel={`${title}: ${buttonText}`}>
          <Text className="list-action-text">{buttonText}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
