import { uploadAsync, FileSystemUploadType } from 'expo-file-system/legacy';
import { Platform } from 'react-native';

import { API_BASE_URL } from '@/constants/config';

/** The session token; `fresh` skips Clerk's cached copy (after the server turned one down). */
type TokenSource = (fresh?: boolean) => Promise<string | null>;
let resolveSource: ((fn: TokenSource) => void) | null = null;
let source: Promise<TokenSource> = new Promise((resolve) => (resolveSource = resolve));

/**
 * The signed-in user's Clerk session token, for every API request (the server
 * answers only signed-in accounts). lib/account-sync.tsx sets it once someone
 * is signed in and clears it on sign-out; requests made before then wait.
 */
export function setTokenSource(fn: TokenSource | null) {
  if (fn && resolveSource) {
    resolveSource(fn);
    resolveSource = null;
  } else if (fn) {
    source = Promise.resolve(fn);
  } else if (!resolveSource) {
    source = new Promise((resolve) => (resolveSource = resolve));
  }
}

let onRejected: (() => void) | null = null;

/** Called when the server still turns the session down after a fresh token (components/SessionGuard.tsx). */
export function setSessionRejectedHandler(fn: (() => void) | null) {
  onRejected = fn;
}

async function getJson<T>(path: string): Promise<T> {
  const call = async (fresh: boolean) => {
    const token = await (await source)(fresh);
    return fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  };
  // A turned-down session gets one quiet retry with a fresh token before the user hears about it.
  let res = await call(false);
  if (res.status === 401) {
    res = await call(true);
    if (res.status === 401) onRejected?.();
  }
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

/** POST JSON with the session token (same retry and rejection handling as getJson). */
async function postJson<T>(path: string, body: unknown): Promise<T> {
  const call = async (fresh: boolean) => {
    const token = await (await source)(fresh);
    return fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
  };
  let res = await call(false);
  if (res.status === 401) {
    res = await call(true);
    if (res.status === 401) onRejected?.();
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // not JSON
    }
    throw Object.assign(new Error(detail), { status: res.status });
  }
  return (await res.json()) as T;
}

export interface BuiltLineup {
  players: { slot: string; dk_draftable_id: number; name: string; team: string }[];
  salary: number;
  proj_points: number;
  ceiling: number;
}

/** "Build for me": up to 5 distinct lineups from the model (more than one is Pro). */
export function buildLineups(
  season: number,
  week: number,
  slateId: string,
  opts: { metric: 'proj_points' | 'ceiling'; count: number; locked: number[]; excluded: number[]; max_exposure: number },
) {
  return postJson<{ lineups: BuiltLineup[]; requested: number }>(`/api/slates/${encodeURIComponent(slateId)}/build`, { season, week, ...opts });
}

export interface TrackRecordSlate {
  season: number;
  week: number;
  slate_id: string;
  lineups: { label: string; metric: string; proj_points: number; ceiling: number; actual: number; note?: string | null }[];
  best_possible: number | null;
}

/** How the saved optimal lineups scored against their projections, newest first. */
export function getTrackRecord() {
  return getJson<{ slates: TrackRecordSlate[] }>('/api/track-record');
}

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
  /** The selected slate's DraftKings draft group id: its contests are listed first. */
  slate?: number | null;
}) {
  const lists = { ...sel, weights: sel.weights ? Object.entries(sel.weights).map(([k, v]) => `${k}:${v}`) : [] };
  const query = [
    ...(['entries', 'fees', 'exclude', 'weights'] as const)
      .filter((k) => lists[k].length)
      .map((k) => `${k}=${encodeURIComponent(lists[k].join(','))}`),
    ...(sel.slate ? [`slate=${sel.slate}`] : []),
  ].join('&');
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

/** Deletes the account and everything stored for it (Settings > Delete account). */
export async function deleteAccount(token: string): Promise<{ deleted_data: boolean; deleted_account: boolean }> {
  const res = await fetch(`${API_BASE_URL}/api/me`, { method: 'DELETE', headers: { Accept: 'application/json', Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as { deleted_data: boolean; deleted_account: boolean };
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

export interface VideoUploadResult extends ActualUploadResult {
  /** Frames read from the recording. */
  frames: number;
  /** What was read for each matched player, highest ownership first. */
  players: {
    name: string;
    team: string;
    position: string;
    pct: number;
    salary: number | null;
    points: number | null;
    /** The salary read doesn't match this slate's DraftKings salary (a contest from a different slate?). */
    salary_mismatch: boolean;
  }[];
}

/** Where an upload was applied when its slate was detected from the data (slate_id "auto"). */
interface AppliedSlate {
  season: number;
  week: number;
  slate_id: string;
  label: string;
  slate_type: string;
}

interface ActualUploadResult {
  added: number;
  unmatched: string[];
  entries?: number;
  field_lineups?: number;
  players_with_ownership?: number;
  persisted?: boolean;
  slate?: AppliedSlate | null;
}

/**
 * Master accounts: uploads a screen recording (or screenshot) of a DraftKings contest's GameCenter Players tab; the
 * server reads each player's ownership, salary and fantasy points from it. Native streams the file from disk.
 */
export async function postOwnershipVideo(
  token: string,
  args: { season: number; week: number; slate_id: string; contest: 'gpp' | 'se' | 'cash' },
  uri: string,
  mimeType: string,
): Promise<VideoUploadResult> {
  const url = `${API_BASE_URL}/api/ownership/actual/video?season=${args.season}&week=${args.week}&slate_id=${encodeURIComponent(args.slate_id)}&contest=${args.contest}`;
  const headers = { 'Content-Type': mimeType || 'application/octet-stream', Accept: 'application/json', Authorization: `Bearer ${token}` };
  let status: number;
  let text: string;
  if (Platform.OS === 'web') {
    const res = await fetch(url, { method: 'POST', headers, body: await (await fetch(uri)).blob() });
    status = res.status;
    text = await res.text();
  } else {
    const res = await uploadAsync(url, uri, { httpMethod: 'POST', uploadType: FileSystemUploadType.BINARY_CONTENT, headers });
    status = res.status;
    text = res.body;
  }
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    // not JSON
  }
  if (status < 200 || status >= 300) throw new Error((body as { detail?: string } | null)?.detail ?? `${status}`);
  return body as VideoUploadResult;
}

/** Master accounts: uploads a DraftKings contest-standings CSV as actual ownership for a slate and contest type. */
export async function postActualOwnership(
  token: string,
  /** slate_id "auto": the server applies it to the slate the standings' players and points match. */
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

export type NewsStatus = 'OUT' | 'D' | 'Q' | 'PLAYING';

export interface NewsOverride {
  id: string;
  season: number;
  week: number;
  team: string;
  name: string;
  status: NewsStatus;
  note: string | null;
  /** False for a player not on a DraftKings slate (a lineman or defender): counts toward starters out only. */
  on_slate: boolean;
  created_at: string;
  persisted?: boolean;
}

/** Breaking news entered by hand for a week (app.news_overrides), newest first. */
export async function getNewsOverrides(season: number, week: number): Promise<NewsOverride[]> {
  const res = await fetch(`${API_BASE_URL}/api/news-overrides?season=${season}&week=${week}`, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return ((await res.json()) as { entries: NewsOverride[] }).entries;
}

async function newsRequest<T>(token: string, path: string, method: 'POST' | 'DELETE', body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: `Bearer ${token}` },
    body: body ? JSON.stringify(body) : undefined,
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
  return (await res.json()) as T;
}

/** Master accounts: enter breaking news (a player ruled Out, Doubtful, Questionable, or confirmed Playing). */
export function postNewsOverride(
  token: string,
  body: { season: number; week: number; name: string; team?: string; status: NewsStatus; note?: string },
) {
  return newsRequest<NewsOverride>(token, '/api/news-overrides', 'POST', body);
}

/** Master accounts: remove an entry; the official feeds take over again. */
export function deleteNewsOverride(token: string, season: number, week: number, id: string) {
  return newsRequest<{ removed: boolean }>(token, `/api/news-overrides/${id}?season=${season}&week=${week}`, 'DELETE');
}
