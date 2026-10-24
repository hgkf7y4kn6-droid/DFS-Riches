import { useMemo, useState } from 'react';
import { Image, Modal, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import SafeAreaView from '@/components/SafeAreaView';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { PICK_POSITIONS, rankedCount, useProPicks } from '@/lib/pro-picks-context';
import { formatCurrency, formatEt, formatPoints } from '@/lib/utils';

type Picks = Partial<Record<PickPosition, number[]>>;
const CANDIDATE_PAGE = 30;

/**
 * Weekly Pro Picks, full screen: rank the players you think will be each position's top DraftKings scorers on
 * the Sunday Main (5 QBs, 10 RBs, 15 WRs, 3 TEs, 5 DSTs). Tap a player to add him at the next open spot; move
 * him with the arrows. Read-only once the Main kicks off; once it's scored, each pick shows where he finished
 * and what he earned. The draft survives closing the editor until the app restarts.
 */
export default function ProPicksEditor() {
  const { state, save, editorOpen, setEditorOpen } = useProPicks();
  const colors = useThemeColors();
  const [position, setPosition] = useState<PickPosition>('QB');
  const [draft, setDraft] = useState<Picks>({});
  const [name, setName] = useState('');
  const [dirty, setDirty] = useState(false);
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(CANDIDATE_PAGE);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);

  // Start from the saved entry (and pick it up again after a save), unless there are unsaved changes
  // (state adjusted during render, React's pattern for it).
  const savedKey = state ? `${state.season}:${state.week}:${state.mine?.updated_at ?? ''}` : null;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  if (state && savedKey !== loadedKey && !dirty) {
    setLoadedKey(savedKey);
    setDraft(state.mine?.picks ?? {});
    setName(state.mine?.name ?? state.default_name ?? '');
  }

  const byId = useMemo(() => new Map((state?.players ?? []).map((p) => [p.id, p])), [state?.players]);
  if (!state) return null;
  const open = state.status === 'open' && state.pro;
  const size = state.sizes[position];
  const list = draft[position] ?? [];
  const scored = state.status === 'final' ? state.my_result?.positions[position] : undefined;
  const { ranked, total } = rankedCount(state, draft);

  const change = (next: Picks) => {
    setDraft(next);
    setDirty(true);
    setMessage(null);
  };
  const add = (p: PickPlayer) => {
    if (list.length >= size) return setMessage({ text: `Your ${position} list is full: remove someone to add ${p.name}.`, error: true });
    change({ ...draft, [position]: [...list, p.id] });
  };
  const remove = (i: number) => change({ ...draft, [position]: list.filter((_, j) => j !== i) });
  const move = (i: number, by: number) => {
    const j = i + by;
    if (j < 0 || j >= list.length) return;
    const next = [...list];
    [next[i], next[j]] = [next[j], next[i]];
    change({ ...draft, [position]: next });
  };
  const submit = async () => {
    setBusy(true);
    const err = await save(draft, name);
    setBusy(false);
    if (err) return setMessage({ text: err, error: true });
    setDirty(false);
    setMessage({ text: `Saved. You can change your picks until the Main kicks off${state.lock_at ? ` (${formatEt(state.lock_at)})` : ''}.` });
  };

  const q = query.trim().toLowerCase();
  const candidates = (state.players ?? []).filter(
    (p) => p.position === position && !list.includes(p.id) && (!q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q),
  );

  return (
    <Modal visible={editorOpen} animationType="slide" onRequestClose={() => setEditorOpen(false)}>
      <SafeAreaView className="flex-1 bg-background" edges={['top', 'bottom', 'left', 'right']}>
        <View className="picker-header">
          <Pressable onPress={() => setEditorOpen(false)} accessibilityRole="button" accessibilityLabel="Close Pro Picks" hitSlop={10} className="picker-back">
            <Text className="picker-back-text">‹ Back</Text>
          </Pressable>
          <Text className="picker-title" accessibilityRole="header">
            Week {state.week} Pro Picks
          </Text>
          <View className="picker-back items-end">
            {open ? (
              <Pressable onPress={submit} disabled={busy || !dirty} accessibilityRole="button" hitSlop={10}>
                <Text className={`link-text ${busy || !dirty ? 'opacity-50' : ''}`}>{busy ? 'Saving…' : dirty ? 'Save' : 'Saved'}</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32 }}>
          <Text className="caption mb-2">
            {state.status === 'open'
              ? `Rank who you think finishes as each position's top DraftKings scorers on the ${state.slate_label ?? 'Sunday Main'}. Locks ${formatEt(state.lock_at ?? null)}. ${ranked} of ${total} ranked.`
              : state.status === 'final'
                ? state.my_result
                  ? `Scored: ${state.my_result.accuracy}% of players ranked correctly as the top performers · ${formatPoints(state.my_result.points)} points.`
                  : "Scored. You didn't enter this week."
                : 'Locked at kickoff. Results post once every Main game is final and its stats are in.'}
          </Text>
          {open ? (
            <>
              <Text className="input-label">Your name on the leaderboard</Text>
              <TextInput
                className="input mb-3"
                value={name}
                onChangeText={(t) => {
                  setName(t);
                  setDirty(true);
                }}
                maxLength={24}
                placeholder="Leaderboard name"
                placeholderTextColor={colors.mutedForeground}
                autoCorrect={false}
              />
            </>
          ) : null}

          <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2" contentContainerClassName="chip-row-content">
            {PICK_POSITIONS.map((pos) => {
              const active = pos === position;
              return (
                <Pressable
                  key={pos}
                  className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => {
                    setPosition(pos);
                    setQuery('');
                    setLimit(CANDIDATE_PAGE);
                  }}
                  accessibilityRole="tab"
                  aria-selected={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                    {pos} {(draft[pos] ?? []).length}/{state.sizes[pos]}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>

          <Text className="section-title mb-1">
            Your top {size} {position === 'DST' ? 'defenses' : `${position}s`}
            {scored ? ` · ${formatPoints(scored.points)} pts` : ''}
          </Text>
          <View className="lineup-card">
            {Array.from({ length: size }, (_, i) => {
              const p = list[i] != null ? byId.get(list[i]) : undefined;
              const row = scored?.rows.find((r) => r.ranked === i + 1);
              return (
                <View key={i} className="lineup-row">
                  <Text className="lineup-slot">{i + 1}.</Text>
                  <View className="flex-1">
                    {p ? (
                      <>
                        <Text className="lineup-player-name" numberOfLines={1}>
                          {p.name}
                        </Text>
                        <Text className="lineup-player-meta" numberOfLines={1}>
                          {p.team} vs {p.opponent} · {formatCurrency(p.salary).replace('.00', '')} · {formatPoints(p.proj)} proj
                          {row ? (row.points > 0 ? ` · finished #${row.finished} · +${formatPoints(row.points)}` : ` · missed the top ${size}`) : ''}
                        </Text>
                      </>
                    ) : (
                      <Text className="caption">{open ? 'Open: tap a player below' : 'Not ranked'}</Text>
                    )}
                  </View>
                  {open && p ? (
                    <View className="flex-row items-center gap-3">
                      <Pressable onPress={() => move(i, -1)} disabled={i === 0} accessibilityRole="button" accessibilityLabel={`Move ${p.name} up`} hitSlop={6}>
                        <Text className={`link-text ${i === 0 ? 'opacity-30' : ''}`}>▲</Text>
                      </Pressable>
                      <Pressable
                        onPress={() => move(i, 1)}
                        disabled={i === list.length - 1}
                        accessibilityRole="button"
                        accessibilityLabel={`Move ${p.name} down`}
                        hitSlop={6}>
                        <Text className={`link-text ${i === list.length - 1 ? 'opacity-30' : ''}`}>▼</Text>
                      </Pressable>
                      <Pressable className="player-remove" onPress={() => remove(i)} accessibilityRole="button" accessibilityLabel={`Remove ${p.name}`}>
                        <Image source={icons.close} style={{ width: 12, height: 12, tintColor: colors.mutedForeground }} />
                      </Pressable>
                    </View>
                  ) : null}
                </View>
              );
            })}
          </View>

          {state.status === 'final' && state.actual_top ? (
            <>
              <Text className="section-title mb-1 mt-3">Actual top {size}</Text>
              <View className="lineup-card">
                {state.actual_top[position].map((a) => {
                  const p = byId.get(a.id);
                  return (
                    <View key={a.id} className="lineup-row">
                      <Text className="lineup-slot">{a.spot}.</Text>
                      <Text className="lineup-player-name flex-1" numberOfLines={1}>
                        {p?.name ?? a.id}
                        {list.includes(a.id) ? ' ✓' : ''}
                      </Text>
                      <Text className="lineup-proj">{formatPoints(a.points)}</Text>
                    </View>
                  );
                })}
              </View>
            </>
          ) : null}

          {message ? <Text className={`lineup-message ${message.error ? 'text-negative' : ''}`}>{message.text}</Text> : null}

          {open ? (
            <>
              <Text className="section-title mb-1 mt-3">Add {position === 'DST' ? 'defenses' : `${position}s`}</Text>
              <Text className="caption mb-2">By projection. Tap one to put him in your next open spot.</Text>
              <TextInput
                className="input mb-2"
                placeholder="Search player or team"
                placeholderTextColor={colors.mutedForeground}
                value={query}
                onChangeText={(t) => {
                  setQuery(t);
                  setLimit(CANDIDATE_PAGE);
                }}
                autoCorrect={false}
                autoCapitalize="none"
              />
              {candidates.slice(0, limit).map((p) => (
                <Pressable
                  key={p.id}
                  className={`lineup-row ${list.length >= size ? 'player-unfit' : ''}`}
                  onPress={() => add(p)}
                  accessibilityRole="button"
                  accessibilityLabel={`Rank ${p.name}`}>
                  <View className="flex-1">
                    <Text className="lineup-player-name" numberOfLines={1}>
                      {p.name}
                      {p.injury && p.injury !== 'Healthy' ? ` (${p.injury})` : ''}
                    </Text>
                    <Text className="lineup-player-meta">
                      {p.team} vs {p.opponent} · {formatCurrency(p.salary).replace('.00', '')}
                    </Text>
                  </View>
                  <Text className="lineup-proj mr-3">{formatPoints(p.proj)}</Text>
                  <View className="player-action">
                    <Image source={icons.plus} style={{ width: 12, height: 12, tintColor: colors.primaryForeground }} />
                  </View>
                </Pressable>
              ))}
              {candidates.length > limit ? (
                <Pressable className="btn-outline mt-2" onPress={() => setLimit((n) => n + CANDIDATE_PAGE)} accessibilityRole="button">
                  <Text className="btn-outline-text">Show more ({candidates.length - limit} left)</Text>
                </Pressable>
              ) : null}
              <Pressable className={`btn mt-4 ${busy || !dirty ? 'opacity-60' : ''}`} onPress={submit} disabled={busy || !dirty} accessibilityRole="button">
                <Text className="btn-text">{busy ? 'Saving…' : dirty ? 'Save my picks' : 'Picks saved'}</Text>
              </Pressable>
            </>
          ) : null}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}
