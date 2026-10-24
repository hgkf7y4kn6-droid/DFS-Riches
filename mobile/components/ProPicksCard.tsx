import { useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import PicksComparison from '@/components/PicksComparison';
import { ProSheet } from '@/components/ProLock';
import { track } from '@/lib/analytics';
import { PICK_POSITIONS, rankedCount, useProPicks } from '@/lib/pro-picks-context';
import { formatEt, formatPoints } from '@/lib/utils';

/** 1 -> "1st", 22 -> "22nd", 13 -> "13th". */
function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
  return `${n}${s}`;
}

/**
 * Home: this week's Weekly Pro Picks -- rank the Sunday Main's top scorers by position, then, once it's
 * scored, where you finished among every Pro entry, how accurate you were, and your picks side by side with
 * who actually finished at each spot (only your own result: no leaderboard of other users). Free accounts
 * see what it is and how to unlock it.
 */
export default function ProPicksCard() {
  const { state, loading, error, refresh, setEditorOpen } = useProPicks();
  const [proOpen, setProOpen] = useState(false);
  const [howOpen, setHowOpen] = useState(false);
  const [position, setPosition] = useState<PickPosition>('QB');
  const byId = useMemo(() => new Map((state?.players ?? []).map((p) => [p.id, p])), [state?.players]);
  if (!state && !loading && !error) return null;

  const openEditor = () => {
    track('pro_picks_opened', { status: state?.status ?? 'unknown' });
    setEditorOpen(true);
  };
  const { ranked, total } = rankedCount(state, state?.mine?.picks);
  const s = state?.scoring;
  const me = state?.my_result;

  return (
    <View className="section card">
      <Text className="intro-kicker">Riches Analytics Pro</Text>
      <Text className="section-title">Weekly Pro Picks{state ? ` · Week ${state.week}` : ''}</Text>
      <Text className="section-subtitle">Rank the Sunday Main&apos;s top scorers at each position and see how you stack up against other Pro users.</Text>

      {!state ? (
        error ? (
          <Pressable onPress={refresh} accessibilityRole="button" className="mt-2">
            <Text className="error-text text-left">Couldn&apos;t load Pro Picks: {error} · Tap to retry</Text>
          </Pressable>
        ) : (
          <Text className="caption mt-2">Loading…</Text>
        )
      ) : state.status === 'no_slate' ? (
        <Text className="caption mt-2">Opens when DraftKings posts the Week {state.week} Sunday Main salaries.</Text>
      ) : !state.pro ? (
        <>
          <Text className="caption mt-2">
            {state.entrants ? `${state.entrants} Pro user${state.entrants === 1 ? ' has' : 's have'} entered this week. ` : ''}A free weekly competition for
            Pro accounts.
          </Text>
          <Pressable
            className="btn-accent mt-3"
            onPress={() => {
              track('pro_unlock_tapped', { feature: 'competition' });
              setProOpen(true);
            }}
            accessibilityRole="button">
            <Text className="btn-text">Unlock with Pro</Text>
          </Pressable>
          <ProSheet feature="competition" visible={proOpen} onClose={() => setProOpen(false)} />
        </>
      ) : state.status === 'open' ? (
        <>
          <Text className="caption mt-2">
            Locks {formatEt(state.lock_at ?? null)} · {state.entrants} Pro user{state.entrants === 1 ? '' : 's'} in
            {state.mine ? ` · you've ranked ${ranked} of ${total}` : ''}
          </Text>
          <Pressable className="btn-accent mt-3" onPress={openEditor} accessibilityRole="button">
            <Text className="btn-text">{state.mine ? 'Edit your picks' : 'Make your picks'}</Text>
          </Pressable>
        </>
      ) : state.status === 'locked' ? (
        <>
          <Text className="caption mt-2">
            Locked at kickoff · {state.entrants} Pro user{state.entrants === 1 ? '' : 's'} submitted rankings. Results post once every Main game is final.
            {state.mine ? ` You ranked ${ranked} of ${total}.` : " You didn't enter this week."}
          </Text>
          {state.mine ? (
            <Pressable className="btn-outline mt-3" onPress={openEditor} accessibilityRole="button">
              <Text className="btn-outline-text">View your picks</Text>
            </Pressable>
          ) : null}
        </>
      ) : (
        <>
          {me ? (
            <>
              <Text className="detail-headline mt-2">
                You finished {ordinal(me.rank)} out of {state.entrants} Pro user submitted ranking{state.entrants === 1 ? '' : 's'} with an accuracy of{' '}
                {me.accuracy}% of players ranked correctly as the top performers.
              </Text>
              <Text className="caption mt-1">
                {me.hits} of {total} top-scorer spots hit · {me.exact} in the exact spot · {formatPoints(me.points)} points ({me.pct_of_perfect}% of a
                perfect week)
              </Text>
            </>
          ) : (
            <Text className="caption mt-2">
              You didn&apos;t enter this week. {state.entrants} Pro user{state.entrants === 1 ? '' : 's'} did.
            </Text>
          )}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2 mt-3" contentContainerClassName="chip-row-content">
            {PICK_POSITIONS.map((pos) => {
              const active = pos === position;
              const hits = me?.positions[pos]?.hits;
              return (
                <Pressable
                  key={pos}
                  className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => setPosition(pos)}
                  accessibilityRole="tab"
                  aria-selected={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                    {pos}
                    {hits != null ? ` ${hits}/${state.sizes[pos]}` : ''}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
          <PicksComparison state={state} position={position} picks={state.mine?.picks[position] ?? []} byId={byId} />
        </>
      )}

      {state && state.status !== 'no_slate' && s ? (
        <>
          <Pressable onPress={() => setHowOpen((o) => !o)} accessibilityRole="button" aria-expanded={howOpen} className="mt-3">
            <Text className="link-text">{howOpen ? 'Hide how scoring works' : 'How scoring works'}</Text>
          </Pressable>
          {howOpen ? (
            <View className="mt-1">
              <Text className="caption">
                • Rank your top {state.sizes.QB} QBs, {state.sizes.RB} RBs, {state.sizes.WR} WRs, {state.sizes.TE} TEs and {state.sizes.DST} defenses by
                DraftKings points.
              </Text>
              <Text className="caption">• +{s.hit} for each player who finishes in that position&apos;s top list, wherever you ranked him.</Text>
              <Text className="caption">• +{s.exact} more when he finishes in exactly the spot you ranked him.</Text>
              <Text className="caption">
                • Tie-breaker: −{s.lower} per spot he finishes below your ranking, −{s.higher} per spot above it.
              </Text>
              <Text className="caption">• A perfect week is {formatPoints(state.perfect)} points.</Text>
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}
