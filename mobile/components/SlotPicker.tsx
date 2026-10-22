import { useMemo, useState, type ReactNode } from 'react';
import { Image, Modal, Pressable, SectionList, Text, TextInput, View } from 'react-native';

import { LineupRow, type RowPlayer } from '@/components/LineupRows';
import SafeAreaView from '@/components/SafeAreaView';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { formatCurrency } from '@/lib/utils';

export interface SlotChoice {
  player: Player;
  blend: number | null;
  /** Why he can't be picked (salary or availability); null when he fits. */
  reason: string | null;
}

type SectionKey = 'fits' | 'salary' | 'unavailable';

/**
 * One roster slot's player list, full screen (like DraftKings' "Draft QB"): the players who fit the
 * lineup's remaining salary first, in the builder's current sort or blend, with the ones priced out and the
 * ones already in the lineup (or locked) folded into sections at the bottom. A bar at the bottom keeps the
 * lineup's positions filled, remaining salary and average left per open slot in view. Tapping a player puts
 * him in this slot and returns to the lineup.
 */
export default function SlotPicker({
  visible,
  slot,
  current,
  choices,
  query,
  onQuery,
  controls,
  summary,
  rowPlayer,
  onPick,
  onRemove,
  onClose,
}: {
  visible: boolean;
  slot: string;
  current: Player | null;
  choices: { fits: SlotChoice[]; salary: SlotChoice[]; unavailable: SlotChoice[] };
  query: string;
  onQuery: (q: string) => void;
  /** The builder's sort chips and weights, shared so the list follows the same sort / blend. */
  controls: ReactNode;
  summary: LineupSummary;
  rowPlayer: (p: Player) => RowPlayer;
  onPick: (p: Player) => void;
  onRemove: () => void;
  onClose: () => void;
}) {
  const colors = useThemeColors();
  const [open, setOpen] = useState<Record<SectionKey, boolean>>({ fits: true, salary: false, unavailable: false });
  const sections = useMemo(
    () =>
      (
        [
          { key: 'fits', title: `Fits your salary (${choices.fits.length})`, data: choices.fits, total: choices.fits.length },
          { key: 'salary', title: `Over your remaining salary (${choices.salary.length})`, data: choices.salary, total: choices.salary.length },
          { key: 'unavailable', title: `Already in your lineup or locked (${choices.unavailable.length})`, data: choices.unavailable, total: choices.unavailable.length },
        ] as { key: SectionKey; title: string; data: SlotChoice[]; total: number }[]
      )
        .filter((s) => s.total > 0)
        .map((s) => ({ ...s, data: open[s.key] ? s.data : [] })),
    [choices, open],
  );
  const filledAfter = summary.filled;
  const underCap = summary.remaining >= 0;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView className="flex-1 bg-background" edges={['top', 'bottom', 'left', 'right']}>
        <View className="picker-header">
          <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="Back to the lineup" hitSlop={10} className="picker-back">
            <Text className="picker-back-text">‹ Lineup</Text>
          </Pressable>
          <Text className="picker-title" accessibilityRole="header">
            Draft {slot}
          </Text>
          <View className="picker-back items-end">
            {current ? (
              <Pressable onPress={onRemove} accessibilityRole="button" accessibilityLabel={`Remove ${current.name}`} hitSlop={10}>
                <Text className="danger-link">Remove</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
        <View className="px-4">
          <TextInput
            className="input mb-2"
            placeholder="Search player or team"
            placeholderTextColor={colors.mutedForeground}
            value={query}
            onChangeText={onQuery}
            autoCorrect={false}
            autoCapitalize="none"
          />
        </View>
        <SectionList
          sections={sections}
          keyExtractor={(c) => String(c.player.dk_draftable_id ?? `${c.player.name}-${c.player.roster_slot}`)}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 24 }}
          stickySectionHeadersEnabled={false}
          ListHeaderComponent={
            <View>
              {controls}
              {current ? (
                <View className="picker-current">
                  <Text className="input-label">In this slot now</Text>
                  <LineupRow slot={slot} player={rowPlayer(current)} />
                </View>
              ) : null}
            </View>
          }
          renderSectionHeader={({ section }) => {
            const s = section as unknown as { key: SectionKey; title: string; total: number };
            const collapsible = s.key !== 'fits';
            return (
              <Pressable
                className="picker-section"
                disabled={!collapsible}
                onPress={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
                accessibilityRole={collapsible ? 'button' : 'header'}
                aria-expanded={collapsible ? open[s.key] : undefined}>
                <Text className={`picker-section-title ${s.key === 'fits' ? '' : 'text-muted-foreground'}`}>{s.title}</Text>
                {collapsible ? <Text className="caption">{open[s.key] ? 'Hide' : 'Show'}</Text> : null}
              </Pressable>
            );
          }}
          renderItem={({ item, section }) => {
            const fits = (section as unknown as { key: SectionKey }).key === 'fits';
            return (
              <View className={fits ? '' : 'player-unfit'}>
                <LineupRow
                  slot={item.player.roster_slot || item.player.position}
                  player={{ ...rowPlayer(item.player), blend: item.blend }}
                  note={item.reason}
                  onPress={fits ? () => onPick(item.player) : undefined}
                  pressLabel={`Add ${item.player.name} at ${slot}`}
                  right={
                    fits ? (
                      <Pressable className="player-action" onPress={() => onPick(item.player)} accessibilityRole="button" accessibilityLabel={`Add ${item.player.name}`}>
                        <Image source={icons.plus} style={{ width: 12, height: 12, tintColor: colors.primaryForeground }} />
                      </Pressable>
                    ) : null
                  }
                />
              </View>
            );
          }}
          ListEmptyComponent={<Text className="empty-text mt-4">No players match.</Text>}
        />
        <View className="picker-bar">
          <View>
            <Text className="picker-bar-label">
              Positions filled <Text className="picker-bar-value">{filledAfter}/{summary.total}</Text>
            </Text>
            <Text className={`picker-bar-label ${underCap ? '' : 'text-negative'}`}>{underCap ? 'Under the salary cap ✓' : 'Over the salary cap'}</Text>
          </View>
          <View className="items-end">
            <Text className="picker-bar-label">
              Remaining <Text className={`picker-bar-value ${underCap ? '' : 'text-negative'}`}>{formatCurrency(summary.remaining)}</Text>
            </Text>
            <Text className="picker-bar-label">
              Avg per open slot{' '}
              <Text className="picker-bar-value">{summary.avgRemaining != null ? formatCurrency(Math.max(0, summary.avgRemaining)) : '-'}</Text>
            </Text>
          </View>
        </View>
      </SafeAreaView>
    </Modal>
  );
}
