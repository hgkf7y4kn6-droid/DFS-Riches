import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { CONTEST_TYPE_BY_ID } from '@/constants/data';
import { useThemeColors } from '@/constants/theme';
import { cost, exposure, type ExposureStat, mostPlayed, mostProfitable, parseMoney, profit, stats, statsByType } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency, formatEt, formatPercent, formatSignedCurrency } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

const RECENT = 10;

function netClass(n: number) {
  return n > 0 ? 'text-positive' : n < 0 ? 'text-negative' : 'text-foreground';
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
  const colors = useThemeColors();
  const { settle, remove, startEditing } = useSubmissions();
  const { current, season, week, setSeasonWeek, selectSlate } = useWeek();
  const [editing, setEditing] = useState(false);
  const [showLineup, setShowLineup] = useState(false);
  // Late swap is for this week's entries; players whose games have started stay locked in the editor.
  const editable = !!entry.lineup?.length && !!current && entry.season === current.season && entry.week === current.week;
  const editLineup = () => {
    if (entry.season !== season || entry.week !== week) setSeasonWeek({ season: entry.season, week: entry.week });
    selectSlate(entry.slateId);
    startEditing(entry.id);
    router.push('/lineups');
  };
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
            {entry.editedAt ? ` · lineup edited ${formatEt(entry.editedAt)}` : ''}
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
      {showLineup && entry.lineup ? (
        <View className="mt-1.5">
          {entry.lineup.map((p, i) => (
            <Text key={`${p.slot}-${i}`} className="entry-meta">
              {p.slot} {p.name} · {p.team} · {formatCurrency(p.salary)}
            </Text>
          ))}
        </View>
      ) : null}
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
          {entry.lineup?.length ? (
            <Pressable onPress={() => setShowLineup((v) => !v)} accessibilityRole="button">
              <Text className="caption">{showLineup ? 'Hide lineup' : 'Lineup'}</Text>
            </Pressable>
          ) : null}
          {editable ? (
            <Pressable onPress={editLineup} accessibilityRole="button" accessibilityLabel="Edit this entry's lineup (late swap)">
              <Text className="link-text">Edit lineup</Text>
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

function ExposureList({ title, rows, kind }: { title: string; rows: ExposureStat[]; kind: 'played' | 'profit' }) {
  if (!rows.length) return null;
  return (
    <View className="mt-2">
      <Text className="pl-exposure-title">{title}</Text>
      {rows.map((r, i) => {
        const roi = r.net != null && r.settledFees > 0 ? r.net / r.settledFees : null;
        return (
          <View key={r.key} className="pl-exposure-row">
            <Text className="pl-exposure-name" numberOfLines={1}>
              {i + 1}. {r.label}
              {r.sub ? <Text className="entry-meta"> {r.sub}</Text> : null}
            </Text>
            <Text className="entry-meta">
              {kind === 'played' ? `${r.entries} entr${r.entries === 1 ? 'y' : 'ies'} · ${r.lineups} lineup${r.lineups === 1 ? '' : 's'}` : ''}
              {kind === 'profit' && roi != null ? `ROI ${roi > 0 ? '+' : ''}${formatPercent(roi, 0)} · ` : ''}
            </Text>
            <Text className={`pl-exposure-net ${r.net == null ? 'text-pending' : netClass(r.net)}`}>
              {r.net == null ? 'pending' : formatSignedCurrency(r.net)}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

/** Most played and most profitable players and teams, from the lineups logged with entries. */
function ExposureStats({ submissions }: { submissions: LineupSubmission[] }) {
  const withLineups = submissions.filter((s) => s.lineup?.length).length;
  if (!withLineups) {
    return (
      <Text className="entry-meta mt-3">
        Log entries from the lineup builder (“Log a contest entry for this lineup”) to track your most played and most profitable players and teams.
      </Text>
    );
  }
  const { players, teams } = exposure(submissions);
  return (
    <View className="mt-4">
      <Text className="label">Your players and teams</Text>
      <Text className="entry-meta">
        From {withLineups} logged lineup{withLineups === 1 ? '' : 's'}. Net = winnings minus fees on settled entries that included them.
      </Text>
      <ExposureList title="Most played players" rows={mostPlayed(players)} kind="played" />
      <ExposureList title="Most profitable players" rows={mostProfitable(players)} kind="profit" />
      <ExposureList title="Most played teams" rows={mostPlayed(teams)} kind="played" />
      <ExposureList title="Most profitable teams" rows={mostProfitable(teams)} kind="profit" />
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
    return <Text className="home-empty-state">No contest entries yet. Tap “+ Log a contest entry” above, or log one from the lineup builder.</Text>;
  }
  const byType = statsByType(submissions).sort((a, b) => b.stats.spent - a.stats.spent);

  return (
    <View>
      <StatsRow title="All contests" s={stats(submissions)} />
      {byType.map(({ type, stats: s }) => (
        <StatsRow key={type} title={CONTEST_TYPE_BY_ID[type]?.title ?? type} s={s} />
      ))}
      <ExposureStats submissions={submissions} />
      <Text className="label mt-4">Recent entries</Text>
      {submissions.slice(0, RECENT).map((e) => (
        <EntryRow key={e.id} entry={e} />
      ))}
    </View>
  );
}
