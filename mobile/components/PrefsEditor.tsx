import { Pressable, Text, View } from 'react-native';

import { FOCUS_OPTIONS, SPEND_OPTIONS, usePrefs } from '@/lib/prefs-context';

/** Settings' "Your game": what they play and their weekly budget (lib/prefs-context.tsx). */
export default function PrefsEditor() {
  const { prefs, update } = usePrefs();
  const chips = <T extends string>(options: { id: T; label: string }[], value: T | undefined, pick: (v: T) => void) => (
    <View className="flex-row flex-wrap">
      {options.map((o) => {
        const active = value === o.id;
        return (
          <Pressable key={o.id} className={`filter-chip mb-2 ${active ? 'filter-chip-active' : ''}`} onPress={() => pick(o.id)} accessibilityRole="radio" aria-checked={active}>
            <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
  return (
    <View className="settings-group mt-0 p-4">
      <Text className="input-label">What you play</Text>
      {chips(FOCUS_OPTIONS, prefs.focus, (focus) => update({ focus, askedAt: prefs.askedAt ?? new Date().toISOString() }))}
      <Text className="input-label mt-2">Weekly budget</Text>
      {chips(SPEND_OPTIONS, prefs.spend, (spend) => update({ spend, askedAt: prefs.askedAt ?? new Date().toISOString() }))}
      <Text className="caption mt-1">Home, Start here and Best contests follow these.</Text>
    </View>
  );
}
