import { FlatList, Pressable, Text, View } from 'react-native';

import { formatDayPart } from '@/lib/utils';

interface Props {
  slates: Slate[];
  selectedId: string | null;
  onSelect: (slateId: string) => void;
}

function slateMeta(slate: Slate): string {
  if (!slate.available) return 'No salaries yet';
  const games = `${slate.games.length} game${slate.games.length === 1 ? '' : 's'}`;
  if (slate.slate_type === 'showdown') {
    const g = slate.games[0];
    return `${slate.day_part ? formatDayPart(slate.day_part) : 'Showdown'} · ${g ? g.kickoff_et.replace(/ ET$/, '') : games}`;
  }
  return `Classic · ${games}`;
}

function slateTitle(slate: Slate): string {
  if (slate.slate_type === 'showdown' && slate.games[0]) return `${slate.games[0].away} @ ${slate.games[0].home}`;
  return slate.slate_id === 'classic_sunday' ? 'Sunday Main' : slate.slate_id === 'classic' ? 'Full Week' : slate.label;
}

/**
 * Every slate this week as a horizontal row: Sunday Main, Full Week, then one
 * Showdown per island game in kickoff order (weeknight and Sunday night games,
 * plus international and holiday games on the weeks that have them).
 */
export default function SlateList({ slates, selectedId, onSelect }: Props) {
  return (
    <FlatList
      horizontal
      data={slates}
      keyExtractor={(s) => s.slate_id}
      showsHorizontalScrollIndicator={false}
      contentContainerClassName="pr-5"
      renderItem={({ item }) => {
        const active = item.slate_id === selectedId;
        return (
          <Pressable
            className={`slate-chip ${active ? 'slate-chip-active' : ''}`}
            onPress={() => onSelect(item.slate_id)}
            accessibilityRole="button"
            aria-pressed={active}>
            <Text className={`slate-chip-kicker ${active ? 'slate-chip-kicker-active' : ''}`}>
              {item.slate_type === 'showdown' ? 'Showdown' : 'Classic'}
            </Text>
            <Text className={`slate-chip-title ${active ? 'slate-chip-title-active' : ''}`} numberOfLines={1}>
              {slateTitle(item)}
            </Text>
            <Text className={`slate-chip-meta ${active ? 'slate-chip-meta-active' : ''}`} numberOfLines={1}>
              {slateMeta(item)}
            </Text>
          </Pressable>
        );
      }}
      ListEmptyComponent={
        <View className="py-2">
          <Text className="empty-text">No slates posted yet</Text>
        </View>
      }
    />
  );
}
