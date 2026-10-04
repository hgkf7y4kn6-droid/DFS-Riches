import { useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { CONTEST_TYPES } from '@/constants/data';
import { useThemeColors } from '@/constants/theme';
import { parseMoney } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

/**
 * Logs a contest entry: contest type, slate, fee per entry, number of
 * entries, and winnings if it has already settled (leave blank while the
 * contest is pending; results can be added later in the tracker). Logged
 * from the builder, the entry keeps its lineup for late swaps and the
 * tracker's player / team stats.
 */
export default function SubmissionForm({ slateId, lineup, onDone }: { slateId?: string; lineup?: SubmittedPlayer[]; onDone?: () => void }) {
  const colors = useThemeColors();
  const { add } = useSubmissions();
  const { season, week, weekData, selectedSlate } = useWeek();
  const slates = weekData.data?.slates ?? [];
  const [type, setType] = useState<ContestType>('gpp');
  const [slate, setSlate] = useState(slateId ?? selectedSlate?.slate_id ?? slates[0]?.slate_id ?? '');
  const [name, setName] = useState('');
  const [fee, setFee] = useState('');
  const [entries, setEntries] = useState('1');
  const [winnings, setWinnings] = useState('');
  const [error, setError] = useState<string | null>(null);

  const feeValue = parseMoney(fee);
  const entriesValue = Number(entries);
  const total = feeValue != null && Number.isInteger(entriesValue) && entriesValue > 0 ? feeValue * entriesValue : null;

  const submit = () => {
    const chosen = slates.find((s) => s.slate_id === slate);
    if (!season || !week || !chosen) return setError('Pick a slate.');
    if (feeValue == null || feeValue <= 0) return setError('Enter the entry fee, e.g. 5 or 3.00.');
    if (!Number.isInteger(entriesValue) || entriesValue < 1 || entriesValue > 150) return setError('Entries must be a whole number from 1 to 150.');
    const won = winnings.trim() ? parseMoney(winnings) : null;
    if (winnings.trim() && won == null) return setError('Winnings must be a dollar amount, or blank if pending.');
    add({
      season,
      week,
      slateId: chosen.slate_id,
      slateLabel: chosen.label,
      contestType: type,
      contestName: name.trim(),
      entryFee: feeValue,
      entries: entriesValue,
      winnings: won,
      ...(lineup?.length ? { lineup } : {}),
    });
    setError(null);
    setName('');
    setFee('');
    setEntries('1');
    setWinnings('');
    onDone?.();
  };

  return (
    <View>
      <Text className="input-label">Contest type</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
        {CONTEST_TYPES.map((c) => {
          const active = c.id === type;
          return (
            <Pressable
              key={c.id}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => setType(c.id)}
              accessibilityRole="button"
              aria-pressed={active}
              accessibilityHint={c.description}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{c.short}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <Text className="input-label">Slate</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
        {slates.map((s) => {
          const active = s.slate_id === slate;
          return (
            <Pressable
              key={s.slate_id}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => setSlate(s.slate_id)}
              accessibilityRole="button"
              aria-pressed={active}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{s.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <View className="input-field">
        <Text className="input-label">Contest name (optional)</Text>
        <TextInput className="input" value={name} onChangeText={setName} placeholder="NFL $5 Millionaire Maker" placeholderTextColor={colors.mutedForeground} />
      </View>
      <View className="input-row">
        <View className="input-field-half">
          <Text className="input-label">Entry fee</Text>
          <TextInput className="input" value={fee} onChangeText={setFee} placeholder="$5.00" keyboardType="decimal-pad" placeholderTextColor={colors.mutedForeground} />
        </View>
        <View className="input-field-half">
          <Text className="input-label">Entries</Text>
          <TextInput className="input" value={entries} onChangeText={setEntries} keyboardType="number-pad" placeholderTextColor={colors.mutedForeground} />
        </View>
      </View>
      <View className="input-field">
        <Text className="input-label">Winnings (blank if pending)</Text>
        <TextInput className="input" value={winnings} onChangeText={setWinnings} placeholder="$0.00" keyboardType="decimal-pad" placeholderTextColor={colors.mutedForeground} />
      </View>

      {error ? <Text className="form-error">{error}</Text> : null}
      <Pressable className="btn-accent" onPress={submit} accessibilityRole="button">
        <Text className="btn-text">Log entry{total != null ? ` · ${formatCurrency(total)}` : ''}</Text>
      </Pressable>
    </View>
  );
}
