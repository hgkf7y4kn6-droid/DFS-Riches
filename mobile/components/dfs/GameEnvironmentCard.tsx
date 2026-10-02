import { Image, Pressable, Text, View } from 'react-native';

import DfsPlayerRow from '@/components/dfs/DfsPlayerRow';
import StatusView from '@/components/StatusView';
import { PLAYABLE_STATUSES } from '@/constants/data';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { useGameDetail } from '@/lib/game-detail';
import { teamLogo } from '@/lib/games';
import { formatCurrency, formatPercent, formatSigned } from '@/lib/utils';

interface Props {
  env: DfsGameEnv;
  /** The model's stacks for this game. */
  stacks: DfsStack[];
  /** Every slate player on either team. */
  players: DfsPlayer[];
  /** Schedule game id, for the matchup data (/api/breakdown/game/{id}). */
  gameId: string | null;
  expanded: boolean;
  onToggle: () => void;
}

function spreadText(env: DfsGameEnv): string {
  if (env.spread_home == null) return '-';
  if (env.spread_home === 0) return 'PK';
  return env.spread_home < 0 ? `${env.home} ${env.spread_home}` : `${env.away} -${env.spread_home}`;
}

/** Positions each defense gives up the most to, ranked across both sides. */
function Matchups({ env, gameId }: { env: DfsGameEnv; gameId: string | null }) {
  const { detail, error } = useGameDetail(gameId);
  if (!gameId) return <Text className="home-empty-state">{"Matchup data isn't available for this game."}</Text>;
  if (!detail) return <StatusView loading={!error} error={error} />;
  const rows = [
    ...detail.away_def_vs_pos.map((r) => ({ ...r, offense: env.home, defense: env.away })),
    ...detail.home_def_vs_pos.map((r) => ({ ...r, offense: env.away, defense: env.home })),
  ]
    .filter((r) => (r.vs_avg ?? 0) > 0)
    .sort((a, b) => (b.vs_avg ?? 0) - (a.vs_avg ?? 0))
    .slice(0, 5);
  const notes = [...env.trench_notes, ...(env.weather?.impact ? [`Weather: ${env.weather.impact}`] : [])];
  if (!rows.length && !notes.length) return <Text className="home-empty-state">No standout matchups in this game.</Text>;
  return (
    <View>
      {rows.map((r, i) => (
        <View key={`${r.offense}-${r.position}`} className="env-matchup">
          <Text className="dfs-rank">{i + 1}</Text>
          <View className="flex-1">
            <Text className="dfs-name">
              {r.offense} {r.position}s vs {r.defense}
            </Text>
            <Text className="dfs-meta">
              {r.defense} allow {r.allowed} DK pts/gm to {r.position}s (league {r.league_avg}){r.rank ? ` · #${r.rank} most` : ''}
            </Text>
          </View>
          <Text className="env-edge text-positive">{formatSigned((r.vs_avg ?? 0) * 100, 0)}%</Text>
        </View>
      ))}
      {notes.map((n, i) => (
        <Text key={i} className="dfs-reason">
          • {n}
        </Text>
      ))}
    </View>
  );
}

function StackCard({ stack, rank }: { stack: DfsStack; rank: number }) {
  const own = stack.players.reduce((s, p) => s + (p.ownership ?? 0), 0);
  const value = stack.salary > 0 ? stack.final / (stack.salary / 1000) : 0;
  return (
    <View className="env-stack">
      <View className="flex-row items-center justify-between">
        <Text className="dfs-name">
          {rank}. {stack.team} · {stack.type}
        </Text>
        <Text className="dfs-salary">{formatCurrency(stack.salary)}</Text>
      </View>
      <Text className="dfs-stats">
        {stack.final.toFixed(1)} proj · {stack.ceiling.toFixed(1)} ceil · {value.toFixed(2)} pts/$1k · {formatPercent(own / 100, 0)} combined own
      </Text>
      <Text className="dfs-meta mt-1">
        {stack.players.map((p) => `${p.name} (${p.position} ${p.team})`).join(' + ')}
      </Text>
      <Text className="dfs-reason">• {stack.reason}</Text>
      {stack.bring_back_note ? <Text className="dfs-reason">• Bring-back: {stack.bring_back_note}</Text> : null}
    </View>
  );
}

/**
 * One game environment, ranked best to worst. Collapsed: environment and
 * popularity rank, lines, script. Tap to expand: the 1-5 best stacks (by the
 * model's stack score: environment, ceiling vs salary, popularity), the
 * matchups to exploit, and the players to target ranked by ceiling. Tap the
 * header again to collapse.
 */
export default function GameEnvironmentCard({ env, stacks, players, gameId, expanded, onToggle }: Props) {
  const colors = useThemeColors();
  const best = [...stacks].sort((a, b) => b.score - a.score).slice(0, 5);
  const targets = players
    .filter((p) => PLAYABLE_STATUSES.has(p.injury ?? 'Healthy') && p.final > 0)
    .sort((a, b) => (b.ceiling ?? 0) - (a.ceiling ?? 0) || b.final - a.final)
    .slice(0, 8);
  const tags = [env.shootout && 'Shootout', env.negative_script && 'Negative script', env.live_dog && `Live dog: ${env.underdog}`].filter(
    Boolean,
  ) as string[];

  return (
    <View className={`env-card ${expanded ? 'slate-card-active' : ''}`}>
      <Pressable onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded }}>
        <View className="flex-row items-center gap-3">
          <View className="env-rank">
            <Text className="env-rank-text">#{env.env_rank}</Text>
          </View>
          <View className="upcoming-logos">
            <Image source={teamLogo(env.away)} className="upcoming-icon" style={{ width: 32, height: 32 }} resizeMode="contain" />
            <Image source={teamLogo(env.home)} className="upcoming-icon" style={{ width: 32, height: 32, marginLeft: -8 }} resizeMode="contain" />
          </View>
          <View className="flex-1">
            <Text className="slate-card-title">
              {env.away} @ {env.home}
            </Text>
            <Text className="slate-card-meta">{env.kickoff}</Text>
          </View>
          <Image
            source={icons.chevron}
            style={{ width: 16, height: 16, tintColor: colors.foreground, transform: [{ rotate: expanded ? '180deg' : '0deg' }] }}
          />
        </View>
        <Text className="dfs-stats mt-2">
          O/U {env.total ?? '-'} · {spreadText(env)} · {env.away} {env.away_implied ?? '-'} / {env.home} {env.home_implied ?? '-'}
        </Text>
        <Text className="dfs-meta">
          Popularity #{env.pop_rank} · {formatPercent(env.pop_share, 0)} of the field · env score {env.env_score.toFixed(2)}
        </Text>
        {tags.length ? <Text className="slate-card-status mt-1">{tags.join(' · ')}</Text> : null}
        <Text className="dfs-reason mt-1">{env.script}</Text>
      </Pressable>

      {expanded ? (
        <View className="slate-card-body">
          <Text className="detail-title">Best stacks</Text>
          {best.length ? best.map((s, i) => <StackCard key={`${s.team}-${s.type}-${i}`} stack={s} rank={i + 1} />) : (
            <Text className="home-empty-state">No stacks for this game.</Text>
          )}
          <Text className="detail-title mt-4">Matchups to exploit</Text>
          <Matchups env={env} gameId={gameId} />
          <Text className="detail-title mt-4">Players to target (by ceiling)</Text>
          {targets.map((p, i) => (
            <DfsPlayerRow key={p.id} player={p} rank={i + 1} metric="ceiling" />
          ))}
        </View>
      ) : null}
    </View>
  );
}
