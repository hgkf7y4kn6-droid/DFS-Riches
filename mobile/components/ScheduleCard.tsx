import { useState } from 'react';
import { Text, View } from 'react-native';

import ExpandableCard from '@/components/ExpandableCard';
import { HOME_SECTIONS } from '@/constants/data';
import { weatherText } from '@/lib/lines';
import { formatDayPart } from '@/lib/utils';

function GameRow({ game, last }: { game: Game; last: boolean }) {
  const c = game.context;
  const final = c?.is_final;
  return (
    <View className={`game-row ${last ? '' : 'border-b border-border'}`}>
      <View className="flex-1 pr-2">
        <Text className="game-matchup">
          {game.away} @ {game.home}
        </Text>
        <Text className="game-meta">
          {game.kickoff_et}
          {game.network ? ` · ${game.network}` : ''}
        </Text>
        {game.weather ? <Text className="game-meta">{weatherText(game.weather)}</Text> : null}
      </View>
      <View className="items-end gap-1">
        {final ? (
          <Text className="text-sm font-semibold text-primary">
            {c?.away_score}-{c?.home_score}
          </Text>
        ) : c?.total_line != null ? (
          <Text className="game-meta">O/U {c.total_line.toFixed(1)}</Text>
        ) : null}
        {game.isolated ? (
          <View className="badge">
            <Text className="badge-text">{formatDayPart(game.day_part)}</Text>
          </View>
        ) : null}
      </View>
    </View>
  );
}

/** Expandable card with every game this week; collapsed it shows the next kickoff. */
export default function ScheduleCard({ schedule }: { schedule: WeekSchedule }) {
  const section = HOME_SECTIONS.schedule;
  const [now] = useState(() => Date.now());
  const next = schedule.games.find((g) => new Date(g.kickoff_utc).getTime() > now);
  return (
    <ExpandableCard
      title={`${section.title} · Week ${schedule.week}`}
      subtitle={section.subtitle}
      aside={`${schedule.games.length} games`}
      defaultExpanded={section.defaultExpanded}
      preview={
        <Text className="game-meta">
          {next ? `Next: ${next.away} @ ${next.home} · ${next.kickoff_et}` : 'Every game this week has kicked off'}
        </Text>
      }>
      {schedule.games.map((g, i) => (
        <GameRow key={g.game_id} game={g} last={i === schedule.games.length - 1} />
      ))}
    </ExpandableCard>
  );
}
