import { useAuth } from '@clerk/expo';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BrandHeader from '@/components/BrandHeader';
import Markdown from '@/components/bigpicture/Markdown';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { useAccountSync } from '@/lib/account-sync';
import { getBigPicture, runBigPicture } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';

const CACHE = createFetchCache<BigPictureResponse>();

const CLASS_STYLE: Record<BigPictureRow['class'], string> = {
  strongest: 'bp-class-strong',
  price_sensitive: 'bp-class-small',
  watchlist: 'bp-class-watch',
  none: 'bp-class-none',
};
const AGENT_NAMES: Record<string, string> = {
  A: 'A · Market & line movement',
  B: 'B · Quantitative projections',
  C: 'C · Injuries & personnel',
  D: 'D · Game environments',
  E: 'E · Betting value',
  F: 'F · DFS ownership & leverage',
  G: 'G · Public narrative',
  H: 'H · Weather & scheduling',
};

function Dashboard({ rows }: { rows: BigPictureRow[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.filter((r) => r.class !== 'none').slice(0, 12);
  if (!rows.length) return <Text className="bp-md-p">No DraftKings or consensus lines are posted yet.</Text>;
  return (
    <View className="mt-2">
      {shown.map((r, i) => (
        <View key={`${r.game}-${r.market}-${i}`} className="bp-row">
          <View className="flex-row items-center justify-between">
            <Text className="bp-row-title flex-shrink">
              {r.game} · {r.side}
            </Text>
            <Text className={`bp-class ${CLASS_STYLE[r.class]}`}>{r.status}</Text>
          </View>
          <Text className="bp-row-meta">
            {r.market} · opened {r.opening} · now {r.current} · fair {r.fair} · {r.edge}
            {r.moved ? ` · moved ${r.moved}` : ''}
          </Text>
        </View>
      ))}
      {rows.length > shown.length || all ? (
        <Pressable onPress={() => setAll((a) => !a)} accessibilityRole="button" aria-expanded={all}>
          <Text className="upcoming-expand-hint">{all ? 'Show rated sides only ▲' : `Show all ${rows.length} markets ▼`}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function ChangeLog({ rows }: { rows: BigPictureChange[] }) {
  if (!rows.length) return null;
  return (
    <View className="mt-2">
      {rows.slice(0, 40).map((r, i) => (
        <View key={i} className="bp-row">
          <Text className="bp-row-title">{r.item}</Text>
          <Text className="bp-row-meta">
            {r.previous} → {r.current} · {r.reason} · {r.action}
          </Text>
        </View>
      ))}
    </View>
  );
}

function Section({ s, report, open, onToggle }: { s: BigPictureSection; report: BigPictureReport; open: boolean; onToggle: () => void }) {
  return (
    <View className="bp-section">
      <Pressable onPress={onToggle} accessibilityRole="button" aria-expanded={open} className="flex-row items-center">
        <Text className="bp-section-n">{s.n}</Text>
        <Text className="bp-section-title flex-1">{s.title}</Text>
        <Text className="bp-chevron">{open ? '▲' : '▼'}</Text>
      </Pressable>
      {open ? (
        <View className="mt-2">
          <Markdown text={s.markdown} />
          {s.n === 2 ? <Dashboard rows={report.tables.dashboard} /> : null}
          {s.n === 11 ? <ChangeLog rows={report.tables.changelog} /> : null}
          {s.unverified?.length ? (
            <Text className="bp-warn">Fact check: {s.unverified.join(', ')} not found in the desk&apos;s data -- treat as unverified.</Text>
          ) : null}
          <Text className="bp-author">
            {s.author === 'agents' ? 'Written by the research agents' : s.author === 'desk' ? 'Written by the desk, straight from the data' : `Written by the ${s.author}`}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function rec(r?: BigPictureRecord | null) {
  return r && r.n ? `${r.w}-${r.l}${r.p ? `-${r.p}` : ''}${r.win_pct != null ? ` (${Math.round(r.win_pct * 100)}%)` : ''}` : 'no picks';
}

function TrackRecord({ data }: { data: NonNullable<BigPictureResponse['report']>['dossier'] }) {
  const bt = data?.track_record?.backtest as Record<string, number | BigPictureRecord | string> | undefined;
  const graded = data?.track_record?.graded;
  const trusted = data?.calibration?.trusted;
  if (!bt && !graded) return null;
  return (
    <View className="bp-section">
      <Text className="bp-section-title">Model track record</Text>
      {bt && (bt.games as number) > 0 ? (
        <>
          <Text className="bp-md-p">
            Backtest, {String(bt.games)} games: spread miss {String(bt.spread_mae_model)} pts (closing line {String(bt.spread_mae_market)});
            total miss {String(bt.total_mae_model)} (closing {String(bt.total_mae_market)}
            ).
          </Text>
          <Text className="bp-md-p">
            Where the model disagreed with the close by 1.5+: ATS {rec(bt['ats_gap_1.5'] as BigPictureRecord)}; totals by 2+:{' '}
            {rec(bt['totals_gap_2'] as BigPictureRecord)}.
          </Text>
          <Text className="bp-row-meta">
            Spread signals {trusted?.spread ? 'can' : "can't"} rate an edge; total signals {trusted?.total ? 'can' : "can't"} (watchlist
            only). {String(bt.note ?? '')}
          </Text>
        </>
      ) : null}
      {graded ? (
        <Text className="bp-md-p">
          Graded desk calls: {rec(graded.record)}
          {graded.avg_clv_points != null ? ` · average closing-line value ${graded.avg_clv_points} pts` : ''}
          {graded.note ? ` · ${graded.note}` : ''}
        </Text>
      ) : null}
    </View>
  );
}

/** One stored report: header, version picker, the 12 sections, track record, quality control, analyst notes. */
export function ReportView({ data, onSelectVersion }: { data: BigPictureResponse; onSelectVersion: (id: number) => void }) {
  const [open, setOpen] = useState<Record<number, boolean>>({ 1: true });
  const [showMeta, setShowMeta] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const rep = data.report;
  const r = rep?.report;
  if (!rep || !r) return null;
  return (
    <>
      <View className="bp-head">
        <Text className="bp-title">{r.title}</Text>
        <View className="mt-1 flex-row flex-wrap items-center gap-2">
          <Text className={`bp-badge ${r.header.status === 'Updated' ? 'bp-badge-ok' : 'bp-badge-prelim'}`}>{r.header.status}</Text>
          <Text className="bp-row-meta">
            {r.header.generated_et} · Week {r.header.week} · {r.header.games.length} games ·{' '}
            {r.writer === 'agents' ? `research agents${r.model ? ` (${r.model})` : ''}` : 'desk templates (no language model)'}
          </Text>
        </View>
        <Pressable onPress={() => setShowMeta((m) => !m)} accessibilityRole="button" aria-expanded={showMeta}>
          <Text className="upcoming-expand-hint">{showMeta ? 'Hide sources & data gaps ▲' : 'Sources, freshness & data gaps ▼'}</Text>
        </Pressable>
        {showMeta ? (
          <View className="mt-1">
            {r.header.freshness.map((f) => (
              <Text key={f.source} className="bp-row-meta">
                {f.source}
                {f.status ? ` · ${f.status}` : ''}
                {f.captured_at ? ` · ${f.captured_at.replace('T', ' ').slice(0, 16)} UTC` : ''}
              </Text>
            ))}
            {r.header.gaps.map((g) => (
              <Text key={g} className="bp-gap">
                • {g}
              </Text>
            ))}
            <Text className="bp-row-meta">
              Markets: {r.header.markets.join(', ')}. Games: {r.header.games.join(', ')}.
            </Text>
          </View>
        ) : null}
      </View>

      {data.versions.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
          {data.versions.slice(0, 15).map((v) => {
            const active = v.id === rep.id;
            return (
              <Pressable
                key={v.id}
                className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                onPress={() => onSelectVersion(v.id)}
                accessibilityRole="button"
                aria-pressed={active}>
                <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                  W{v.week} · {v.summary.generated_et.replace(/^\w+ /, '').replace(/, \d{4}/, '')}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}

      {r.sections.map((s) => (
        <Section key={s.n} s={s} report={r} open={!!open[s.n]} onToggle={() => setOpen((o) => ({ ...o, [s.n]: !o[s.n] }))} />
      ))}

      <TrackRecord data={rep.dossier} />

      <View className="bp-section">
        <Text className="bp-section-title">Quality control</Text>
        <Text className="bp-md-p">
          {r.qc.review
            ? `Reviewer (Agent J): ${r.qc.review.verdict}${r.qc.review.revised ? ', flagged sections revised' : ''}.`
            : 'No agent review (desk templates are built straight from the data).'}{' '}
          Every figure is also checked mechanically against the desk&apos;s data.
        </Text>
        {(r.qc.review?.issues ?? []).slice(0, 8).map((i, k) => (
          <Text key={k} className="bp-gap">
            • §{i.section}: {i.problem}
          </Text>
        ))}
      </View>

      {Object.keys(r.agent_notes || {}).length ? (
        <View className="bp-section">
          <Pressable
            onPress={() => setShowNotes((n) => !n)}
            accessibilityRole="button"
            aria-expanded={showNotes}
            className="flex-row items-center">
            <Text className="bp-section-title flex-1">Analyst notes (agents A–H)</Text>
            <Text className="bp-chevron">{showNotes ? '▲' : '▼'}</Text>
          </Pressable>
          {showNotes
            ? Object.entries(r.agent_notes).map(([k, v]) => (
                <View key={k} className="mt-2">
                  <Text className="bp-md-h">{AGENT_NAMES[k] ?? k}</Text>
                  <Markdown text={v} />
                </View>
              ))
            : null}
        </View>
      ) : null}
      <Text className="bp-row-meta mt-2">
        Analysis, not betting advice: classifications are model estimates and can lose. Built in {r.elapsed_s}s.
      </Text>
    </>
  );
}

/**
 * Big Picture: the NFL Intelligence Desk's report (master accounts only while it's piloted).
 * Written by research agents on GitHub Actions; this screen only reads stored versions.
 */
export default function BigPictureScreen() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { isSignedIn, getToken } = useAuth();
  const { master } = useAccountSync();
  const [versionId, setVersionId] = useState<number | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const { data, error, loading, refreshing, refresh } = useCachedFetch(
    CACHE,
    isSignedIn && master ? `bp:${versionId ?? 'latest'}` : '',
    async () => {
      const token = await getToken();
      if (!token) throw new Error('Sign in again to load the Big Picture.');
      return getBigPicture(token, versionId);
    },
  );

  const run = async () => {
    setRunMsg('Starting a research run…');
    try {
      const token = await getToken();
      await runBigPicture(token!);
      setRunMsg('Research run started -- the new version appears here in about 5-10 minutes.');
    } catch (e) {
      setRunMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const shell = (body: React.ReactNode) => (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{
          paddingBottom: insets.bottom + FLOATING_TAB_BAR.space,
        }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}>
        <BrandHeader title="Big Picture" />
        {body}
      </ScrollView>
    </SafeAreaView>
  );

  if (!isSignedIn || !master) {
    return shell(
      <View className="bp-section">
        <Text className="bp-section-title">Private pilot</Text>
        <Text className="bp-md-p">The NFL Intelligence Desk is being piloted with the master account before it launches.</Text>
        {!isSignedIn ? (
          <Pressable className="btn-outline mt-2" onPress={() => router.push('/sign-in')} accessibilityRole="button">
            <Text className="btn-outline-text">Sign in</Text>
          </Pressable>
        ) : null}
      </View>,
    );
  }

  const rep = data?.report;
  const runState = data?.run?.status && data.run.status !== 'completed' ? `A research run is ${data.run.status.replace('_', ' ')}.` : null;

  return shell(
    <>
      <Text className="screen-subtitle">NFL Intelligence Desk · betting markets, injuries and DFS · master-only pilot</Text>
      <StatusView loading={loading} error={error} />
      {data && !rep ? <Text className="home-empty-state">No report yet. The first research run stores one here.</Text> : null}
      {data?.can_run ? (
        <Pressable className="btn-outline mb-3" onPress={run} accessibilityRole="button" disabled={!!runState}>
          <Text className="btn-outline-text">{runState ?? 'Run the research desk now'}</Text>
        </Pressable>
      ) : null}
      {runMsg ? <Text className="bp-row-meta mb-3">{runMsg}</Text> : null}
      {data ? (
        <Pressable onPress={refresh} accessibilityRole="button" className="mb-2 self-start">
          <Text className="link-text text-sm">{refreshing ? 'Reloading…' : 'Reload the latest version'}</Text>
        </Pressable>
      ) : null}
      {rep ? <ReportView data={data!} onSelectVersion={setVersionId} /> : null}
    </>,
  );
}
