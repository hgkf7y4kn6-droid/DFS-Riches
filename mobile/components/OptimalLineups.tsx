import { useState } from "react";
import { Image, Pressable, Text, View } from "react-native";

import { LineupRow, Totals } from "@/components/LineupRows";
import StatusView from "@/components/StatusView";
import { OPTIMAL_STATUS_TEXT } from "@/constants/data";
import icons from "@/constants/icons";
import { useThemeColors } from "@/constants/theme";
import { fromOptimal } from "@/lib/lineups";
import { formatCurrency, formatEt, formatPoints } from "@/lib/utils";
import { type LineupScope, useLineups, useWeek } from "@/lib/week-context";

function statusLine(opt: OptimalResponse): string {
  if (opt.status === "live") {
    const locks = opt.locked_players
      ? ` · ${opt.locked_players} player${opt.locked_players === 1 ? "" : "s"} locked (${opt.games_started} game${opt.games_started === 1 ? "" : "s"} underway)`
      : "";
    return `${OPTIMAL_STATUS_TEXT.live} (last change ${formatEt(opt.saved_at)})${locks}`;
  }
  if (opt.status === "saved")
    return `${OPTIMAL_STATUS_TEXT.saved} (saved ${formatEt(opt.saved_at)})`;
  if (opt.status === "final")
    return `${OPTIMAL_STATUS_TEXT.final} (${formatEt(opt.results_at)})`;
  return OPTIMAL_STATUS_TEXT.none;
}

function summary(lineup: OptimalLineup): string {
  const parts = [formatCurrency(lineup.salary)];
  if (lineup.metric !== "actual")
    parts.push(
      `${formatPoints(lineup.proj_points)} proj`,
      `${formatPoints(lineup.ceiling)} ceil`,
    );
  if (lineup.actual != null)
    parts.push(`${formatPoints(lineup.actual)} actual`);
  return parts.join(" · ");
}

function OptimalCard({
  lineup,
  onEdit,
  collapsible,
}: {
  lineup: OptimalLineup;
  onEdit?: () => void;
  collapsible?: boolean;
}) {
  const hindsight = lineup.metric === "actual";
  const colors = useThemeColors();
  // Collapsible (Home): starts minimized to its totals; tap the header to show the players.
  const [open, setOpen] = useState(!collapsible);
  const title = <Text className="lineup-title">{lineup.label}</Text>;
  return (
    <View className="lineup-card">
      <View className="lineup-card-header">
        {collapsible ? (
          <Pressable
            className="flex-1 flex-row items-center"
            onPress={() => setOpen((o) => !o)}
            accessibilityRole="button"
            aria-expanded={open}
            accessibilityLabel={`${lineup.label}, ${open ? "hide players" : "show players"}`}
          >
            <View className="flex-1">
              {title}
              {!open ? (
                <Text className="lineup-status mb-0 mt-0.5">
                  {summary(lineup)}
                </Text>
              ) : null}
            </View>
            <Image
              source={icons.chevron}
              resizeMode="contain"
              style={{
                width: 16,
                height: 16,
                marginLeft: 8,
                tintColor: colors.foreground,
                transform: [{ rotate: open ? "180deg" : "0deg" }],
              }}
            />
          </Pressable>
        ) : (
          title
        )}
        {onEdit && open ? (
          <Pressable
            onPress={onEdit}
            accessibilityRole="button"
            accessibilityLabel={`Edit ${lineup.label} in the builder`}
            className="ml-3"
          >
            <Text className="link-text">Edit in builder</Text>
          </Pressable>
        ) : null}
      </View>
      {!open
        ? null
        : lineup.players.map((p, i) => (
            <LineupRow
              key={`${p.slot}-${i}`}
              slot={p.slot}
              player={p}
              note={
                p.locked && lineup.metric !== "actual" && p.actual == null
                  ? "Locked: game underway (pre-kickoff numbers)"
                  : null
              }
            />
          ))}
      {open ? (
        <Totals
          items={[
            { label: "Salary", value: formatCurrency(lineup.salary) },
            ...(hindsight
              ? []
              : [
                  { label: "Proj", value: formatPoints(lineup.proj_points) },
                  { label: "Ceiling", value: formatPoints(lineup.ceiling) },
                ]),
            ...(lineup.actual != null
              ? [{ label: "Actual", value: formatPoints(lineup.actual) }]
              : []),
          ]}
        />
      ) : null}
    </View>
  );
}

/** The projected optimal lineups for the selected slate (and, once final, the best possible);
 *  "Edit in builder" copies one into the `scope` builder's active lineup. */
export default function OptimalLineups({
  scope = "",
  collapsible = false,
}: {
  scope?: LineupScope;
  collapsible?: boolean;
}) {
  const { selectedSlate, optimal, players } = useWeek();
  const { activeLineup, setLineup } = useLineups(scope);
  if (!selectedSlate) return null;
  const opt = optimal.data;
  const pool = players.data?.players ?? [];
  const editable =
    selectedSlate.available && pool.length > 0 && opt?.status === "live";

  return (
    <View>
      <StatusView
        loading={optimal.loading}
        error={optimal.error}
        empty={
          opt && opt.lineups.length === 0
            ? selectedSlate.available
              ? "No optimal lineups yet"
              : "DraftKings has not posted salaries for this slate yet"
            : null
        }
      />
      {opt && opt.lineups.length > 0 ? (
        <>
          <Text className="lineup-status">{statusLine(opt)}</Text>
          {opt.lineups.map((lu) => (
            <OptimalCard
              key={lu.label}
              lineup={lu}
              onEdit={
                editable
                  ? () =>
                      setLineup(
                        activeLineup,
                        fromOptimal(lu, selectedSlate.slate_type, pool),
                      )
                  : undefined
              }
              collapsible={collapsible}
            />
          ))}
          {opt.hindsight ? (
            <OptimalCard lineup={opt.hindsight} collapsible={collapsible} />
          ) : null}
        </>
      ) : null}
    </View>
  );
}
