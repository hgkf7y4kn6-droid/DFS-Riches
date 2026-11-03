import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import ExpandableCard from '@/components/ExpandableCard';
import { useRecap } from '@/lib/recap';
import { formatSigned } from '@/lib/utils';

const TONE: Record<RecapGame['tone'], string> = { good: 'text-positive', warn: 'text-negative', neutral: 'text-pending' };

/** "vs DEN (-1.5) · Sun 11/1 4:25 PM ET", or "at KC · played 17-24" once that game is final. */
function nextText(n: RecapNext): string {
  const spread = n.spread != null ? ` (${n.spread > 0 ? '+' : ''}${n.spread})` : '';
  const when = n.final ? `played ${n.team_score}-${n.opponent_score}` : n.kickoff_et;
  return `${n.home ? 'vs' : 'at'} ${n.opponent}${spread} · ${when}`;
}

function Flagged({ title, subtitle, flags }: { title: string; subtitle: string; flags: RecapFlag[] }) {
  if (!flags.length) return null;
  return (
    <View className="mt-3">
      <Text className="detail-subhead">{title}</Text>
      <Text className="detail-note">{subtitle}</Text>
      {flags.map((f) => (
        <View key={`${f.team}-${f.game_id}`} className="detail-target">
          <Text className="detail-target-name">
            {f.team} <Text className="detail-target-meta">vs {f.opponent} · neutral-script EPA/play {formatSigned(f.neutral_margin, 2)}</Text>
          </Text>
          <Text className="detail-bullet">{f.reason}</Text>
          {f.next ? <Text className="detail-target-meta">This week: {nextText(f.next)}</Text> : null}
        </View>
      ))}
    </View>
  );
}

function TeamAudit({ team, d }: { team: string; d: RecapTeam }) {
  return (
    <View className="mt-2">
      <Text className="detail-subhead">
        {team} {d.score}
        {d.tag !== 'steady' ? ` · ${d.tag}` : ''}
      </Text>
      {d.signal.length ? <Text className="detail-note">Signal: what repeats</Text> : null}
      {d.signal.map((t, i) => (
        <Text key={`s${i}`} className="detail-bullet">
          • {t}
        </Text>
      ))}
      {d.noise.length ? <Text className="detail-note">Noise: what likely won&apos;t</Text> : null}
      {d.noise.map((t, i) => (
        <Text key={`n${i}`} className="detail-bullet">
          • {t}
        </Text>
      ))}
    </View>
  );
}

function GameRow({ g }: { g: RecapGame }) {
  const [open, setOpen] = useState(false);
  return (
    <View className="detail-target">
      <Pressable onPress={() => setOpen((o) => !o)} accessibilityRole="button" aria-expanded={open} accessibilityLabel={`${g.away} at ${g.home}, ${g.verdict}`}>
        <View className="flex-row items-center justify-between">
          <Text className="detail-target-name">
            {g.away} {g.away_score} @ {g.home} {g.home_score}
          </Text>
          <Text className={`detail-target-meta ${TONE[g.tone]}`}>{g.verdict}</Text>
        </View>
        <Text className="detail-target-meta">{open ? 'Hide audit ▲' : 'Signal vs noise ▼'}</Text>
      </Pressable>
      {open ? Object.entries(g.teams).map(([team, d]) => <TeamAudit key={team} team={team} d={d} />) : null}
    </View>
  );
}

/**
 * Home: last week's recap (app.recap) as a reminder when looking at this week's games -- which results the play
 * backed up, which teams were better than their score (ascending) or worse (fragile), and each team's opponent
 * this week. Collapsed by default; the games expand one by one into their signal-vs-noise audit.
 */
export default function RecapCard() {
  const { recap, error, loading, week } = useRecap();
  const [allOpen, setAllOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  if (!week) return null;
  if (!loading && !error && !recap?.available) return null;

  const up = recap?.ascending.length ?? 0;
  const down = recap?.fragile.length ?? 0;
  const preview = recap ? (
    <View className="mt-1">
      {up ? (
        <Text className="detail-note">
          Ascending: {recap.ascending.map((f) => f.team).join(', ')}
        </Text>
      ) : null}
      {down ? (
        <Text className="detail-note">
          Fragile: {recap.fragile.map((f) => f.team).join(', ')}
        </Text>
      ) : null}
      {!up && !down ? <Text className="detail-note">Every result matched the underlying play.</Text> : null}
    </View>
  ) : null;

  return (
    <ExpandableCard
      title={`Week ${week} recap`}
      subtitle="What last week's results hide: signal vs noise"
      aside={recap ? `${recap.games.length} games` : undefined}
      preview={preview}>
      {!recap ? (
        <Text className="caption">{error ? `Couldn't load the recap: ${error}` : 'Loading…'}</Text>
      ) : (
        <View>
          <Text className="caption">
            Scores swing on turnovers, red-zone luck and garbage time. Signal is what repeats (early-down success, neutral-script EPA, pass rate
            over expected, pressure); noise regresses (turnover margin, fumble recoveries, red-zone and third-and-long rates, defensive
            touchdowns, trailing volume).
          </Text>
          <Flagged title="Ascending" subtitle="Played better than the score, or the bounces went against them" flags={recap.ascending} />
          <Flagged title="Fragile" subtitle="Won or stayed close while out-played, or the bounces carried them" flags={recap.fragile} />
          <Pressable className="btn-outline mt-3" onPress={() => setAllOpen((o) => !o)} accessibilityRole="button" aria-expanded={allOpen}>
            <Text className="btn-outline-text">{allOpen ? 'Hide every game' : `Every game's audit (${recap.games.length})`}</Text>
          </Pressable>
          {allOpen ? recap.games.map((g) => <GameRow key={g.game_id} g={g} />) : null}
          <Pressable onPress={() => setNotesOpen((o) => !o)} accessibilityRole="button" aria-expanded={notesOpen} className="mt-3">
            <Text className="link-text">{notesOpen ? 'Hide what this leaves out' : 'What this leaves out'}</Text>
          </Pressable>
          {notesOpen ? (
            <View className="mt-1">
              <Text className="caption">
                Neutral script = win probability 20-80%; early downs are counted at 10-90%; garbage time = under 10%. Pressure is a sack or QB hit
                over dropbacks, compared with the league&apos;s rate this season.
              </Text>
              {recap.unavailable.map((t) => (
                <Text key={t} className="caption">
                  • {t}
                </Text>
              ))}
            </View>
          ) : null}
        </View>
      )}
    </ExpandableCard>
  );
}
