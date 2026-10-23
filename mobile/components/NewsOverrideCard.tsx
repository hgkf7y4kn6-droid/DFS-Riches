import { useAuth } from '@clerk/expo';
import { useState } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';

import { useThemeColors } from '@/constants/theme';
import { useAccountSync } from '@/lib/account-sync';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { deleteNewsOverride, getNewsOverrides, postNewsOverride, type NewsOverride, type NewsStatus } from '@/lib/api';
import { useDfsModel } from '@/lib/dfs-model-context';
import { formatEt } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

const STATUSES: { id: NewsStatus; label: string }[] = [
  { id: 'OUT', label: 'Out' },
  { id: 'D', label: 'Doubtful' },
  { id: 'Q', label: 'Questionable' },
  { id: 'PLAYING', label: 'Playing' },
];
const CACHE = createFetchCache<NewsOverride[]>();
const LABEL: Record<NewsStatus, string> = { OUT: 'Out', D: 'Doubtful', Q: 'Questionable', PLAYING: 'Playing' };

/**
 * Master accounts: breaking news before DraftKings, ESPN or the team's report catch up -- a coach ruling a player
 * out, say. It applies to projections, the player pool, the model and the plays right away (app.news_overrides).
 * Out / Doubtful / Questionable only make a player's status worse; Playing only clears a Questionable tag; official
 * Out and Doubtful always win. Linemen and defenders (not on a DraftKings slate) need their team and count toward
 * the game model's starters out.
 */
export default function NewsOverrideCard() {
  const { master } = useAccountSync();
  const { getToken } = useAuth();
  const { season, week, refresh } = useWeek();
  const { refresh: refreshModel } = useDfsModel();
  const colors = useThemeColors();
  const [name, setName] = useState('');
  const [team, setTeam] = useState('');
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<NewsStatus>('OUT');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const list = useCachedFetch(CACHE, master && season && week ? `news:${season}:${week}` : '', () => getNewsOverrides(season!, week!));
  const entries = list.data ?? [];
  if (!master) return null;

  const changed = () => {
    list.refresh();
    refresh();
    refreshModel();
  };

  const submit = async () => {
    setMessage(null);
    setBusy(true);
    try {
      const token = await getToken();
      if (!token || !season || !week) throw new Error('Sign in first.');
      const e = await postNewsOverride(token, { season, week, name: name.trim(), team: team.trim() || undefined, status, note: note.trim() || undefined });
      setMessage({
        text:
          `${e.name} (${e.team}) marked ${LABEL[e.status]} for Week ${e.week}` +
          (e.on_slate ? '' : ' -- not on a DraftKings slate: counts toward his team’s starters out') +
          (e.persisted === false ? ' · not saved to the database (kept until the next deploy)' : ''),
      });
      setName('');
      setTeam('');
      setNote('');
      changed();
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : String(err), error: true });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (e: NewsOverride) => {
    try {
      const token = await getToken();
      if (!token) throw new Error('Sign in first.');
      await deleteNewsOverride(token, e.season, e.week, e.id);
      setMessage({ text: `Removed ${e.name}: the official feeds take over again.` });
      changed();
    } catch (err) {
      setMessage({ text: err instanceof Error ? err.message : String(err), error: true });
    }
  };

  return (
    <View className="account-card">
      <Text className="account-title">Breaking news</Text>
      <Text className="account-text">
        A coach rules someone out before DraftKings, ESPN or the team&apos;s injury report catch up? Enter it here and it applies
        to Week {week} projections, the player pool, the model and the plays right away. Official Out and Doubtful still win.
      </Text>
      <View className="input-row mt-3">
        <TextInput
          className="input flex-1"
          placeholder="Player (e.g. Rashee Rice)"
          placeholderTextColor={colors.mutedForeground}
          value={name}
          onChangeText={setName}
          autoCorrect={false}
        />
        <TextInput
          className="input w-20"
          placeholder="Team"
          placeholderTextColor={colors.mutedForeground}
          value={team}
          onChangeText={(t) => setTeam(t.toUpperCase())}
          autoCapitalize="characters"
          autoCorrect={false}
          maxLength={3}
        />
      </View>
      <View className="mt-2 flex-row flex-wrap gap-y-2">
        {STATUSES.map((s) => {
          const active = s.id === status;
          return (
            <Pressable
              key={s.id}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => setStatus(s.id)}
              accessibilityRole="radio"
              aria-checked={active}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{s.label}</Text>
            </Pressable>
          );
        })}
      </View>
      <TextInput
        className="input mt-2"
        placeholder="Source (optional, e.g. Andy Reid presser)"
        placeholderTextColor={colors.mutedForeground}
        value={note}
        onChangeText={setNote}
        maxLength={280}
      />
      <Pressable className="btn mt-3" onPress={submit} disabled={busy || name.trim().length < 2} accessibilityRole="button">
        {busy ? <ActivityIndicator color={colors.primaryForeground} /> : <Text className="btn-text">Apply news</Text>}
      </Pressable>
      {message ? <Text className={`account-text ${message.error ? 'text-negative' : ''}`}>{message.text}</Text> : null}
      {entries.length ? (
        <View className="mt-3">
          <Text className="input-label">Week {week} news</Text>
          {entries.map((e) => (
            <View key={e.id} className="news-row">
              <View className="flex-1 pr-2">
                <Text className="news-row-name">
                  {e.name} <Text className="dfs-meta">{e.team}</Text> · {LABEL[e.status]}
                </Text>
                <Text className="account-text mt-0">
                  {formatEt(e.created_at)}
                  {e.note ? ` · ${e.note}` : ''}
                  {e.on_slate ? '' : ' · starters out only'}
                </Text>
              </View>
              <Pressable onPress={() => remove(e)} accessibilityRole="button" accessibilityLabel={`Remove news for ${e.name}`} hitSlop={8}>
                <Text className="danger-link">Remove</Text>
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}
