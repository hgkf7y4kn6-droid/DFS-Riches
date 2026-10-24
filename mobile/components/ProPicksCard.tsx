import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { ProSheet } from '@/components/ProLock';
import { track } from '@/lib/analytics';
import { rankedCount, useProPicks } from '@/lib/pro-picks-context';
import { formatEt, formatPoints } from '@/lib/utils';

const STANDINGS_SHOWN = 5;

/**
 * Home: this week's Weekly Pro Picks -- rank the Sunday Main's top scorers by position, see who else entered
 * once it locks, and the standings once it's scored. Free accounts see what it is and how to unlock it.
 */
export default function ProPicksCard() {
  const { state, loading, error, refresh, setEditorOpen } = useProPicks();
  const [proOpen, setProOpen] = useState(false);
  const [howOpen, setHowOpen] = useState(false);
  if (!state && !loading && !error) return null;

  const openEditor = () => {
    track('pro_picks_opened', { status: state?.status ?? 'unknown' });
    setEditorOpen(true);
  };
  const { ranked, total } = rankedCount(state, state?.mine?.picks);
  const s = state?.scoring;
  const top = state?.standings ?? [];
  const me = state?.my_result;
  const shown = top.slice(0, STANDINGS_SHOWN);
  const meBelow = me && !shown.some((r) => r.me) ? top.find((r) => r.me) : null;

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
            Locked at kickoff. Results post once every Main game is final.
            {state.mine ? ` You ranked ${ranked} of ${total}.` : " You didn't enter this week."}
          </Text>
          {state.entrant_names?.length ? (
            <Text className="caption mt-1" numberOfLines={2}>
              In this week: {state.entrant_names.join(', ')}
            </Text>
          ) : null}
          {state.mine ? (
            <Pressable className="btn-outline mt-3" onPress={openEditor} accessibilityRole="button">
              <Text className="btn-outline-text">View your picks</Text>
            </Pressable>
          ) : null}
        </>
      ) : (
        <>
          {me ? (
            <Text className="detail-headline mt-2">
              You finished #{me.rank} of {top.length} · {formatPoints(me.points)} pts ({me.pct_of_perfect}% of perfect)
            </Text>
          ) : (
            <Text className="caption mt-2">You didn&apos;t enter this week. {top.length} Pro users did.</Text>
          )}
          <View className="mt-2">
            {[...shown, ...(meBelow ? [meBelow] : [])].map((r) => (
              <View key={`${r.rank}-${r.name}`} className="detail-row">
                <Text className={`detail-row-label ${r.me ? 'font-bold' : ''}`} numberOfLines={1}>
                  {r.rank}. {r.name}
                  {r.me ? ' (you)' : ''}
                </Text>
                <Text className="detail-row-value">{formatPoints(r.points)}</Text>
                <Text className="detail-row-value">{r.hits} hits</Text>
              </View>
            ))}
          </View>
          <Pressable className="btn-outline mt-3" onPress={openEditor} accessibilityRole="button">
            <Text className="btn-outline-text">{me ? 'Your scorecard and the actual top scorers' : 'See the actual top scorers'}</Text>
          </Pressable>
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
