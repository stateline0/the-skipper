# The Skipper — Backlog

Last updated: April 7, 2026

---

## ✅ Completed (session April 7, 2026 — part 2)

### Roster transaction lag fix
- [x] Detect if any MLB game today is `in_progress` or `final` using schedule data
- [x] If yes, re-fetch roster at `scoringPeriodId = currentScoringPeriod + 1`
- [x] Falls back to original roster if re-fetch fails
- [x] `today_has_started()` helper added to `espn.py`
- [x] Handles last day of matchup period gracefully (tomorrow's period is correct behavior)

### Projected FPTS model — Option B
- [x] `get_projected_fpts()` added to `espn.py`
- [x] Pulls 2025 and 2026 season pitching stats from MLB Stats API in parallel via `ThreadPoolExecutor`
- [x] Blends by IP: 0% this year at season start → 100% at 50 IP for SPs, 20 IP for RPs
- [x] RP threshold lower (20 IP) because relievers reach 50 IP much later in the season (~13 weeks vs ~6)
- [x] League-specific scoring applied: IP×3, K×1, H×-1, BB×-1, ER×-2, HB×-1, W×+5, L×-5, SV×+5
- [x] RPs projected via appearances-per-week estimate (4/week × period length) rather than starts
- [x] Blend % shown under each Proj FPTS number (e.g. "29% '26")
- [x] Unicode accent normalization via `strip_accents()` for MLB↔ESPN name matching (e.g. Edwin Díaz → Edwin Diaz)
- [x] Falls back to ESPN's `appliedStatTotal` if MLB Stats API unavailable
- [x] `projBlend` field added to API response and `RosterSP` interface
- [x] `ScheduleGrid` Pitcher interface updated with optional `projBlend` field

---

## ✅ Completed (session April 7, 2026 — part 1)

### Relievers section on My Team
- [x] Separate "Your Relievers" grid below the starters grid using `ScheduleGrid` component
- [x] Day-by-day matchup cells for RPs — same layout as starters
- [x] Actual FPTS shown on appearance days (not just start days) — fixed `DayCell` to render points for non-start appearances
- [x] Saves tracking: ESPN stat ID 57 captured per player per day in `get_actual_fpts()`
- [x] 🔒 emoji on days a save occurred
- [x] "X team SV this period" badge in relievers section header
- [x] Saves column replaces Starts column in relievers grid (`savesData` prop on `ScheduleGrid`)
- [x] Bench-day strikethrough: FPTS earned while on bench shown in gray strikethrough
- [x] `actualSaves` and `benchDays` added to ESPN API response and persisted in sessionStorage
- [x] `ScheduleGrid` now accepts `savesData`, `actualSaves`, `benchDays` props

### Period dropdown — current period default + auto-fetch
- [x] `api/config.py` now returns `currentPeriod` — calculated by comparing today's date against the period table
- [x] Dropdown defaults to current period on fresh load (was always defaulting to Period 1)
- [x] Changing the dropdown now auto-fetches without requiring a manual Refresh click
- [x] `useRef` pattern used to distinguish first render from user-triggered period changes
- [x] Applied to both `my-team.tsx` and `free-agents.tsx`

### Config date format fix
- [x] `api/config.py` MATCHUP_PERIODS table converted from human-readable strings ("Apr 6") to full ISO dates ("2026-04-06")
- [x] Dropdown option labels formatted in frontend with a `fmt()` helper
- [x] Consistent with `mlb.py` date format — single source of truth now properly structured

### Cache version system
- [x] `CACHE_VERSION = 2` constant in `my-team.tsx` and `free-agents.tsx`
- [x] Version written to sessionStorage on every cache save
- [x] Version checked on cache load — mismatch triggers auto-fetch instead of loading stale data
- [x] Eliminates need to manually clear browser storage when API response shape changes

---

## ✅ Completed (session March 29/30, 2026)

### Free agents cache fix
- [x] Auto-fetch free agents when cached data is missing `matchupDates` field
- [x] Mirrors the stale cache detection logic already present on My Team
- [x] `savedPeriod` moved before cache check so correct period is set before any fetch

### Actual FPTS in schedule grid cells
- [x] New `get_actual_fpts()` function in `espn.py` — parallel ESPN API calls (one per past day) via `ThreadPoolExecutor`
- [x] `date_to_scoring_period()` helper — converts YYYY-MM-DD to ESPN daily scoring period ID (Mar 25 = period 1)
- [x] Past start cells now show actual points (+26.0, -9.0 etc.) in green/red below the ✓ checkmark
- [x] `actualFpts` added to ESPN API response and persisted in sessionStorage on both pages
- [x] Works for live/today cells too (e.g. Shane Baz's +4.0 on Mar 29 while game was in progress)

### Bench vs IL distinction fix
- [x] `lineupSlotId=16` = bench (healthy player parked there), `lineupSlotId=17` = true IL
- [x] Edwin Diaz and David Bednar now correctly show as RP/Bench instead of IL
- [x] Ryan Pepiot and Merrill Kelly correctly show as IL
- [x] IL/Bench players preserve past `startDates` history while zeroing future projections
- [x] `injuryStatus` field is empty string for all players in this league — slot ID is the only reliable signal

---

## ✅ Completed (session March 28, 2026 — evening)

### Schedule grid (PR #21)
- [x] New `components/ScheduleGrid.tsx` — shared component used by both My Team and Free Agents
- [x] Day-by-day columns showing opponent per pitcher per day
- [x] ✅ for MLB-confirmed probable starts, blue P badge for ESPN-projected starts
- [x] ✓ for past confirmed starts, gray opponent label for non-start game days, — for no-game days
- [x] Today's column: bold header + green underline + highlighted background + "TODAY" label
- [x] IL players grayed out (opacity 0.5)
- [x] `espn.py` refactored to import `get_starts_for_players` from `mlb.py`
- [x] `mlb.py` `fetch_espn_probables` returns full game schedule alongside probables
- [x] `schedule` and `matchupDates` added to ESPN API response and persisted in sessionStorage
- [x] Stale cache auto-refresh when cached data is missing `matchupDates`
- [x] Fix: normalize ESPN Scoreboard abbreviations (CHW→CWS etc.)
- [x] Fix: remove `scoringPeriodId` from roster fetch — was returning stale roster

---

## ✅ Completed (session March 28, 2026 — earlier)

### Probable pitcher integration (PR #18)
- [x] Replace hardcoded starts=2 with dual-source probable pitcher system
- [x] MLB Stats API: confirmed probables 1-2 days out (`confirmed: true`)
- [x] ESPN Scoreboard API: projected starters up to 7 days out (`confirmed: false`)
- [x] Fallback is 0 starts when pitcher has no data in either source
- [x] Fix `jr.`/`sr.`/`ii`/`iii` suffix bug in pitcher name parsing

### Matchup period dropdown + roster fixes (PR #20)
- [x] Matchup period dropdown on My Team and Free Agents, synced via sessionStorage
- [x] `api/config.py` returns full 22-period matchup table to frontend
- [x] Starts limit auto-updates to match selected period
- [x] Remove `starts = 2` and `Math.random()` fallbacks
- [x] Remove redundant Status column from My Team
- [x] My Team auto-fetches on first visit if no cached data exists
- [x] Complete ESPN PRO_TEAM_MAP rebuild for 2026 (all 32 IDs verified)
- [x] Main branch protection enabled on GitHub

---

## ✅ Completed (session March 27, 2026)

### Auth + navigation + data layer (PRs #14–#17)
- [x] Replace cookie auth with NextAuth.js credentials provider
- [x] Persistent sidebar layout with `/dashboard`, `/my-team`, `/free-agents`, `/recommendations`
- [x] Fix team name, free agent fetching, injury status labels
- [x] MLB Stats API integration for probable pitchers
- [x] All 22 matchup period dates hardcoded (ESPN `matchupPeriodDates` not returned for this league)
- [x] Next.js upgraded to 15.5.14 (patched CVEs)
- [x] Fixed `.gitignore`

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

## 🔜 Next session priorities

### Dashboard "at a glance" component
- [ ] "This week at a glance" tile — projected starts vs. weekly limit with visual progress bar
- [ ] Current matchup period dates and opponent
- [ ] Quick links to My Team and Free Agents
- [ ] Tile/component system so new features slot in over time

### Shane Smith probable pitcher matching bug
- [ ] Last-name-only matching (`"smith"`) collides with other Smiths in the data
- [ ] Fix: use full name or ESPN player ID for matching instead of last name only
- [ ] His schedule cells populate correctly (abbreviation fix worked) but starts aren't detected

### League scoring settings UI
- [ ] Settings form where user can enter custom scoring multipliers
- [ ] Stored in `localStorage` (persistent across sessions)
- [ ] Projection formula reads from stored settings instead of hardcoded constants
- [ ] Pre-populated with current league values as defaults
- [ ] Generalizes app to any ESPN league scoring configuration

---

## ⚾ Data layer — remaining work

### Projection accuracy improvements — Bundle 1 (next 1-2 sessions)
Implement as a group since they're all contextual per-start adjustments:
- [ ] **Opponent offensive strength** (HIGH impact) — adjust projection based on opponent team wOBA or K-rate from MLB Stats API. Multiplier: ~×1.15 vs weak offense, ~×0.85 vs strong offense
- [ ] **Park factors** (HIGH impact) — hardcoded table of 30 park factors adjusting H and ER components. Coors ~+30%, Petco ~-15%. Stable year-over-year, essentially free accuracy
- [ ] **Home/away split** (MEDIUM impact, very low effort) — flat adjustment using existing `is_home` field. ~×1.05 home, ~×0.95 away

### Projection accuracy improvements — Bundle 2 (session after Bundle 1)
- [ ] **Days of rest** (MEDIUM impact) — pitcher on 4 days rest projects lower than 5+ days. Calculate from last start date vs next start date, already in schedule data
- [ ] **Recent form weighting** (MEDIUM impact) — weight last 3-4 starts more heavily than season average. Requires game log fetch (already done for actual FPTS). Captures hot/cold streaks season averages wash out

### Projected FPTS model — Option C (after ~50 IP of 2026 data, target mid-May)
- [ ] Replace Option B inputs with Statcast metrics from Baseball Savant
- [ ] Key inputs: xFIP, SIERA, xERA, SwStr%, CSW%
- [ ] Only meaningful after ~50 innings of season data — mid-May 2026 for most starters
- [ ] Target: 15-25% lower projection error vs Option B
- [ ] At that point most SPs will naturally be near/past the 50 IP blend threshold anyway

### Projection improvements — future / lower priority
- [ ] **Handedness splits** (LOW-MEDIUM impact, HIGH effort) — pitcher vs L/R lineup composition. Requires per-pitcher split data and opponent lineup handedness. Marginal gain over opponent wOBA
- [ ] **Weather** (LOW impact) — wind/temperature affect scoring but APIs cost money and effect is small. Not worth it

### Dropped players section
- [ ] Players who started this matchup period but were subsequently dropped should still appear
- [ ] Show in a separate table below main roster, labeled "Dropped this period"
- [ ] Points earned should match ESPN's matchup scoring summary

---

## 🐛 Known bugs (current version)

- [ ] Shane Smith (CWS SP) probable pitcher starts not being detected — last-name-only matching collision.
- [ ] ESPN slot 16 vs slot 17 behavior confirmed for this league (16=bench, 17=IL) but may vary by league settings — worth noting if app ever goes multi-user.
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue). Always test Python changes against production URL.

---

## 💡 Future ideas (not yet scoped)

- Hitter optimizer (lineup optimization beyond just SP)
- Trade analyzer
- Waiver wire priority ranking beyond just SPs
- Push notifications when probable pitchers change
- Historical accuracy tracking of projection model vs actual outcomes
- Multi-user support / league sharing
- Mobile app (React Native)
- Pay for a proper probable pitchers data source (SportsDataIO, MySportsFeeds) once serving real users — ~$10-30/month

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

---

## 📚 ESPN API reference (hard-won knowledge)

### Base URL
```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}/segments/0/leagues/{league_id}
```

### Key views
- `mRoster` — full roster with player entries and stats
- `mTeam` — team metadata (name, etc.)
- `mMatchupScore` — matchup scoring data
- `kona_player_info` — projected stats, requires `x-fantasy-filter` header

### Scoring periods
- ESPN uses a **daily scoring period counter** starting from opening day
- 2026: March 25 = period 1, March 26 = period 2, etc.
- Formula: `scoringPeriodId = (date - 2026-03-25).days + 1`
- **Never pass matchup period number as scoringPeriodId** — this was the roster staleness bug

### Per-game stats
- `statSplitTypeId=5` = per-game log entries
- One entry per game, keyed by `scoringPeriodId`
- `appliedTotal` = actual fantasy points earned that game
- `stats` dict within each entry contains raw stat values keyed by stat ID
- Stat ID 57 = saves — confirmed in raw API data
- Must fetch with the specific day's `scoringPeriodId` to get that day's stats
- No single call returns full history — use parallel fetching via `ThreadPoolExecutor`

### Lineup slots
- Slot 13 = P (pitcher, any)
- Slot 14 = SP
- Slot 16 = Bench (healthy player parked here) ← confirmed for this league
- Slot 17 = IL (injured player) ← confirmed for this league
- **Note:** slot numbering may vary by league settings
- `injuryStatus` field is **empty string** for all players in this league — not a reliable signal

### Auth
- Requires `espn_s2` and `SWID` cookies
- Must use `lm-api-reads.fantasy.espn.com` not `fantasy.espn.com` (the latter redirects to HTML)
- CloudFront blocks requests without a browser-like `User-Agent` header

### Known limitations
- `matchupPeriodDates` not returned for this league → all 22 period dates are hardcoded in `api/config.py`
- `appliedStatTotal` not populated early in the season → replaced by Option B model
- Roster locked to current scoring period once first game starts → fixed by transaction lag fix
- ESPN Scoreboard API uses `CHW` for White Sox; our map uses `CWS` → normalization map in `mlb.py`
- ESPN caches roster data server-side — cache-busting query params have no effect

### PRO_TEAM_MAP (2026 verified)
```
1=BAL, 2=BOS, 3=LAA, 4=CWS, 5=CLE, 6=DET, 7=KC, 8=MIL, 9=MIN, 10=NYY,
11=ATH, 12=SEA, 13=TEX, 14=TOR, 15=ATL, 16=CHC, 17=CIN, 18=HOU, 19=LAD,
20=WSH, 21=NYM, 22=PHI, 23=PIT, 24=STL, 25=SD, 26=SF, 27=COL, 28=MIA,
29=ARI, 30=TB, 31=FA, 32=FA
```
---

## 📚 MLB Stats API reference

- Base: `https://statsapi.mlb.com`
- Confirms probable pitchers 1-2 days out only
- Free, no auth required
- Season stats endpoint: `/api/v1/stats?stats=season&playerPool=all&group=pitching&season=YYYY&gameType=R&limit=1000`
- Returns `gamesStarted`, `gamesPlayed`, `inningsPitched`, `strikeOuts`, `hits`, `baseOnBalls`, `earnedRuns`, `hitBatsmen`, `wins`, `losses`, `saves`
- IP stored as string e.g. "34.2" meaning 34 innings + 2 outs = 34.667 actual innings
- Player names may use accented characters (e.g. "Edwin Díaz") — normalize with `strip_accents()` before matching against ESPN names

## 📚 ESPN Scoreboard API reference

- Base: `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD`
- Public, no auth required
- Returns probable starters up to 7 days out
- Uses `CHW` for White Sox (not `CWS`) — normalization required
- FantasyPros and FanGraphs probables are JS-rendered — not scrapeable server-side

## 📚 League scoring settings (Good Season Imanagas)

| Stat | Points |
|---|---|
| Innings Pitched (IP) | +3 |
| Strikeouts (K) | +1 |
| Hits Allowed (H) | -1 |
| Earned Runs (ER) | -2 |
| Walks Issued (BB) | -1 |
| Hit Batsmen (HB) | -1 |
| Wins (W) | +5 |
| Losses (L) | -5 |
| Saves (SV) | +5 |