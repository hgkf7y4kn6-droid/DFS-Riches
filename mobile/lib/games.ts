// Turns API games into the UpcomingGame shape the game cards display.
import dayjs from '@/lib/dayjs';
import { weatherText } from '@/lib/lines';
import { formatDayPart, formatGameDate, formatGameTime, formatSigned } from '@/lib/utils';

/** A team's logo from Sleeper's CDN (the app's projection source), e.g. "IND" -> .../ind.png. */
export function teamLogo(team: string): { uri: string } {
  return { uri: `https://sleepercdn.com/images/team_logos/nfl/${team.toLowerCase()}.png` };
}

function linesText(g: Game): string {
  const c = g.context;
  if (!c) return 'Lines not posted';
  const parts: string[] = [];
  if (c.away_spread != null && c.home_spread != null) {
    if (c.away_spread === c.home_spread) parts.push('PK');
    else if (c.away_spread < c.home_spread) parts.push(`${g.away} ${formatSigned(c.away_spread)}`);
    else parts.push(`${g.home} ${formatSigned(c.home_spread)}`);
  }
  if (c.total_line != null) parts.push(`O/U ${c.total_line.toFixed(1)}`);
  return parts.length ? parts.join(' · ') : 'Lines not posted';
}

export function toUpcomingGame(g: Game, now: number = Date.now()): UpcomingGame {
  const kickoff = dayjs(g.kickoff_utc);
  const c = g.context;
  const final = Boolean(c?.is_final);
  const started = kickoff.valueOf() <= now;
  return {
    id: g.game_id,
    name: `${g.away} @ ${g.home}`,
    location: g.weather?.venue || `${g.home} home stadium`,
    kickoff: `${formatGameDate(g.kickoff_utc)} · ${formatGameTime(g.kickoff_utc)}`,
    network: g.network,
    daysLeft: kickoff.startOf('day').diff(dayjs(now).startOf('day'), 'day'),
    status: final ? 'final' : started ? 'live' : 'upcoming',
    score: c?.away_score != null && c.home_score != null ? `${g.away} ${c.away_score} - ${g.home} ${c.home_score}` : null,
    lines: linesText(g),
    weather: weatherText(g.weather) || 'Forecast not available',
    icon: teamLogo(g.away),
    opponentIcon: teamLogo(g.home),
    islandLabel: g.isolated ? formatDayPart(g.day_part) : null,
  };
}

/** Where a slate stands: upcoming until its first kickoff, live until every game is final. */
export function slateStatus(slate: Slate, now: number = Date.now()): { status: UpcomingGameStatus; daysLeft: number; firstKickoff: string | null } {
  const kickoffs = slate.games.map((g) => g.kickoff_utc).sort();
  const firstKickoff = kickoffs[0] ?? null;
  if (!firstKickoff) return { status: 'upcoming', daysLeft: 0, firstKickoff };
  const allFinal = slate.games.every((g) => g.context?.is_final);
  const started = new Date(firstKickoff).getTime() <= now;
  return {
    status: allFinal ? 'final' : started ? 'live' : 'upcoming',
    daysLeft: dayjs(firstKickoff).startOf('day').diff(dayjs(now).startOf('day'), 'day'),
    firstKickoff,
  };
}
