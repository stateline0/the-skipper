# The Skipper — Backlog

Last updated: March 26, 2026

---

## 🏗️ Architecture rebuild (next major milestone)

This is the primary focus for the next development session. A full rebuild of the app architecture from the current single-page step wizard into a proper multi-page SaaS product.

### Auth
- [ ] Replace current cookie-based password with NextAuth.js username + password
- [ ] Add login/logout flow
- [ ] Design for future multi-user support (single user for now, but architected to scale)
- [ ] Design for future OAuth options (Google, potentially ESPN SSO)

### Navigation + layout
- [ ] Persistent sidebar or top nav replacing the current step wizard
- [ ] Next.js page routing: `/dashboard`, `/my-team`, `/free-agents`, `/recommendations`
- [ ] Responsive layout that works on mobile

### Dashboard page (`/dashboard`)
- [ ] "This week at a glance" component — projected starts vs. weekly limit
- [ ] Designed as a tile/component system so new features can be added over time
- [ ] Quick links to My Team and Free Agents

### My Team page (`/my-team`)
- [ ] Matchup period dropdown (replaces hardcoded current week) — selecting a matchup reruns all API calls
- [ ] "Refresh" button to re-fetch probable pitchers and projections on demand
- [ ] Schedule grid table (see table design below)
- [ ] Projected starts vs. weekly limit display
- [ ] Starts limit editable inline

### Free Agents page (`/free-agents`)
- [ ] Same schedule grid table as My Team
- [ ] Filter by ownership %, position, starts this week
- [ ] Checkboxes for selecting players to consider for adds

### Recommendations page (`/recommendations`)
- [ ] Location TBD — evaluate after new layout is built
- [ ] Claude AI analysis using schedule grid + projected FPTS data
- [ ] Add/drop/hold recommendations with day-by-day action plan

---

## 📊 Schedule grid table design

Replaces the current simple roster table. Target design:

| Pitcher | Team | Slot | Mar 26 | Mar 27 | Mar 28 | ... | Expected Starts | Proj FPTS |
|---|---|---|---|---|---|---|---|---|
| Garrett Crochet | BOS | SP | @CIN · PP · 18.5 | -- | CIN · PP · 22.0 | ... | 2 | 40.5 |

**Cell logic:**
- If pitcher is probable starter (PP) that day: show `OPP · PP · XX.X pts` (home = `CIN`, away = `@CIN`)
- If pitcher's team plays but they're not PP: show `vs OPP` with no projection
- If no game that day: show `--`

**Column behavior:**
- Columns are dynamic based on matchup length (7 days standard, up to 12+ for extended weeks)
- Sort: SP first → RP → IL, then Expected Starts desc, then Proj FPTS desc
- IL players show 0 starts, grayed out

---

## ⚾ Data layer rebuild

### Probable pitcher integration (highest priority)
- [ ] Replace current fallback-based starts count with MLB Stats API
- [ ] Endpoint: `statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher`
- [ ] No auth required, public API, updates within 1-2 hours of announcements
- [ ] Call for each day in the matchup period
- [ ] Match returned pitcher names to rostered players
- [ ] "Expected Starts" = count of days player appears as probable pitcher

### Matchup period dates
- [ ] Fix `weekStart` / `weekEnd` returning empty from ESPN API
- [ ] Populate matchup dropdown with all periods for the season
- [ ] Store selected matchup period in state, re-fetch on change

### Projected FPTS model — Option B (v1, ship now)
- [ ] Use MLB Stats API for pitcher season stats (ERA, WHIP, K/9, avg IP/start)
- [ ] Apply ESPN standard scoring formula:
  - 3 pts/IP, 1 pt/K, -1 pt/H, -1 pt/BB, -2 pts/ER, +2 win, -2 loss
- [ ] Adjust for opponent quality (team wRC+ or OPS allowed)
- [ ] Adjust for park factor (publicly available)
- [ ] Per-start projection, summed across probable starts for weekly total
- [ ] Label clearly as "projected" not guaranteed

### Projected FPTS model — Option C (v2, upgrade after ~6 weeks of season data)
- [ ] Replace Option B inputs with Statcast metrics from Baseball Savant
- [ ] Key inputs: xFIP, SIERA, xERA, SwStr%, CSW%
- [ ] Opponent splits: xwOBA vs pitcher handedness
- [ ] Days rest adjustment
- [ ] Validate against real outcomes before deploying
- [ ] Target: 15-25% lower projection error vs Option B
- [ ] Note: only becomes meaningfully better after ~50 innings of season data (mid-May)

---

## 🐛 Known bugs (current version)

- [ ] Dates in header still showing Mar 23–Mar 29 (should reflect actual matchup period)
- [ ] `weekStart` / `weekEnd` returning empty from ESPN API — `matchupPeriodDates` not found in response
- [ ] Starts still showing fallback value of 2 for all pitchers — `filterStatsForCurrentSeasonScoringPeriodId` not returning per-week projected stats
- [ ] IL players (Merrill Kelly, David Peterson) showing 2 starts and non-zero FPTS
- [ ] Free agents `projFpts` showing 0 for all players
- [ ] Team name returning empty string from ESPN API
- [ ] `appliedStatTotal` is season-long projection, not weekly — not meaningful for weekly planning

---

## ✅ Completed

- [x] Password protection (NextAuth-style cookie middleware)
- [x] ESPN API connection (private league via espn_s2 + SWID cookies)
- [x] Roster pulls with real player names
- [x] Team abbreviations (PRO_TEAM_MAP)
- [x] Slot labels: SP, RP, IL
- [x] IL badge red, RP badge amber, SP badge blue
- [x] Status: Active (green), IL (red)
- [x] Proj FPTS 1 decimal place
- [x] Sort order: SP → RP → IL, then starts desc, then FPTS desc
- [x] Team ID and starts limit pre-populate from env vars (`ESPN_TEAM_ID`, `ESPN_STARTS_LIMIT`)
- [x] `/api/config` endpoint for page-load pre-population
- [x] Next.js upgraded to 15.3.6 (CVE-2025-66478 patched)
- [x] Branch/PR workflow established
- [x] Vercel deployment stable

---

## 🛠️ Local dev setup (do before next session)

- [ ] Install VS Code
- [ ] Install Git for Windows
- [ ] Install GitHub CLI (`gh`)
- [ ] Install Node.js LTS
- [ ] Install Python 3.12
- [ ] Install Vercel CLI: `npm i -g vercel`
- [ ] Clone repo: `gh repo clone stateline0/the-skipper`
- [ ] Run `npm install`
- [ ] Run `pip install -r requirements.txt`
- [ ] Create `.env.local` with all credentials
- [ ] Run `vercel dev` — confirm app loads at localhost:3000
- [ ] Install VS Code extensions: Python, Pylance, ESLint, Prettier, GitLens, Thunder Client

---

## 💡 Future ideas (not yet scoped)

- Hitter optimizer (lineup optimization beyond just SP)
- Trade analyzer
- Waiver wire priority ranking beyond just SPs
- Push notifications when probable pitchers change
- Historical accuracy tracking of our projection model vs actual outcomes
- Multi-user support / league sharing
- Mobile app (React Native)
