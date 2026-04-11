# The Skipper — Backlog

Last updated: April 11, 2026

---

## ✅ Completed (session April 11, 2026)

### Projection sequencing + bench/IL normalization (PR #49)
- [x] Moved transaction lag re-fetch before `option_b_inputs` — lineup slots now fresh when building projection inputs
- [x] Removed bench/IL skip from `option_b_inputs` — all pitchers get projections computed
- [x] Removed bench/IL branch from roster parsing — all pitchers treated identically for projections and start counting
- [x] `get_slot_label()` now uses `eligibleSlots` + `player.injured` instead of `lineupSlotId`
- [x] `get_status()` simplified to use `player.injured` boolean
- [x] Added `position` field (SP/RP) to roster entries, independent of IL slot
- [x] Fixed IL players (Pepiot, Kelly) missing from My Team starters grid
- [x] Fixed `get_projected_fpts()` empty return: 2 values → 3

### ESPN API investigation
- [x] Built `debug_roster.py` endpoint to fetch per-day lineup slots across full matchup period
- [x] Verified `lineupSlotId` is per-day accurate: 98 data points across 7 days × 14 players, 0 mismatches vs ESPN website
- [x] Confirmed `player.injured` (boolean) is the reliable IL signal — `injuryStatus` string is empty for all rostered players
- [x] Confirmed `eligibleSlots` determines SP vs RP (stable attribute), not `lineupSlotId` (daily lineup decision)
- [x] Confirmed bench status is a daily lineup decision with no impact on The Skipper's projections

### Documentation
- [x] Created `KNOWLEDGE.md` — permanent reference for API behavior, architecture decisions, league settings
- [x] Each section includes confidence rating (1-10) and last-assessed date
- [x] Added `.DS_Store` to `.gitignore`

---

## ✅ Completed (session April 10, 2026)

### Upstash KV locked projections infrastructure
- [x] `api/kv.py`: new helper module — all Upstash Redis read/write logic in one place
- [x] Key schema: `proj:{season}:{period}:{player-slug}:{date}` → float
- [x] `get_locked_projection()`: reads existing lock, returns None if not yet locked
- [x] `set_locked_projection()`: writes with NX flag — never overwrites existing lock
- [x] `get_all_locked_projections()`: returns full period dict for API response
- [x] `api/espn.py`: locks fpts_per_game into KV for each start that is today or past
- [x] `api/espn.py`: passes `lockedProjections` dict in API response
- [x] `pages/my-team.tsx`: wires lockedProjections into state, cache (CACHE_VERSION → 4), and ScheduleGrid props
- [x] `components/ScheduleGrid.tsx`: DayCell uses locked projection for past/today cells, live fptsPerStart for future cells
- [x] Fixed pre-existing bug: relievers ScheduleGrid was rendering rosterStarterSPs instead of rosterRelievers

### Full-name probable pitcher matching
- [x] Replaced last-name-only key with `full_name.strip().lower()` throughout `mlb.py`
- [x] `fetch_espn_probables`: stores `{ 'shane baz': ['2026-04-10'] }` instead of `{ 'baz': [...] }`
- [x] `fetch_mlb_probables`: same — full lowercase name as key
- [x] `get_starts_for_players`: looks up by full name instead of last name
- [x] Fixes Shane Baz probable starts not being detected
- [x] Fixes Shane Smith (CWS) probable pitcher collision with other Smiths

### Bench player starts fix
- [x] Bench player startDates filter used strict `<` — excluded today's confirmed starts
- [x] Changed to `<=` so today's confirmed start is included for bench-slotted players
- [x] `scheduled_starts` now counts today's confirmed starts rather than hardcoding 0

---

## ✅ Completed (session April 9, 2026)

### Sortable free agents table
- [x] Click any column header to sort — Pitcher, Starts, Proj FPTS, Own%, individual date columns
- [x] Date column sort ranks by `fptsPerStart` for starters on that day, 0 for non-starters
- [x] Active sort column shows ↓ or ↑ arrow indicator
- [x] First click = desc, second click = asc, third click = reset to default (Own% desc)
- [x] Checkbox toggles correctly after sort via name-based lookup instead of index
- [x] `sortCol`, `sortDir`, `onSortChange` props added to `ScheduleGrid`

### Fix: SP slot filter on free agent fetch
- [x] Added `filterSlotIds: [14]` to ESPN `kona_player_info` filter
- [x] Free agent count jumped from 29 to 100 — low-ownership probable starters now visible

### Actual FPTS for free agents
- [x] `get_actual_fpts()` now fetches stats for FA names alongside roster names — zero extra API calls
- [x] `faActualFpts` added to API response, split from roster `actualFpts`
- [x] Act FPTS period total column now appears on Free Agents page
- [x] Past start cells show actual points with (proj: +X.X) comparison

### Projection model fixes
- [x] Minimum sample size threshold in `per_game_avgs()` — 3 starts for SPs, 5 appearances for RPs
- [x] Prevents inflated projections from tiny samples (Grant Taylor 41.9 → 0.0)
- [x] Today's start cells show (proj: +X.X) even before actual FPTS arrives

---

## ✅ Completed (session April 8, 2026)

### Free agent projections
- [x] Call `get_projected_fpts()` for free agents using `fa_starts_map`
- [x] Same Option B blended model as roster players
- [x] `projFpts` and `projBlend` added to free agent API response
- [x] Display in Free Agents ScheduleGrid Proj FPTS column with blend % sub-label
- [x] `faFptsPerStart` added to API response

### Per-start projections in schedule grid cells
- [x] Return `fpts_per_start` from `get_projected_fpts()` alongside period total
- [x] Future start cells show per-start projection in gray below ✅ or P badge
- [x] Past start cells show `(proj: +X.X)` in gray below actual FPTS
- [x] `rosterFptsPerStart` added to API response

### Actual FPTS column
- [x] New Act FPTS column sums actual points earned per pitcher across the period
- [x] Only renders on My Team (where `actualFpts` prop is provided), not Free Agents
- [x] Sits left of Proj FPTS for direct comparison
- [x] `CACHE_VERSION` bumped to 3 on both pages

---

## ✅ Completed (session April 7, 2026 — part 2)

### Roster transaction lag fix
- [x] Detect if any MLB game today is `in_progress` or `final` using schedule data
- [x] If yes, re-fetch roster at `scoringPeriodId = currentScoringPeriod + 1`
- [x] Falls back to original roster if re-fetch fails
- [x] `today_has_started()` helper added to `espn.py`

### Projected FPTS model — Option B
- [x] `get_projected_fpts()` added to `espn.py`
- [x] Pulls 2025 and 2026 season pitching stats from MLB Stats API in parallel
- [x] Blends by IP: 0% this year at season start → 100% at 50 IP for SPs, 20 IP for RPs
- [x] League-specific scoring applied: IP×3, K×1, H×-1, BB×-1, ER×-2, HB×-1, W×+5, L×-5, SV×+5
- [x] RPs projected via appearances-per-week estimate (4/week × period length)
- [x] Blend % shown under each Proj FPTS number (e.g. "29% '26")
- [x] Unicode accent normalization via `strip_accents()` for MLB↔ESPN name matching
- [x] `projBlend` field added to API response and `RosterSP` interface

---

## ✅ Completed (session April 7, 2026 — part 1)

### Relievers section on My Team
- [x] Separate "Your Relievers" grid below the starters grid
- [x] Actual FPTS shown on appearance days
- [x] Saves tracking: ESPN stat ID 57 captured per player per day
- [x] 🔒 emoji on days a save occurred
- [x] "X team SV this period" badge in relievers section header
- [x] Saves column replaces Starts column in relievers grid
- [x] Bench-day strikethrough: FPTS earned while on bench shown in gray strikethrough

### Period dropdown — current period default + auto-fetch
- [x] `api/config.py` now returns `currentPeriod`
- [x] Dropdown defaults to current period on fresh load
- [x] Changing the dropdown now auto-fetches without requiring a manual Refresh click
- [x] `useRef` pattern used to distinguish first render from user-triggered period changes

### Cache version system
- [x] `CACHE_VERSION` constant in both pages
- [x] Version written to sessionStorage on every cache save
- [x] Version checked on cache load — mismatch triggers auto-fetch

---

## ✅ Completed (session March 29/30, 2026)

### Actual FPTS in schedule grid cells
- [x] `get_actual_fpts()` — parallel ESPN API calls via `ThreadPoolExecutor`
- [x] Past start cells show actual points in green/red below the ✓ checkmark
- [x] Works for live/today cells too

### Bench vs IL distinction fix
- [x] `lineupSlotId=16` = bench, `lineupSlotId=17` = true IL
- [x] IL/Bench players preserve past `startDates` while zeroing future projections

---

## ✅ Completed (session March 28, 2026)

### Schedule grid, probable pitchers, matchup period dropdown
- [x] `components/ScheduleGrid.tsx` — shared component
- [x] MLB Stats API + ESPN Scoreboard API dual-source probable pitcher system
- [x] Matchup period dropdown synced via sessionStorage
- [x] Complete ESPN PRO_TEAM_MAP rebuild for 2026
- [x] Main branch protection enabled on GitHub

---

## ✅ Completed (session March 27, 2026)

### Auth + navigation + data layer
- [x] NextAuth.js credentials provider
- [x] Persistent sidebar layout with four pages
- [x] MLB Stats API probable pitcher integration
- [x] All 22 matchup period dates hardcoded

---

## 🔜 Next session priorities

### Tile redesign — My Team page
- [ ] ROSTERED SPs tile: fix count to only include SP-position players (currently counts all pitchers)
- [ ] Replace SCHEDULED and STILL NEEDED tiles with:
  - ACTUAL STARTS — starts already completed this period
  - PROJECTED STARTS — actual + probable future starts (compare against limit)
- [ ] Progress bar should track projected starts vs limit

### Dropped streamers
- [ ] Players dropped mid-period who started a game should remain visible in the SP grid
- [ ] Show with a special slot badge (e.g. `EX-SP`) to indicate they are no longer rostered
- [ ] Sort dropped streamers to the bottom of the starters table
- [ ] Detect by finding players with actual FPTS in the period who are no longer in roster entries

### Store actual FPTS in Upstash KV
- [ ] Store actual FPTS per pitcher per start date in KV alongside locked projections
- [ ] Key schema: `actual:{season}:{period}:{player-slug}:{date}` → float
- [ ] Enables model accuracy analysis: `actual - projected` per start
- [ ] Reduces ESPN API calls for historical period views (read from KV instead of re-fetching)
- [ ] Required foundation for future model accuracy dashboard

### Projection model improvements — near term
- [ ] Recent form weighting (MEDIUM impact) — weight last 3-4 starts more heavily than season average
  - Game log data already fetched for actualFpts — infrastructure mostly in place

### Projected FPTS model — Option C (target mid-May)
- [ ] Replace Option B inputs with Statcast metrics from Baseball Savant
- [ ] Key inputs: xFIP, SIERA, xERA, SwStr%, CSW%
- [ ] Only meaningful after ~50 innings of 2026 data

---

## 🐛 Known bugs

- [ ] Free agent actual FPTS only available for players who were rostered at time of start — ESPN API limitation, no fix available
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue). Always test Python changes against production URL

---

## 💡 Future ideas

- Model accuracy dashboard — projected vs actual FPTS per start, mean error, directional bias, accuracy trend over time
- Dropped players section — players who started this period but were dropped should still appear
- Dashboard at-a-glance component — projected starts vs limit, current period dates, quick links
- Hitter optimizer
- Trade analyzer
- Push notifications when probable pitchers change
- Historical accuracy tracking of projection model vs actual outcomes
- Multi-user support / league sharing
- Mobile app (React Native)
- Pay for a proper probable pitchers data source (SportsDataIO, MySportsFeeds) once serving real users

---

## 🔧 Environment variables

All set in both `.env.local` (local) and Vercel dashboard (production):

| Variable | Purpose |
|---|---|
| `APP_USERNAME` | Login username |
| `APP_PASSWORD` | Login password |
| `NEXTAUTH_SECRET` | JWT encryption key |
| `NEXTAUTH_URL` | `https://the-skipper-iota.vercel.app` |
| `ESPN_LEAGUE_ID` | Fantasy league ID |
| `ESPN_SEASON` | `2026` |
| `ESPN_S2` | ESPN auth cookie |
| `ESPN_SWID` | ESPN auth cookie |
| `ESPN_TEAM_ID` | Your team number in the league |
| `ESPN_STARTS_LIMIT` | Weekly pitcher starts limit |
| `ANTHROPIC_API_KEY` | Claude API key |
| `KV_REST_API_URL` | Upstash Redis REST URL |
| `KV_REST_API_TOKEN` | Upstash Redis REST token |
| `KV_REST_API_READ_ONLY_TOKEN` | Upstash Redis read-only token |
| `KV_URL` | Upstash Redis connection URL |
| `REDIS_URL` | Upstash Redis connection URL (alias) |

---

## 🛠️ Local dev setup
```bash
cd ~/Developer/the-skipper
git checkout main
git pull origin main
vercel dev   # frontend only — Python routes require production
```

Open `http://localhost:3000`. Python API routes only work at `https://the-skipper-iota.vercel.app`.

**Deploy sequence:** `git add` → `git commit` → `vercel --prod`
**Git workflow:** Feature branches → PR → squash merge. Prefixes: `fix:`, `feat:`, `chore:`

**Important:** ESPN API requires `espn_s2` and `SWID` cookies — cannot be called directly from local machine. Always test ESPN-dependent changes against production URL after deploy.

---

## 📚 Reference

All API reference documentation, architecture decisions, league settings, and development workflow are maintained in **[KNOWLEDGE.md](KNOWLEDGE.md)** — the single source of truth for technical reference. Each section includes a confidence rating (1-10) and last-assessed date.