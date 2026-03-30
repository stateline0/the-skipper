# The Skipper — Backlog

Last updated: March 30, 2026

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

## 🔜 Next session priorities

### Relievers section on My Team (highest priority)
- [ ] Add a separate "My Relievers" table below the starters grid
- [ ] Shows RP-slot players (Jeff Hoffman, Edwin Diaz, David Bednar, etc.)
- [ ] Simpler display than the starters grid — summed actual FPTS for the period
- [ ] If an RP has a confirmed or actual start this period, promote them into the starters section
- [ ] Explore tracking Saves — either per-player or as a group total (ESPN stat ID 57 = saves, confirmed in raw API data)
- [ ] Bench players (slot 16) should appear here, not in the IL section

### Reliever actual FPTS — known gap
- [ ] `actualFpts` is fetched for all `roster_sps` names — RPs are included but need to verify points are displaying correctly in the new Relievers section
- [ ] Jeff Hoffman showed 9.0 pts on Mar 27 and Mar 29 in the raw data — confirm this surfaces in the UI

### Dashboard "at a glance" component
- [ ] "This week at a glance" tile — projected starts vs. weekly limit with visual progress bar
- [ ] Current matchup period dates and opponent
- [ ] Quick links to My Team and Free Agents
- [ ] Tile/component system so new features slot in over time

### Roster transaction lag fix
- [ ] ESPN locks today's roster once the first MLB game starts
- [ ] Adds/drops made during the day don't appear until the next scoring period
- [ ] Fix: detect if any game today is `in_progress` or `final` using schedule data we already have
- [ ] If yes, fetch `scoringPeriodId = currentScoringPeriod + 1` to get the post-transaction roster
- [ ] Edge case: last day of matchup period — tomorrow is a new period, handle gracefully

### Shane Smith probable pitcher matching bug
- [ ] Last-name-only matching (`"smith"`) collides with other Smiths in the data
- [ ] Fix: use full name or ESPN player ID for matching instead of last name only
- [ ] His schedule cells populate correctly (abbreviation fix worked) but starts aren't detected

---

## ⚾ Data layer — remaining work

### Projected FPTS model — Option B (v1, ship now)
- [ ] `projFpts` shows 0.0 for all pitchers — ESPN's `appliedStatTotal` not populated early in season
- [ ] Use MLB Stats API for pitcher season stats (ERA, WHIP, K/9, avg IP/start)
- [ ] Apply ESPN standard scoring formula: 3 pts/IP, 1 pt/K, -1 pt/H, -1 pt/BB, -2 pts/ER, +2 win, -2 loss
- [ ] Per-start projection, summed across probable starts for weekly total
- [ ] Label clearly as "projected" not guaranteed

### Projected FPTS model — Option C (v2, after ~6 weeks of season data)
- [ ] Replace Option B inputs with Statcast metrics from Baseball Savant
- [ ] Key inputs: xFIP, SIERA, xERA, SwStr%, CSW%
- [ ] Only meaningful after ~50 innings of season data (mid-May 2026)
- [ ] Target: 15-25% lower projection error vs Option B

### Dropped players section
- [ ] Players who started this matchup period but were subsequently dropped should still appear
- [ ] Show in a separate table below main roster, labeled "Dropped this period"
- [ ] Points earned should match ESPN's matchup scoring summary

---

## 🐛 Known bugs (current version)

- [ ] `projFpts` showing 0.0 for all pitchers — ESPN's `appliedStatTotal` not populated early season. Fixed by Option B model.
- [ ] Shane Smith (CWS SP) probable pitcher starts not being detected — last-name-only matching collision.
- [ ] ESPN slot 16 vs slot 17 behavior confirmed for this league (16=bench, 17=IL) but may vary by league settings — worth noting if app ever goes multi-user.
- [ ] Roster transaction lag — adds/drops made after first game of day don't appear until next scoring period.
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
- `appliedStatTotal` not populated early in the season → `projFpts` shows 0.0 until Option B model ships
- Roster locked to current scoring period once first game starts → transaction lag bug
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
- Used for: confirmed probables, game schedules, pitcher stats (future Option B model)

## 📚 ESPN Scoreboard API reference

- Base: `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD`
- Public, no auth required
- Returns probable starters up to 7 days out
- Uses `CHW` for White Sox (not `CWS`) — normalization required
- FantasyPros and FanGraphs probables are JS-rendered — not scrapeable server-side