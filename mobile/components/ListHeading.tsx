import { Text, TouchableOpacity, View } from 'react-native';

/** A section heading with a "View all" button, reused above Home's lists. */
export default function ListHeading({ title, subtitle, buttonText = 'View all', onPress }: ListHeadingProps) {
  return (
    <View className="list-head">
      <View className="flex-1 pr-3">
        <Text className="list-title">{title}</Text>
        {subtitle ? <Text className="list-subtitle">{subtitle}</Text> : null}
      </View>
      {onPress ? (
        <TouchableOpacity className="list-action" onPress={onPress} accessibilityRole="button" accessibilityLabel={`${title}: ${buttonText}`}>
          <Text className="list-action-text">{buttonText}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}
