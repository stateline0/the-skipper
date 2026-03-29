# The Skipper — Backlog

Last updated: March 28, 2026

---

## ✅ Completed (session March 28, 2026 — evening)

### Schedule grid (PR #21)
- [x] New `components/ScheduleGrid.tsx` — shared component used by both My Team and Free Agents
- [x] Day-by-day columns showing opponent per pitcher per day, inserted between Slot and Starts
- [x] ✅ for MLB-confirmed probable starts, blue P badge for ESPN-projected starts
- [x] ✓ for past confirmed starts, blue P for past projected starts
- [x] Non-start game days show `vs OPP` / `@OPP` in gray
- [x] No-game days show `—`
- [x] Today's column: bold header + green underline + highlighted background
- [x] IL players grayed out (opacity 0.5)
- [x] Columns are dynamic — built from matchupDates range, handles any period length
- [x] `espn.py` refactored to import `get_starts_for_players` from `mlb.py` — eliminates duplicate MLB Stats API call
- [x] `mlb.py` `fetch_espn_probables` now returns full game schedule alongside probables
- [x] `schedule` and `matchupDates` added to ESPN API response and persisted in sessionStorage
- [x] Stale cache auto-refresh when cached data is missing `matchupDates`
- [x] Fix: normalize ESPN Scoreboard abbreviations to match PRO_TEAM_MAP (CHW→CWS, etc.)

### Roster fixes (same session)
- [x] Fix: remove `scoringPeriodId` from roster fetch — was returning stale roster after transactions
- [x] Fix: IL classification uses lineup slot only, not `injuryStatus` field

---

## ✅ Completed (session March 28, 2026 — earlier)

### Probable pitcher integration (PR #18)
- [x] Replace hardcoded starts=2 with dual-source probable pitcher system
- [x] New endpoint: `api/mlb.py` — fetches probable pitchers for any matchup period
- [x] MLB Stats API integration — confirmed probables 1-2 days out (`confirmed: true`)
- [x] ESPN Scoreboard API integration — projected starters up to 7 days out (`confirmed: false`)
- [x] Each start carries a per-date `confirmed` boolean for frontend confidence indicators
- [x] Fallback is now 0 starts when pitcher has no data in either source
- [x] `api/espn.py` updated to use real starts data for both roster SPs and free agents
- [x] Fix `jr.`/`sr.`/`ii`/`iii` suffix bug in pitcher name parsing (both MLB and ESPN sources)

### Matchup period dropdown + roster fixes (PR #20)
- [x] Add matchup period dropdown to My Team and Free Agents pages
- [x] Dropdown shows all 22 ESPN matchup periods with date ranges
- [x] Selecting a period re-fetches data for that date range
- [x] Selected period persists in sessionStorage so both pages stay in sync
- [x] Starts limit auto-updates to match the selected period's limit
- [x] `api/config.py` now returns full matchup period table to frontend
- [x] Remove `starts = 2` fallback — RPs and IL players now correctly show 0 starts
- [x] Remove `Math.random()` projected FPTS fallback
- [x] Remove redundant Status column from My Team (slot badge conveys same info)
- [x] My Team auto-fetches roster on first visit if no cached data exists
- [x] Complete ESPN PRO_TEAM_MAP rebuild for 2026 (all 32 IDs verified via player lookups)
- [x] Main branch protection ruleset created on GitHub
- [x] Stale branches cleaned up locally and old unmerged PR closed

---

## ✅ Completed (session March 27, 2026)

### Auth
- [x] Replace cookie-based password with NextAuth.js username + password (PR #14)
- [x] Add login/logout flow — logout button in sidebar footer
- [x] Designed for future multi-user support (single user for now, architected to scale)
- [x] Designed for future OAuth options (Google, potentially ESPN SSO)

### Navigation + layout
- [x] Persistent sidebar with Dashboard, My Team, Free Agents, Recommendations (PR #15)
- [x] Next.js page routing: `/dashboard`, `/my-team`, `/free-agents`, `/recommendations`
- [x] Login page excluded from layout
- [x] Data persists across pages via sessionStorage

### Data layer
- [x] Fix team name returning empty — now uses `name` field from ESPN API (PR #16)
- [x] Fix free agents returning empty — corrected data structure parsing + SP-only filter (PR #16)
- [x] Fix injury status labels — `SIXTY_DAY_DL` → `IL60`, `FIFTEEN_DAY_DL` → `IL15`, `DAY_TO_DAY` → `DTD` (PR #16)
- [x] Fix IL players showing 2 starts — IL players correctly show 0 starts and 0 projFpts
- [x] Fix weekStart / weekEnd returning empty — now derived from hardcoded 2026 matchup period table (PR #17)
- [x] Upgraded Next.js to 15.5.14 (patched multiple CVEs)
- [x] Fixed `.gitignore` — node_modules and .next were never properly excluded

### Previously completed (before March 27)
- [x] Password protection (original cookie middleware — now replaced by NextAuth)
- [x] ESPN API connection (private league via espn_s2 + SWID cookies)
- [x] Roster pulls with real player names
- [x] Team abbreviations (PRO_TEAM_MAP)
- [x] Slot labels: SP, RP, IL
- [x] IL badge red, RP badge amber, SP badge blue
- [x] Proj FPTS 1 decimal place
- [x] Sort order: SP → RP → IL, then starts desc, then FPTS desc
- [x] Team ID and starts limit pre-populate from env vars (`ESPN_TEAM_ID`, `ESPN_STARTS_LIMIT`)
- [x] `/api/config` endpoint for page-load pre-population
- [x] Branch/PR workflow established
- [x] Vercel deployment stable at `https://the-skipper-iota.vercel.app`

---

## 🔜 Next session priorities

### Actual FPTS in past/live cells
- [ ] Wire up ESPN Fantasy matchup box score API to pull actual FPTS earned per pitcher per day
- [ ] Past start cells show real points earned (e.g. `@CIN ✓ 26.0`)
- [ ] Live cells show in-progress points with a live indicator
- [ ] Distinguish final vs. in-progress game status
- [ ] Today's column: bold + highlighted (already done) — live scores update on refresh

### Dropped players section
- [ ] Players who started this matchup period but were subsequently dropped should still appear on My Team
- [ ] Show in a separate table below the main roster, labeled "Dropped this period"
- [ ] Slot badge shows gray "Dropped" label
- [ ] Stats and points earned still visible
- [ ] Points earned should match ESPN's matchup scoring summary

### Dashboard "at a glance" component
- [ ] "This week at a glance" tile — projected starts vs. weekly limit with visual progress
- [ ] Designed as a tile/component system so new features can be added over time
- [ ] Quick links to My Team and Free Agents
- [ ] Show current matchup period dates and opponent

### Free agents cache fix
- [ ] Apply same stale cache auto-refresh logic to Free Agents page (already done on My Team)

### Roster transaction lag fix
- [ ] After the first MLB game of the day starts, ESPN locks today's roster
- [ ] Transactions made today (adds/drops) don't appear until tomorrow's scoring period
- [ ] Fix: detect whether any game today is `in_progress` or `final` using the schedule data we already have
- [ ] If yes, fetch `scoringPeriodId = currentScoringPeriod + 1` from ESPN to get the post-transaction roster
- [ ] This ensures adds made during the day show up immediately in The Skipper
- [ ] Edge case: last day of a matchup period — tomorrow is a new period, handle gracefully

### Responsive layout (mobile)
- [ ] Sidebar collapses on mobile
- [ ] Top header gets hamburger menu on small screens

### Dropdown label improvement
- [ ] Instead of "Period N · dates", show "Week N: vs. [Opponent] · dates"
- [ ] Requires fetching matchup schedule from ESPN API to get opponent names

---

## ⚾ Data layer — remaining work

### Projected FPTS model — Option B (v1, ship now)
Currently `projFpts` shows 0.0 for all pitchers. ESPN's `appliedStatTotal` is not populated early in the season.

- [ ] Use MLB Stats API for pitcher season stats (ERA, WHIP, K/9, avg IP/start)
- [ ] Apply ESPN standard scoring formula: 3 pts/IP, 1 pt/K, -1 pt/H, -1 pt/BB, -2 pts/ER, +2 win, -2 loss
- [ ] Adjust for opponent quality (team wRC+ or OPS allowed)
- [ ] Adjust for park factor (publicly available)
- [ ] Per-start projection, summed across probable starts for weekly total
- [ ] Label clearly as "projected" not guaranteed

### Projected FPTS model — Option C (v2, after ~6 weeks of season data)
- [ ] Replace Option B inputs with Statcast metrics from Baseball Savant
- [ ] Key inputs: xFIP, SIERA, xERA, SwStr%, CSW%
- [ ] Opponent splits: xwOBA vs pitcher handedness
- [ ] Days rest adjustment
- [ ] Validate against real outcomes before deploying
- [ ] Target: 15-25% lower projection error vs Option B
- [ ] Note: only meaningful after ~50 innings of season data (mid-May 2026)

---

## 🐛 Known bugs (current version)

- [ ] `projFpts` showing 0.0 for all pitchers — ESPN's `appliedStatTotal` not populated early season. Will be fixed by Option B model.
- [ ] Shane Smith (CWS SP) probable pitcher matching not working — last name `"smith"` is likely colliding with another Smith in the ESPN Scoreboard or MLB Stats API data. His schedule cells now populate correctly (abbreviation fix resolved that), but his starts aren't being detected. Needs a more robust name matching strategy (full name or player ID) rather than last-name-only lookup.
- [ ] Shane Smith (CWS SP) showing as IL slot — ESPN API has him in lineup slot 16 (IL10) despite being active. ESPN API/UI out of sync. Resolves automatically, not a code bug.
- [ ] Dropdown label shows "Period N · dates" instead of matchup opponent — needs ESPN schedule API integration.
- [ ] `vercel dev` does not serve Python API routes locally (known issue with Vercel CLI v50+). Workaround: test against production URL `https://the-skipper-iota.vercel.app`.

---

## 🛠️ Local dev setup

Already completed on Mac — no action needed:
- [x] VS Code installed
- [x] Git CLI installed
- [x] GitHub CLI (`gh`) installed
- [x] Node.js LTS installed
- [x] Python 3.9.6 installed
- [x] Vercel CLI installed (`npm i -g vercel`)
- [x] Repo cloned: `gh repo clone stateline0/the-skipper`
- [x] `npm install` complete
- [x] `.env.local` configured with all credentials
- [x] `vercel dev` confirmed working at localhost:3000

**To start a new session:**
```bash
cd ~/Developer/the-skipper
git checkout main
git pull origin main
vercel dev
```
Then open `http://localhost:3000` in browser.

**Note:** Python API routes (`/api/espn`, `/api/mlb`, `/api/analyze`) only work in production. Test API changes by deploying with `vercel --prod` and hitting `https://the-skipper-iota.vercel.app`.

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

## 💡 Future ideas (not yet scoped)

- Hitter optimizer (lineup optimization beyond just SP)
- Trade analyzer
- Waiver wire priority ranking beyond just SPs
- Push notifications when probable pitchers change
- Historical accuracy tracking of our projection model vs actual outcomes
- Multi-user support / league sharing
- Mobile app (React Native)
- Pay for a proper probable pitchers data source (SportsDataIO, MySportsFeeds) once serving real users — ~$10-30/month for full 10-day projections