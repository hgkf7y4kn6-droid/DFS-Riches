import { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { CONTEST_TYPE_BY_ID } from '@/constants/data';
import { colors } from '@/constants/theme';
import { cost, parseMoney, profit, stats, statsByType } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency, formatPercent, formatSignedCurrency } from '@/lib/utils';

const RECENT = 10;

function netClass(n: number) {
  return n > 0 ? 'text-positive' : n < 0 ? 'text-negative' : 'text-primary';
}

function StatsRow({ title, s }: { title: string; s: ProfitLossStats }) {
  return (
    <View className="pl-row">
      <View className="pl-row-header">
        <Text className="pl-type">{title}</Text>
        <Text className={`pl-net ${netClass(s.net)}`}>{formatSignedCurrency(s.net)}</Text>
      </View>
      <View className="pl-stats">
        {[
          ['Entries', String(s.entries)],
          ['Spent', formatCurrency(s.spent)],
          ['Won', formatCurrency(s.won)],
          ['Win %', formatPercent(s.winPct, 0)],
          ['ROI', s.roi == null ? '-' : `${s.roi > 0 ? '+' : ''}${formatPercent(s.roi, 0)}`],
        ].map(([label, value]) => (
          <View key={label}>
            <Text className="pl-stat-value">{value}</Text>
            <Text className="pl-stat-label">{label}</Text>
          </View>
        ))}
      </View>
      <View className="pl-bar-track">
        <View className="pl-bar-fill" style={{ width: `${Math.round((s.winPct ?? 0) * 100)}%` }} />
      </View>
    </View>
  );
}

function EntryRow({ entry }: { entry: LineupSubmission }) {
  const { settle, remove } = useSubmissions();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const net = profit(entry);
  const type = CONTEST_TYPE_BY_ID[entry.contestType];

  const save = () => {
    const won = parseMoney(value);
    if (won == null) return;
    settle(entry.id, won);
    setEditing(false);
    setValue('');
  };

  return (
    <View className="entry-row">
      <View className="pl-row-header">
        <View className="flex-1 pr-2">
          <Text className="entry-title" numberOfLines={1}>
            {entry.contestName || type?.title || entry.contestType}
          </Text>
          <Text className="entry-meta" numberOfLines={1}>
            {type?.short} · Wk {entry.week} · {entry.slateLabel}
          </Text>
          <Text className="entry-meta">
            {entry.entries} × {formatCurrency(entry.entryFee)} = {formatCurrency(cost(entry))}
          </Text>
        </View>
        {net == null ? (
          <Text className="entry-pending">Pending</Text>
        ) : (
          <View className="items-end">
            <Text className={`entry-result ${netClass(net)}`}>{formatSignedCurrency(net)}</Text>
            <Text className="entry-meta">won {formatCurrency(entry.winnings ?? 0)}</Text>
          </View>
        )}
      </View>
      {editing ? (
        <View className="input-row mt-2 items-center">
          <TextInput
            className="input flex-1"
            value={value}
            onChangeText={setValue}
            placeholder="Total winnings, e.g. 0 or 18.00"
            keyboardType="decimal-pad"
            placeholderTextColor={colors.mutedForeground}
            autoFocus
          />
          <Pressable className="btn" onPress={save} accessibilityRole="button">
            <Text className="btn-text">Save</Text>
          </Pressable>
        </View>
      ) : (
        <View className="mt-1.5 flex-row gap-4">
          <Pressable onPress={() => setEditing(true)} accessibilityRole="button">
            <Text className="link-text">{net == null ? 'Enter result' : 'Edit result'}</Text>
          </Pressable>
          {net != null ? (
            <Pressable onPress={() => settle(entry.id, null)} accessibilityRole="button">
              <Text className="caption">Mark pending</Text>
            </Pressable>
          ) : null}
          <Pressable onPress={() => remove(entry.id)} accessibilityRole="button">
            <Text className="danger-link">Delete</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

/**
 * Profit/loss by contest type -- entries, money spent and won, win
 * percentage, ROI and net dollars -- plus the most recent entries, where
 * pending contests get their results entered.
 */
export default function ProfitLossTracker() {
  const { submissions, loaded } = useSubmissions();
  if (!loaded) return null;
  if (submissions.length === 0) {
    return <Text className="home-empty-state">No contest entries yet. Tap “+ Log entry” to track what you spend and win.</Text>;
  }
  const byType = statsByType(submissions).sort((a, b) => b.stats.spent - a.stats.spent);

  return (
    <View>
      <StatsRow title="All contests" s={stats(submissions)} />
      {byType.map(({ type, stats: s }) => (
        <StatsRow key={type} title={CONTEST_TYPE_BY_ID[type]?.title ?? type} s={s} />
      ))}
      <Text className="label mt-4">Recent entries</Text>
      {submissions.slice(0, RECENT).map((e) => (
        <EntryRow key={e.id} entry={e} />
      ))}
    </View>
  );
}
