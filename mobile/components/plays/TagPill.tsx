import { Text, View } from 'react-native';

// Full class names (not built with a template) so Tailwind keeps them.
const STYLE: Record<PlayTag, { label: string; pill: string; text: string }> = {
  prioritize: { label: 'Prioritize', pill: 'tag-pill tag-prioritize', text: 'tag-pill-text tag-prioritize-text' },
  neutral: { label: 'Neutral', pill: 'tag-pill tag-neutral', text: 'tag-pill-text tag-neutral-text' },
  fade: { label: 'Fade', pill: 'tag-pill tag-fade', text: 'tag-pill-text tag-fade-text' },
};

/** Prioritize / Neutral / Fade. */
export default function TagPill({ tag }: { tag: PlayTag }) {
  const s = STYLE[tag];
  return (
    <View className={s.pill}>
      <Text className={s.text}>{s.label}</Text>
    </View>
  );
}
