import { API_BASE_URL } from '@/constants/config';

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // not JSON: keep the status line
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

const q = (season: number, week: number) => `season=${season}&week=${week}`;

/** Sleeper's current NFL state: { season, week, display_week, season_type, ... }; display_week moves on once that week's games are all complete. */
export function getNflState() {
  return getJson<{ season: string; week: number; display_week?: number; season_type: string }>('/api/state');
}

/** Schedule + slates for a week in one round trip. */
export function getWeek(season: number, week: number) {
  return getJson<WeekData>(`/api/week?${q(season, week)}`);
}

export function getSlatePlayers(season: number, week: number, slateId: string) {
  return getJson<SlatePlayers>(`/api/slates/${encodeURIComponent(slateId)}/players?${q(season, week)}`);
}

export function getOptimal(season: number, week: number, slateId: string) {
  return getJson<OptimalResponse>(`/api/slates/${encodeURIComponent(slateId)}/optimal?${q(season, week)}`);
}

/** One game's Weekly Breakdown: lines, team profiles, matchups, usage, DFS targets, postgame. */
export function getGameDetail(season: number, week: number, gameId: string) {
  return getJson<GameDetail>(`/api/breakdown/game/${encodeURIComponent(gameId)}?${q(season, week)}`);
}

/** The DFS model for a Classic slate (the server picks the main slate when slateId is omitted). */
export function getDfsModel(season: number, week: number, slateId?: string | null) {
  const slate = slateId ? `&slate_id=${encodeURIComponent(slateId)}` : '';
  return getJson<DfsModel>(`/api/dfs-model?${q(season, week)}${slate}`);
}

/** Cash or GPP play rankings plus every player's expected field ownership and tags. */
export function getPlays(season: number, week: number, contest: PlayContest, slateId?: string | null) {
  const slate = slateId ? `&slate_id=${encodeURIComponent(slateId)}` : '';
  return getJson<PlaysResponse>(`/api/plays?${q(season, week)}&contest=${contest}${slate}`);
}

/** A player's last few games before this week: snap share, DK points and position-relevant stats. */
export function getPlayerGames(season: number, week: number, player: { name: string; position: string; team: string }) {
  const params = `name=${encodeURIComponent(player.name)}&position=${player.position}&team=${player.team}`;
  return getJson<PlayerGamesResponse>(`/api/player-games?${q(season, week)}&${params}`);
}

/** Every defense's rank vs each position (DK points and efficiency allowed), raw and schedule-adjusted. */
export function getDefenseVsPosition(season: number, week: number) {
  return getJson<DefenseVsPosition>(`/api/defense-vs-position?${q(season, week)}`);
}

/** The 15 best DraftKings NFL GPPs for a mix of max-entries groups, fee groups (empty = all) and kinds to leave out, scored with the user's weights. */
export function getBestContests(sel: {
  entries: string[];
  fees: string[];
  exclude: string[];
  /** Points (0-10) per factor; null = the server's defaults. */
  weights: Record<ContestFactor, number> | null;
}) {
  const lists = { ...sel, weights: sel.weights ? Object.entries(sel.weights).map(([k, v]) => `${k}:${v}`) : [] };
  const query = (['entries', 'fees', 'exclude', 'weights'] as const)
    .filter((k) => lists[k].length)
    .map((k) => `${k}=${encodeURIComponent(lists[k].join(','))}`)
    .join('&');
  return getJson<BestContestsResponse>(`/api/contests/best${query ? `?${query}` : ''}`);
}

/** Free DraftKings NFL contests that pay cash. */
export function getFreeContests() {
  return getJson<FreeContestsResponse>('/api/contests/free');
}

/** The signed-in user's synced data (needs Clerk's session token). */
export async function getAccount(token: string): Promise<AccountData> {
  const res = await fetch(`${API_BASE_URL}/api/me`, { headers: { Accept: 'application/json', Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as AccountData;
}

/** Stores one synced document; the server keeps the newest by updated_at and returns what it kept. */
export async function putAccountDoc(token: string, key: SyncKey, value: unknown, updatedAt: string): Promise<SyncedDoc> {
  const res = await fetch(`${API_BASE_URL}/api/me/data/${key}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ value, updated_at: updatedAt }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as SyncedDoc;
}

interface ActualUploadResult {
  added: number;
  unmatched: string[];
  entries?: number;
  field_lineups?: number;
  players_with_ownership?: number;
  persisted?: boolean;
}

/** Master accounts: uploads a DraftKings contest-standings CSV as actual ownership for a slate and contest type. */
export async function postActualOwnership(
  token: string,
  body: { season: number; week: number; slate_id: string; contest: 'gpp' | 'se' | 'cash'; text: string },
): Promise<ActualUploadResult> {
  const res = await fetch(`${API_BASE_URL}/api/ownership/actual`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
  return (await res.json()) as ActualUploadResult;
}

async function authed<T>(token: string, path: string, method: 'GET' | 'POST' = 'GET'): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { method, headers: { Accept: 'application/json', Authorization: `Bearer ${token}` } });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

/** Master accounts: the NFL Intelligence Desk report (newest, or one version by id) and its version list. */
export function getBigPicture(token: string, id?: number | null) {
  return authed<BigPictureResponse>(token, `/api/big-picture${id ? `?id=${id}` : ''}`);
}

/** Master accounts: start a research run now (when on-demand runs are configured). */
export function runBigPicture(token: string) {
  return authed<{ started: boolean }>(token, '/api/big-picture/run', 'POST');
}
