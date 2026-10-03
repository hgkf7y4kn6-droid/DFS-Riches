import { ActivityIndicator, Text, View } from 'react-native';

import { useThemeColors } from '@/constants/theme';
import { matchupTone, useMatchups, type MatchupTone } from '@/lib/matchups-context';
import { usePlayerGames } from '@/lib/player-games';
import { useWeek } from '@/lib/week-context';

const ORDER: (keyof PlayerGameStats)[] = ['passing', 'rushing', 'receiving', 'defense'];

/** One stat group as a readable line, e.g. "22/33 · 310 yds · 2 TD · 1 INT". */
function line(group: keyof PlayerGameStats, s: PlayerGameStats): string | null {
  switch (group) {
    case 'passing': {
      const p = s.passing;
      return p ? `${p.cmp}/${p.att} · ${p.yds} yds · ${p.td} TD · ${p.int} INT${p.sacks ? ` · ${p.sacks} sk` : ''}` : null;
    }
    case 'rushing': {
      const r = s.rushing;
      return r ? `${r.att} car · ${r.yds} yds${r.att ? ` (${(r.yds / r.att).toFixed(1)} ypc)` : ''} · ${r.td} TD` : null;
    }
    case 'receiving': {
      const r = s.receiving;
      if (!r) return null;
      const share = r.target_share ? ` (${Math.round(r.target_share * 100)}% share)` : '';
      return `${r.rec}/${r.tgt} tgt${share} · ${r.yds} yds · ${r.td} TD`;
    }
    case 'defense': {
      const d = s.defense;
      if (!d) return null;
      return `${d.sacks} sk · ${d.int} INT · ${d.fum_rec} FR · ${d.td} TD${d.pts_allowed != null ? ` · ${d.pts_allowed} pts allowed` : ''}`;
    }
  }
}

const RANK_TEXT: Record<MatchupTone, string> = {
  soft: 'game-log-rank text-success',
  neutral: 'game-log-rank',
  tough: 'game-log-rank text-danger',
};

/** "Soft schedule: ..." from the average rank (vs this position) of the defenses faced. */
function scheduleNote(ranks: number[], teams: number, position: string, mode: MatchupMode): { tone: MatchupTone; text: string } | null {
  if (!ranks.length) return null;
  const avg = ranks.reduce((a, b) => a + b, 0) / ranks.length;
  const tone = matchupTone(avg, teams);
  const who = position === 'DST' ? 'offenses' : `defenses vs ${position}`;
  const basis = `${mode === 'adj' ? 'schedule-adjusted' : 'raw'} FP rank, #1 = allows the most`;
  const head = `Faced ${who} averaging #${avg.toFixed(0)} (${basis}).`;
  if (tone === 'soft') return { tone, text: `Soft schedule: ${head} These numbers may be inflated by easy matchups.` };
  if (tone === 'tough') return { tone, text: `Tough schedule: ${head} The numbers may undersell this player.` };
  return { tone, text: `Neutral schedule: ${head}` };
}

const GROUP_LABEL: Record<keyof PlayerGameStats, string> = {
  passing: 'Pass',
  rushing: 'Rush',
  receiving: 'Rec',
  defense: 'Def',
};

/**
 * The player's last games before this week: snap share, DK points, and only
 * the stat lines that matter for the position (passing + rushing for QBs,
 * rushing + receiving for RBs, receiving for WRs/TEs, team defense for DSTs).
 */
export default function GameLog({ player }: { player: PlayPlayer }) {
  const colors = useThemeColors();
  const { season } = useWeek();
  const { lookup, mode } = useMatchups();
  const { data, loading, error } = usePlayerGames(player);

  if (loading) {
    return (
      <View className="game-log flex-row items-center gap-2">
        <ActivityIndicator size="small" color={colors.accent} />
        <Text className="game-log-snaps">Loading game log…</Text>
      </View>
    );
  }
  if (error || !data) return <Text className="dfs-reason">Game log unavailable{error ? `: ${error}` : ''}</Text>;
  if (!data.games.length) return <Text className="dfs-reason">No games played yet this season or last.</Text>;

  const s = data.summary;
  const ranked = data.games.map((g) => lookup(g.opponent, player.position));
  const known = ranked.filter((m): m is NonNullable<typeof m> => m != null);
  const schedule = scheduleNote(known.map((m) => m.fp_rank), known[0]?.teams ?? 32, player.position, mode);
  return (
    <View className="game-log">
      <Text className="game-log-title">Last {s.games} games</Text>
      <Text className="game-log-summary">
        {s.avg_dk_points?.toFixed(1)} DK pts / game{s.avg_snap_pct != null ? ` · ${Math.round(s.avg_snap_pct)}% snaps` : ''}
      </Text>
      {schedule ? <Text className={`game-log-schedule ${RANK_TEXT[schedule.tone]}`}>{schedule.text}</Text> : null}
      {data.games.map((g, i) => (
        <View key={`${g.season}-${g.week}`} className="game-log-game">
          <View className="game-log-head">
            <Text className="game-log-week">
              {g.season !== season ? `${g.season} ` : ''}Wk {g.week} vs {g.opponent}
              {ranked[i] ? (
                <Text className={RANK_TEXT[matchupTone(ranked[i].fp_rank, ranked[i].teams)]}> #{ranked[i].fp_rank}</Text>
              ) : null}
              {g.snap_pct != null ? (
                <Text className="game-log-snaps">
                  {'  '}
                  {Math.round(g.snap_pct)}% snaps{g.offense_snaps != null ? ` (${g.offense_snaps})` : ''}
                </Text>
              ) : null}
            </Text>
            <Text className="game-log-pts">{g.dk_points.toFixed(1)} pts</Text>
          </View>
          {ORDER.map((k) => {
            const text = line(k, g.stats);
            return text ? (
              <Text key={k} className="game-log-line">
                <Text className="game-log-group">{GROUP_LABEL[k]} </Text>
                {text}
              </Text>
            ) : null;
          })}
        </View>
      ))}
    </View>
  );
}
