import { Pressable, Text, View } from 'react-native';

// Full class names (not built with a template) so Tailwind keeps them.
export const TAG_STYLE: Record<PlayTag, { label: string; pill: string; mine: string; text: string }> = {
  prioritize: { label: 'Prioritize', pill: 'tag-pill tag-prioritize', mine: 'tag-pill tag-prioritize tag-pill-mine', text: 'tag-pill-text tag-prioritize-text' },
  neutral: { label: 'Neutral', pill: 'tag-pill tag-neutral', mine: 'tag-pill tag-neutral tag-pill-mine', text: 'tag-pill-text tag-neutral-text' },
  fade: { label: 'Fade', pill: 'tag-pill tag-fade', mine: 'tag-pill tag-fade tag-pill-mine', text: 'tag-pill-text tag-fade-text' },
};

/**
 * Prioritize / Neutral / Fade. `mine` outlines a tag the user set for their
 * pool; with onPress the pill is a button that opens the tag picker.
 */
export default function TagPill({ tag, mine = false, onPress }: { tag: PlayTag; mine?: boolean; onPress?: () => void }) {
  const s = TAG_STYLE[tag];
  const pill = (
    <View className={mine ? s.mine : s.pill}>
      <Text className={s.text}>
        {s.label}
        {onPress ? ' ▾' : ''}
      </Text>
    </View>
  );
  if (!onPress) return pill;
  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel={`${s.label}${mine ? ' (your tag)' : ''}. Change tag`}>
      {pill}
    </Pressable>
  );
}
