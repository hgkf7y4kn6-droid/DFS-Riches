import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import TrendChips from '@/components/TrendChips';

import { atsCell, finalCell, impliedCell, paceCell, spreadCell, totalCell, totalResultCell, weatherText, type Cell } from '@/lib/lines';

const TONE_CLASS: Record<string, string> = {
  positive: 'text-positive',
  negative: 'text-negative',
  pending: 'text-pending',
  neutral: '',
};

function LinesCell({ label, cell, wide, detail }: { label: string; cell: Cell; wide?: boolean; detail?: boolean }) {
  return (
    <View className={wide ? 'lines-cell-wide' : 'lines-cell'}>
      <Text className="lines-label">{label}</Text>
      <Text className={`lines-value ${TONE_CLASS[cell.tone ?? 'neutral']}`}>{cell.text}</Text>
      {cell.sub ? <Text className="lines-sub">{cell.sub}</Text> : null}
      {detail && cell.trends?.map((t) => (
        <TrendChips
          key={t.label}
          label={t.label}
          windows={t.windows}
          baseline={t.baseline}
          better={t.better}
          steps={t.steps}
          absolute
          format={t.format}
        />
      ))}
    </View>
  );
}

/** Collapsed: the lines and results. Tap for each team's recent form (L3/L6/L9 chips) and pace. */
function GameLines({ game }: { game: Game }) {
  const [open, setOpen] = useState(false);
  return (
    <Pressable className="lines-card" onPress={() => setOpen((o) => !o)} accessibilityRole="button" aria-expanded={open}>
      <View className="flex-row items-start justify-between">
        <View className="flex-1 pr-2">
          <Text className="game-matchup">
            {game.away} @ {game.home}
          </Text>
          <Text className="game-meta">
            {game.kickoff_et}
            {game.weather ? ` · ${weatherText(game.weather)}` : ''}
          </Text>
        </View>
        <Text className="game-score">{finalCell(game).text}</Text>
      </View>
      <View className="lines-grid">
        <LinesCell label="Spread" cell={spreadCell(game)} wide detail={open} />
        <LinesCell label="Total" cell={totalCell(game)} detail={open} />
        <LinesCell label="Implied totals" cell={impliedCell(game)} detail={open} />
        <LinesCell label="Vs spread" cell={atsCell(game)} detail={open} />
        <LinesCell label="Vs total" cell={totalResultCell(game)} detail={open} />
        {open ? <LinesCell label="Pace vs baseline (plays)" cell={paceCell(game)} wide detail /> : null}
      </View>
      <Text className="upcoming-expand-hint mt-1">{open ? 'Less ▲' : 'Recent form and pace ▼'}</Text>
    </Pressable>
  );
}

/**
 * Lines & Performance as a vertical list: each game's closing spread, total
 * and implied team totals (with each team's trailing L3/L6/L9 averages as
 * conditionally-colored chips -- each shows once the team has played that
 * many games this season), and
 * once final, how the result landed against each line and each team's pace.
 */
export default function LinesList({ games }: { games: Game[] }) {
  return (
    <View>
      {games.map((g) => (
        <GameLines key={g.game_id} game={g} />
      ))}
    </View>
  );
}
