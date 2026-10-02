import { Pressable, ScrollView, Text } from 'react-native';

import { useDfsModel } from '@/lib/dfs-model-context';

/** Chips for the Classic slates the DFS model can run on. */
export default function DfsSlatePicker() {
  const { model, slateId, selectSlate } = useDfsModel();
  if (!model?.slates?.length) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
      {model.slates.map((s) => {
        const active = s.slate_id === (slateId ?? model.slate.slate_id);
        return (
          <Pressable
            key={s.slate_id}
            className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
            onPress={() => selectSlate(s.slate_id)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}>
            <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{s.label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
