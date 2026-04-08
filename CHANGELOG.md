# The Skipper — Changelog

---

## Session 6 — April 7, 2026

Relievers section, period dropdown fixes, cache version system.

### Key learnings this session
- `DayCell` in `ScheduleGrid` was gated behind `isStarting` — FPTS only rendered on days a pitcher had a `startDate` entry. Relievers never have `startDates`, so their points were silently swallowed. Fix: check for FPTS on non-start appearance days too and render them in the non-starting branch.
- ESPN stat ID 57 = saves, confirmed live. Captured in the `stats` dict within each `statSplitTypeId=5` entry alongside `appliedTotal`.
- `benchDays` requires per-day roster fetches to determine — the `lineupSlotId` for a player varies day to day as they're moved in and out of the lineup. We already fire one request per past day in `get_actual_fpts()`, so capturing slot ID there is essentially free.
- `CACHE_VERSION` constant pattern: write it to sessionStorage on save, check it on load, discard and re-fetch on mismatch. Eliminates the need to ever manually clear browser storage when the API response shape changes. Bump the number any time new fields are added to the cached object.
- `useRef(true)` pattern for distinguishing first render from subsequent renders in a `useEffect` — lets us auto-fetch on period change without double-fetching on initial load.
- `config.py` date format was inconsistent with `mlb.py` — human-readable strings ("Apr 6") vs ISO ("2026-04-06"). Converted config to ISO throughout; frontend formats for display with a small `fmt()` helper.
- ESPN credentials live entirely in Vercel env vars server-side — never in sessionStorage. Cache invalidation does not affect auth.

### Relievers section
- `api/espn.py`: `get_actual_fpts()` extended to also return `actualSaves` (stat ID 57) and `benchDays` (lineupSlotId==16 per day) — both structured as `{ player_name: { date: value } }` and `{ player_name: [dates] }` respectively
- `api/espn.py`: `get_league_data()` unpacks the new tuple return, adds `actualSaves` and `benchDays` to API response
- `components/ScheduleGrid.tsx`: new props `actualSaves`, `benchDays`, `savesData` — when `savesData` provided, Starts column replaced with Saves column
- `components/ScheduleGrid.tsx`: `DayCell` now renders FPTS and 🔒 emoji on non-start appearance days (reliever appearances)
- `components/ScheduleGrid.tsx`: bench-day FPTS shown in gray strikethrough via `benchDays` lookup
- `pages/my-team.tsx`: roster split into `rosterStarterSPs` (slot=SP) and `rosterRelievers` (slot=RP)
- `pages/my-team.tsx`: relievers rendered in their own card with `ScheduleGrid` + `savesData` prop + team saves badge

### Period dropdown fixes
- `api/config.py`: added `get_current_period()` — walks MATCHUP_PERIODS table, returns period containing today's date
- `api/config.py`: `currentPeriod` added to config API response
- `api/config.py`: MATCHUP_PERIODS dates converted from human-readable to full ISO format
- `pages/my-team.tsx` + `pages/free-agents.tsx`: `selectedPeriod` initial state changed from `1` to `null`
- Both pages: config `useEffect` now sets period from sessionStorage if present, otherwise uses `currentPeriod` from config
- Both pages: `useRef(true)` pattern added — period `useEffect` skips fetch on first render if cache is valid, fires fetch on all subsequent period changes

### Cache version system
- `pages/my-team.tsx` + `pages/free-agents.tsx`: `CACHE_VERSION = 2` constant added
- Version written into sessionStorage cache object on every save
- Version checked on cache load — mismatch causes early return, triggering auto-fetch via period effect

---

## Session 5 — March 29/30, 2026

Actual FPTS in schedule grid cells, bench/IL distinction fix, and free agents cache fix.

### Key learnings this session
- ESPN per-game stats use `statSplitTypeId=5`, one entry per game keyed by `scoringPeriodId`. Must fetch each day individually — no single call returns full history. Parallel fetching via `ThreadPoolExecutor` (max_workers=6) makes this fast enough to be practical for a 12-day matchup period.
- Scoring period math: 2026 season start = March 25 = period 1. Formula: `(date - 2026-03-25).days + 1`. Reverse: `2026-03-25 + (period - 1) days`.
- ESPN's `injuryStatus` field is **empty string** for all players in this league — cannot be used to distinguish bench from IL. Must use `lineupSlotId` instead.
- In this league: slot 16 = bench (healthy player parked there), slot 17 = true IL. Confirmed by cross-referencing known IL players (Pepiot, Kelly) with known bench players (Diaz, Bednar).
- Past performance data (`actualFpts`) is the ground truth regardless of current slot — preserve past `startDates` history even for players currently on IL/bench.
- sessionStorage cache validation pattern: always check for presence of key fields (like `matchupDates`) before using cached data. Auto-fetch when fields are absent.
- `savedPeriod` must be loaded from sessionStorage **before** the cache check, not after — otherwise a stale cache auto-fetch uses the wrong period (defaulting to 1).

### Free agents cache fix
- `pages/free-agents.tsx`: stale cache auto-refresh when `matchupDates` missing — mirrors My Team behavior
- `pages/free-agents.tsx`: `savedPeriod` loading moved above cache check

### Actual FPTS in schedule grid
- `api/espn.py`: new `get_actual_fpts()` — parallel ESPN API calls (one per past day) via `ThreadPoolExecutor`
- `api/espn.py`: new `date_to_scoring_period()` helper
- `api/espn.py`: `actualFpts` added to API response (`{ player_name: { date: fpts } }`)
- `components/ScheduleGrid.tsx`: past/live start cells show actual points in green (positive) or red (negative) below the ✓ checkmark
- `pages/my-team.tsx` + `pages/free-agents.tsx`: `actualFpts` state, cache persistence, and prop passing added

### Bench vs IL distinction fix
- `api/espn.py`: `get_slot_label()` and `get_status()` updated — slot 17 = IL, slot 16 = bench
- Edwin Diaz and David Bednar now correctly show as RP / Bench
- Ryan Pepiot and Merrill Kelly correctly show as IL
- IL/Bench players preserve past `startDates` while future projections zeroed out
- `slot_order` updated to include `"Bench": 3` so bench players sort after IL

---

## Session 4 — March 28, 2026 (evening)

Schedule grid, roster fixes, and backend refactor. One PR shipped.

### Key learnings this session
- ESPN's `scoringPeriodId` is a daily counter — not the matchup period number. Passing the matchup period number was returning stale rosters. Removing it entirely lets ESPN default to today's live roster.
- ESPN Scoreboard API uses `CHW` for White Sox; our PRO_TEAM_MAP uses `CWS`. Normalization map added to `mlb.py`.
- Last-name-only pitcher matching is fragile for common surnames — full name or player ID matching needed.
- sessionStorage cache shape needs a version check — auto-fetch when key fields are missing.

### PR #21 — Schedule grid
- `components/ScheduleGrid.tsx` — new shared component
- Day columns dynamic based on matchup period length
- ✅ confirmed, P projected, ✓ past confirmed, gray label for non-start game days, — for no game
- Today's column highlighted with green underline and "TODAY" label
- IL players at 50% opacity
- `mlb.py` expanded to return full game schedule alongside probables
- `espn.py` refactored to import from `mlb.py` — eliminates duplicate MLB Stats API call
- Abbreviation normalization map added (CHW→CWS etc.)
- Fix: removed `scoringPeriodId` from roster fetch
- Fix: IL classification uses lineup slot only

---

## Session 3 — March 28, 2026

Probable pitcher data integration, matchup period dropdown, roster data fixes, ESPN team map rebuild. Two PRs shipped.

### Key learnings this session
- ESPN Scoreboard API is public, no auth, returns probable starters up to 7 days out — better than FantasyPros/FanGraphs which are JS-rendered
- MLB Stats API only confirms probables 1-2 days out but is the authoritative confirmed source
- ESPN's `proTeamId` mapping completely changed in 2026 — old map was ~2019 era
- ESPN's fantasy API caches roster data server-side — cache-busting query params don't help
- FantasyPros and FanGraphs probables: JS-rendered, dead ends for server-side scraping

### PR #18 — ESPN Scoreboard API probable pitcher integration
- `api/mlb.py` — new endpoint at `/api/mlb?period=N`
- MLB Stats API: confirmed probables (`confirmed: true`)
- ESPN Scoreboard API: projected starters (`confirmed: false`)
- Fallback is 0 starts (was hardcoded 2)
- Fixed `jr.`/`sr.`/`ii`/`iii` suffix bug in name parsing

### PR #20 — Matchup period dropdown + roster fixes
- Matchup period dropdown synced via sessionStorage across pages
- `api/config.py` returns full 22-period matchup table
- Removed `starts = 2` and `Math.random()` fallbacks
- Removed Status column from My Team
- Complete ESPN PRO_TEAM_MAP rebuild — all 32 IDs verified
- Main branch protection enabled on GitHub

---

## Session 2 — March 28, 2026 (earlier)

Probable pitcher integration via dual-source API merge. One PR shipped.

### PR #18 — ESPN Scoreboard API probable pitcher integration
- `api/mlb.py` — dual-source probable pitcher system
- MLB Stats API + ESPN Scoreboard API merged with confidence tier system
- Each start carries `confirmed` boolean for frontend indicators
- Brought forward 3 unmerged commits from `feature/mlb-stats-api` via cherry-pick

---

## Session 1 — March 27, 2026

Full architecture rebuild. Four PRs shipped and deployed to production.

### Key learnings this session
- `matchupPeriodDates` not returned for this league → all 22 period dates must be hardcoded
- MLB Stats API only confirms probables 1-2 days out → secondary source needed for days 3-10
- `vercel dev` with CLI v50+ does not serve Python serverless functions locally → test against production

### PR #14 — NextAuth credentials login
- Replaced hand-rolled cookie auth with NextAuth.js
- Added `APP_USERNAME`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL` env vars

### PR #15 — Sidebar layout + multi-page routing
- Persistent sidebar + four real Next.js pages
- Data persists across pages via `sessionStorage`

### PR #16 — ESPN API bug fixes
- Team name, free agent fetching, injury status labels all fixed

### PR #17 — MLB Stats API probable pitcher integration
- `api/mlb.py` — new endpoint with real probable pitcher data
- All 22 matchup period dates hardcoded with exact dates and starts limits

---

## Pre-session baseline (before March 27, 2026)

Initial working prototype. Single-page step wizard.

- ESPN API connection via `espn_s2` + `SWID` cookies
- Roster pulls with real player names, team abbreviations, slot labels
- Hand-rolled cookie-based password protection
- Claude AI analysis via Anthropic API
- Vercel deployment stable at `https://the-skipper-iota.vercel.app`
- Branch/PR workflow established