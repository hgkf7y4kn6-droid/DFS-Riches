import { Pressable, ScrollView, Text } from 'react-native';

import { useDfsModel } from '@/lib/dfs-model-context';

/** Chips for the Classic slates the DFS model can run on (from the model, or from a plays response). */
export default function DfsSlatePicker({ slates, current }: { slates?: { slate_id: string; label: string }[]; current?: string } = {}) {
  const { model, slateId, selectSlate } = useDfsModel();
  const list = slates ?? model?.slates ?? [];
  const selected = slateId ?? current ?? model?.slate.slate_id;
  if (!list.length) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
      {list.map((s) => {
        const active = s.slate_id === selected;
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
