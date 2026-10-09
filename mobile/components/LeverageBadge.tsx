import { useEffect } from 'react';
import { type GestureResponderEvent, Pressable, Text } from 'react-native';

import { useLeverage } from '@/lib/leverage-context';
import { trendInk, trendLevel } from '@/lib/trend';
import { useColorScheme } from '@/lib/color-scheme';

// Shades by size in ownership points: under 1.5 steady (gold), then 1.5 / 4 / 8.
const STEPS: [number, number, number] = [1.5, 4, 8];

const formatLeverage = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}`;

/** Plain-English read of a leverage number and how it was built. */
export function leverageText(value: number, d: LeverageDetail | null | undefined): string {
  const parts = [`Leverage ${formatLeverage(value)} pts`];
  if (d?.fair_own != null && d.own != null) {
    parts.push(`fair ownership ${d.fair_own.toFixed(1)}% vs ${d.own.toFixed(1)}% ${d.own_is_actual ? 'actual' : 'projected'}`);
  }
  if (d) {
    const sig = (z: number) => `${z >= 0 ? '+' : '−'}${Math.abs(z).toFixed(1)}σ`;
    parts.push(
      `efficiency x${d.mem.toFixed(2)} (offense ${sig(d.off_z)}, opposing defense ${sig(d.def_z)}, vs his position ${sig(d.pos_z)})` +
        (d.teap != null ? ` → ${d.teap.toFixed(1)} adjusted proj` : ''),
    );
    if (d.verdict) parts.push(d.verdict);
  }
  return parts.join(' · ');
}

interface Props {
  /** Look the player up in the shared (large-field GPP) leverage... */
  player?: { id?: number | null; name?: string | null; team?: string | null };
  /** ...or show this contest's own value (Cash / GPP rows). */
  value?: number | null;
  detail?: LeverageDetail | null;
  /** Inside a <Text> line (previews): renders as nested text. */
  inline?: boolean;
  /** The player's name, for the explainer's title (when `player` isn't given). */
  name?: string | null;
}

/**
 * A small leverage number after a player's name: fair minus projected
 * ownership in points (app/leverage.py), the number itself colored green (positive), red
 * (negative) or gold (about even) -- darker = bigger. Renders nothing when
 * the player has no leverage (not on the DFS model's slate).
 */
export default function LeverageBadge({ player, value, detail, inline, name }: Props) {
  const dark = useColorScheme() === 'dark';
  const { lookup, request, explain } = useLeverage();
  const explicit = value !== undefined;
  useEffect(() => {
    if (!explicit) request();
  }, [explicit, request]);
  const info = explicit ? (value != null ? { value, detail: detail ?? null } : null) : player ? lookup(player) : null;
  if (!info) return null;
  const level = trendLevel(info.value, 0, 'high', { steps: STEPS, absolute: true });
  const color = trendInk(level, dark);
  const label = `${leverageText(info.value, info.detail)}. Tap for what this means.`;
  // Tapping explains the number (one shared explainer, lib/leverage-context).
  // The badge often sits inside a tappable row or card: the tap stays with the badge.
  const open = (e?: GestureResponderEvent) => {
    e?.stopPropagation?.();
    explain({ value: info.value, detail: info.detail, name: name ?? player?.name });
  };
  if (inline) {
    return (
      <Text onPress={open} accessibilityRole="button" accessibilityLabel={label} suppressHighlighting>
        {' '}
        <Text className="lev-badge-text" style={{ color }}>
          {formatLeverage(info.value)}
        </Text>
      </Text>
    );
  }
  return (
    <Pressable className="lev-badge" onPress={open} accessibilityRole="button" accessibilityLabel={label} hitSlop={8}>
      <Text className="lev-badge-text" style={{ color }}>
        {formatLeverage(info.value)}
      </Text>
    </Pressable>
  );
}
