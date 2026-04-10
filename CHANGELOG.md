# The Skipper — Changelog

---

## Session 11 — April 10, 2026

Upstash KV locked projections, full-name pitcher matching, bench player start fix, and multiple bug fixes. Seven PRs shipped (#41–#47).

### Key learnings this session
- Vercel removed native KV — Upstash for Redis is the direct replacement, same `upstash-redis` Python library, same REST API pattern.
- Upstash Eviction must be OFF for projection storage — eviction silently deletes keys when storage fills up, which would destroy our audit log.
- Redis NX flag (`set key value nx=True`) is the correct pattern for write-once locks — it's atomic and never overwrites an existing value.
- Key schema design matters: `proj:{season}:{period}:{slug}:{date}` makes prefix queries trivial and keys human-readable.
- ESPN `lineupSlotId` reflects the scoring period snapshot, not the player's live lineup position — it can be stale after the transaction lag re-fetch.
- Last-name-only pitcher matching was fragile in two distinct ways: (1) common surnames collide (Smith), (2) unusual surnames fail silently if there's any name variation across sources. Full-name matching eliminates both.
- The ESPN API cannot be called directly from local machine — requires `espn_s2` and `SWID` cookies only available server-side. Always test ESPN-dependent changes against production URL after deploy.
- `git reset --hard origin/main` is the correct fix when local main diverges from origin after a squash merge — do not `git merge origin/main` as it creates a stray merge commit that branch protection will reject.
- When debugging a data pipeline issue, add a targeted debug field to the API response and read it from DevTools Network tab — much faster than guessing at intermediate state.

### Upstash KV infrastructure (PR #41, #42)
- `requirements.txt`: added `upstash-redis==1.7.0`
- `.gitignore`: fixed — `next-env.d.ts` was accidentally concatenated with `.env.local` entry
- `api/kv.py`: new module — `get_locked_projection()`, `set_locked_projection()` (NX flag), `get_all_locked_projections()`
- `api/espn.py`: imports kv helpers; `get_projected_fpts()` accepts `season`, `period`, `today_str` params; locks `fpts_per_game` into KV for each past/today start; returns `lockedProjections` in API response
- `pages/my-team.tsx`: `lockedProjections` state, cache (CACHE_VERSION → 4), and ScheduleGrid prop wiring; fixed relievers grid rendering starters data
- `components/ScheduleGrid.tsx`: DayCell uses `lockedProjections?.[pitcher.name]?.[date]` for past/today cells with live `fptsPerStart` as fallback

### Full-name probable pitcher matching (PR #43)
- `api/mlb.py`: `fetch_espn_probables` and `fetch_mlb_probables` now store `full_name.strip().lower()` as key instead of last name
- `api/mlb.py`: `get_starts_for_players` looks up by full lowercase name instead of last name
- Removes all suffix handling code (`jr.`/`sr.`/`ii`/`iii`) — no longer needed
- Fixes Shane Baz and Shane Smith probable pitcher detection

### Bench player starts fix (PR #46)
- `api/espn.py`: bench player `startDates` filter changed from `< today_str` to `<= today_str`
- `scheduled_starts` for bench players now counts today's confirmed starts instead of hardcoding 0
- Fixes players in lineup slot 16 not showing today's confirmed probable start

---

## Session 10 — April 9, 2026

Opponent quality adjustment using team wOBA factors. One PR shipped (#39).

### Key learnings this session
- MLB Stats API `/api/v1/teams/stats` returns team-level hitting stats for all 30 teams in one call — free, no auth, same API we already use for pitcher stats.
- wOBA (weighted on-base average) is the best single stat for measuring offensive quality — it weights each outcome (BB, HBP, 1B, 2B, 3B, HR) by its run value rather than treating them equally like OBP.
- Normalizing to league average (factor = team_wOBA / lg_avg) is cleaner than using raw wOBA — it makes 1.0 always mean "average opponent" regardless of league-wide offensive environment year to year.
- 10-game minimum threshold before trusting team wOBA — small samples produce noisy factors early in the season.
- Per-start opponent adjustment (sum each start's adjusted fpts) is mathematically equivalent to average-factor × total but easier to extend when we want per-start UI context later.
- RPs excluded from matchup adjustment — their appearance rate is driven by game state and save situations, not opponent quality.
- `get_starts_for_players()` needed a `team_map` parameter to look up each pitcher's opponent per start date — the schedule dict already had this data, just needed to thread the team abbreviation through.
- The MLB Stats API uses `AZ` as Arizona's abbreviation but our schedule uses `ARI` — always verify abbreviation normalization when adding new data sources.

### Opponent quality adjustment
- `api/mlb.py`: `get_team_woba()` — fetches team hitting stats, computes wOBA per team, returns factors relative to league average
- `api/mlb.py`: `MLB_TEAM_ID_TO_ABBREV` — hardcoded MLB Stats API team ID → abbreviation map (verified 2026)
- `api/mlb.py`: `get_starts_for_players()` now accepts `team_map` parameter — adds `opponent` field to each `startDate` entry
- `api/mlb.py`: `build_pitcher_starts()` cleaned up — removed unused `schedule` parameter
- `api/espn.py`: `get_team_woba` imported from `mlb`
- `api/espn.py`: `get_team_woba()` called once at top of `get_league_data()` — result passed to both roster and FA projection calls
- `api/espn.py`: `roster_team_map` and `fa_team_map` built from `PRO_TEAM_MAP` and passed to `get_starts_for_players()`
- `api/espn.py`: `startDates` (with opponent) now included in Option B inputs for both roster and FA pitchers
- `api/espn.py`: `get_projected_fpts()` accepts `team_woba_factors` — applies per-start matchup factor before summing period total
- RPs use flat appearances-per-week estimate with no matchup adjustment

---

## Session 9 — April 9, 2026

Sortable free agents table, SP slot filter fix, FA actual FPTS, and projection model fixes. One PR shipped (#37).

### Key learnings this session
- ESPN's `kona_player_info` with `limit: 100` returns top 100 players across all positions — without `filterSlotIds: [14]`, only ~29 of those are SPs. Always filter by slot before applying limits.
- `get_actual_fpts()` fetches whole-league roster data per day — free agents who were never rostered have no retrievable stats. Accept the limitation; show data when available.
- Minimum sample size thresholds are essential in projection models — a pitcher with 1 start and a win produces absurdly inflated per-game averages. 3 starts for SPs, 5 appearances for RPs.
- The `hasFpts || isToday` pattern for conditional rendering: past days need actual data before showing projections (comparison context), but today should always show projections (game is live or upcoming).
- Sort state should never mutate the source array — derive a sorted copy with `useMemo`, keep source as truth for checkbox state.
- When rows are reordered by sort, index-based state updates break — look up by name instead of index.
- Branch cleanup: `git fetch --prune` syncs local refs with remote, removing stale tracking branches from deleted PRs.

### Sortable free agents table
- `pages/free-agents.tsx`: `sortCol` and `sortDir` state added
- `pages/free-agents.tsx`: `handleSort()` — cycles desc → asc → reset to default on third click
- `pages/free-agents.tsx`: `sortedFreeSPs` derived via `useMemo` — date columns sort by `fptsPerStart` for starters, 0 for non-starters
- `pages/free-agents.tsx`: `toggleCheck()` rewritten to look up by name instead of index — fixes checkbox behavior after sort
- `pages/free-agents.tsx`: Own% header wired to `handleSort` with arrow indicator
- `components/ScheduleGrid.tsx`: `sortCol`, `sortDir`, `onSortChange` props added
- `components/ScheduleGrid.tsx`: all sortable column headers get click handlers and ↓/↑ indicators
- `components/ScheduleGrid.tsx`: duplicate `}}` closing brace on `Props` interface removed

### Fix: SP slot filter on free agent fetch
- `api/espn.py`: `filterSlotIds: [14]` added to FA `kona_player_info` filter
- Free agent count jumped from 29 to 100 — low-ownership probable starters now visible

### Actual FPTS for free agents
- `api/espn.py`: `get_actual_fpts()` now receives roster + FA names combined via set union
- `api/espn.py`: `faActualFpts` split from roster `actualFpts` in return dict
- `pages/free-agents.tsx`: `faActualFpts` wired into cache, state, and `ScheduleGrid`
- Act FPTS column now appears on Free Agents page

### Projection model fixes
- `api/espn.py`: `per_game_avgs()` now requires minimum sample — 3 starts (SP), 5 appearances (RP)
- Prevents inflated projections from tiny samples (Grant Taylor 41.9 → 0.0)
- `components/ScheduleGrid.tsx`: today's start cells show (proj: +X.X) even before actual FPTS arrives

---

## Session 8 — April 8, 2026

FA projections, per-start cell projections, actual FPTS column, and bug fixes. One PR shipped (#35).

### Key learnings this session
- Cache version bumps are critical any time the API response shape changes — without them, users with stale caches silently get empty data rather than an error. Always bump `CACHE_VERSION` when adding new fields.
- When a fetch function sets state from an API response, the key names must match exactly — `data.rosterFptsPerStart` not `data.fptsPerStart`. A mismatch silently sets state to `{}` with no error.
- Hard refresh (`Cmd+Shift+R`) busts the browser's JS cache and is a reliable first debugging step when deployed behavior doesn't match expectations.
- The IIFE pattern (`(() => { const x = ...; return <td>...</td> })()`) is the clean way to compute local variables inside JSX expressions where `const` declarations aren't allowed inline.
- Conditional column rendering with `{actualFpts && <th>...</th>}` lets one component serve two pages with different column layouts — no duplication.
- A dead `if not is_rp else` branch inside an `if is_rp:` block always takes the else path — effectively a no-op wrapper that makes code unreadable. Simplify to the direct expression.

### Free agent projections
- `api/espn.py`: `fa_option_b_inputs` built for free agents — same structure as roster Option B inputs
- `api/espn.py`: `get_projected_fpts()` called for free agents; `fa_proj_fpts`, `fa_proj_blend`, `fa_fpts_per_start` returned
- `api/espn.py`: `projFpts` and `projBlend` now populated on each free agent dict (was hardcoded `0.0`)
- `api/espn.py`: `faFptsPerStart` added to API response

### Per-start projections in schedule grid cells
- `api/espn.py`: `get_projected_fpts()` now returns a third dict `fpts_per_start` — per-game FPTS average per pitcher
- `api/espn.py`: `rosterFptsPerStart` added to API response
- `components/ScheduleGrid.tsx`: new `fptsPerStart` prop (`Record<string, number>`) added to `Props` and `DayCell`
- `components/ScheduleGrid.tsx`: future start cells show per-start projection in gray below ✅ or P badge
- `components/ScheduleGrid.tsx`: past start cells show `(proj: +X.X)` in gray below actual FPTS — only when actual FPTS is also present
- `pages/my-team.tsx` + `pages/free-agents.tsx`: `fptsPerStart` state added, fetched, cached, restored, and passed to `ScheduleGrid`

### Actual FPTS column
- `components/ScheduleGrid.tsx`: new Act FPTS column — sums `actualFpts` across all days for each pitcher
- Column only renders when `actualFpts` prop is provided — appears on My Team, absent on Free Agents
- Positive totals in green, negative in red, zero as `—`
- Sits left of Proj FPTS column for direct comparison

### Bug fixes
- `api/espn.py`: fixed dead `if not is_rp else` branch inside `if is_rp:` RP projection block — simplified to direct expression
- `pages/my-team.tsx`: fixed `setFptsPerStart(data.fptsPerStart)` → `setFptsPerStart(data.rosterFptsPerStart)` — was silently setting state to `{}` after every Refresh click
- `CACHE_VERSION` bumped to 3 on both `my-team.tsx` and `free-agents.tsx`

---

## Session 7 — April 7, 2026 (part 3)

Projection model brainstorm and prioritization. No code written.

### Projection model roadmap established
- Ranked accuracy improvements by impact and buildability
- Identified free agent projections and per-start cell display as immediate next priorities
- Full ranking documented in backlog

---

## Session 7 — April 7, 2026 (part 2)

Roster transaction lag fix and Option B projected FPTS model with blended 2025/2026 stats.

### Key learnings this session
- ESPN locks the current scoring period's roster once any game starts. The fix is to check the schedule for `in_progress` or `final` games and re-fetch at `scoringPeriodId + 1` when detected. One extra ESPN API call only when needed.
- MLB Stats API season stats endpoint returns all pitchers in one call: `/api/v1/stats?stats=season&playerPool=all&group=pitching`. Fast and reliable — no auth required.
- IP is stored as a string like "34.2" meaning 34 innings + 2 outs, not 34.2 actual innings. Must parse as `full_innings + outs/3`.
- MLB Stats API uses accented names ("Edwin Díaz") while ESPN uses plain ASCII ("Edwin Diaz"). Must normalize both sides with `unicodedata.normalize('NFD')` + strip combining characters before comparing.
- Blend threshold for RPs should be 20 IP, not 50 IP. At ~1 IP/appearance and 3-4 appearances/week, 50 IP takes ~13 weeks for a reliever vs ~6 weeks for a starter. Same calendar time = different IP threshold.
- Python UnboundLocalError: if a variable is assigned in any branch of an if/elif/else block, Python treats it as local to the whole function. Must assign a default value before the block, not rely on a prior assignment being "close enough."
- Hardcoded ESPN standard scoring formula was wrong for this league. League uses W×+5, L×-5, SV×+5 vs standard W×+2, L×-2, SV×+2. Always verify league settings before hardcoding a formula.
- `gamesPlayed` used for RP appearance count, `gamesStarted` for SP start count — different field for the denominator depending on pitcher role.

### Roster transaction lag fix
- `api/espn.py`: new `today_has_started(schedule)` helper — checks if any game today is `in_progress` or `final`
- `api/espn.py`: after fetching schedule, if `today_has_started()` returns True, re-fetch roster at `scoringPeriodId = current_week + 1`
- Falls back silently to original roster if re-fetch fails or team not found in response

### Option B projected FPTS model
- `api/espn.py`: new `get_projected_fpts(player_starts)` function
- `api/espn.py`: new `strip_accents()` helper using `unicodedata` for MLB↔ESPN name normalization
- Fetches 2025 and 2026 MLB Stats API season stats in parallel via `ThreadPoolExecutor(max_workers=2)`
- Blend weight: `this_year_weight = min(1.0, ip_2026 / threshold)` where threshold=50 for SP, 20 for RP
- Per-game averages calculated from season totals, formula applied, multiplied by projected starts (SP) or estimated appearances (RP, 4/week)
- League scoring: IP×3, K×1, H×-1, BB×-1, ER×-2, HB×-1, W×+5, L×-5, SV×+5
- `projBlend` field added to each roster player in API response (0.0–1.0, fraction of 2026 data)
- `components/ScheduleGrid.tsx`: blend % shown under Proj FPTS when > 0 (e.g. "29% '26")
- `pages/my-team.tsx`: `RosterSP` interface updated with optional `projBlend` field

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