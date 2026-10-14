# DFSRiches mobile

An Expo Router + NativeWind app for the DFSRiches API (the FastAPI app in the
repo root). It reads live data: this week's schedule, every DraftKings slate
(Sunday Main, Full Week, and a Showdown for each island game -- weeknight,
Sunday night, international and holiday games), projected optimal lineups, a
lineup builder, and Lines & Performance.

```bash
cd mobile
npm install
npx expo start            # scan the QR code with Expo Go, or press i / a / w
```

The app talks to `https://dfs-riches.onrender.com` by default. To use a local
API server instead (`python -m uvicorn app.main:app --host 0.0.0.0` from the
repo root), set its address before starting:

```bash
EXPO_PUBLIC_API_URL=http://<your-computer's-LAN-IP>:8000 npx expo start
```

## Over-the-air updates (EAS Update)

Installed builds update themselves: every push to `claude/dfsriches-explorer-t1pdh5`
that touches `mobile/` publishes the app's JavaScript to EAS Update's `production`
channel (`.github/workflows/eas-update.yml`), and the app downloads it when it
launches or comes back to the foreground. Expo Go and the website don't use it.

One-time setup:

1. Link the Expo project (writes `extra.eas.projectId` and `updates.url` to
   `app.json`; commit and push it):
   ```bash
   cd mobile && npx eas-cli login && npx eas-cli init && npx eas-cli update:configure
   ```
2. Add an Expo access token (expo.dev > Account settings > Access tokens) as the
   `EXPO_TOKEN` repository secret on GitHub.
3. Install a build that listens on `production`, once per phone:
   - Android: `npx eas-cli build -p android --profile preview` and install the APK.
   - iPhone (needs an Apple Developer account): `npx eas-cli build -p ios --profile preview`
     after registering the phone with `npx eas-cli device:create`, or
     `--profile production` and TestFlight.

Updates only reach builds with the same runtime fingerprint
(`runtimeVersion.policy: "fingerprint"`; `fingerprint.config.js` leaves the app
version out, since every push bumps it). Adding or upgrading a package with
native code changes the fingerprint and needs a new build.

## Layout

| Path | What's there |
| --- | --- |
| `app/_layout.tsx` | Root stack: safe-area provider, week data provider, `global.css` |
| `app/(tabs)/_layout.tsx` | Floating bottom tab bar (Home, DFS Model, Cash, GPP, Settings), mapped from `tabs` in `constants/data.ts`; positioned with `useSafeAreaInsets()` |
| `app/(tabs)/dfs-model.tsx` | Top 10 projections / values / ceilings by position, and game environments ranked best to worst (stacks, matchups, targets) |
| `app/(tabs)/cash.tsx`, `app/(tabs)/gpp.tsx` | Top QB/RB/WR/TE plays by strength of play, and every player's expected cash (or small/large-field GPP) ownership with Prioritize / Neutral / Fade tags (`components/plays/`, `/api/plays`) |
| `app/(tabs)/settings.tsx` | Account, data, links to the lineup builder and Lines & Performance, clearing saved data |
| `app/(tabs)/index.tsx` | Home: header with add-entry button, balance card (money spent on entries, next lineup lock), upcoming games (tap a card for its weekly breakdown), slate cards (tap to open projected optimal lineups and build/save lineups), profit/loss tracker, Lines & Performance |
| `app/(tabs)/lineups.tsx` | Slates, projected optimal lineups and the lineup builder (from Home/Settings; not in the tab bar) |
| `app/(tabs)/lines.tsx` | Lines & Performance for every game (from Home/Settings; not in the tab bar) |
| `components/` | The pieces those screens are built from |
| `constants/data.ts` | Tabs, Home user, Home sections, builder filters |
| `constants/icons.ts`, `constants/images.ts` | Centralized icon and image imports |
| `lib/utils.ts` | `formatCurrency` and other formatters |
| `lib/api.ts`, `lib/week-context.tsx` | API client and shared week/slate/lineup state (saved lineups persist on the device) |
| `lib/submissions.ts`, `lib/submissions-context.tsx` | Logged contest entries (saved on the device) and the profit/loss math |
| `lib/lineups.ts` | Lineup rules, ported from the website's `static/lineups.js` |
| `lib/lines.ts` | Lines & Performance formatting, ported from `static/app.js` |
| `lib/dfs-model-context.tsx`, `lib/game-detail.ts` | The DFS model (shared by DFS Model/Cash/GPP) and per-game breakdowns, each fetched once |
| `lib/games.ts` | Turns API games into the `UpcomingGame` cards (team logos from Sleeper's CDN) |
| `type.d.ts` | Global types for tabs, Home data and every API response |
| `global.css` | Tailwind layers plus the app's component classes (auth, home, games, players, lineups, forms, profit/loss) |

`assets/images/avatar.png` and `assets/images/splash-pattern.png` are
placeholders: replace them with the design's files (same names) and nothing
else needs to change.

Before committing: `npx tsc --noEmit && npx expo lint`.
