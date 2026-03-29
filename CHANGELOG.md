# The Skipper — Changelog

---

## Session 4 — March 28, 2026 (evening)

Schedule grid, roster fixes, and backend refactor. One PR shipped.

### Key learnings this session
- ESPN's `scoringPeriodId` is a daily counter (day 1 of season = 1, day 2 = 2, etc.) — not the matchup period number. Passing the matchup period number was returning stale rosters from early in the season. Removing it entirely lets ESPN default to today's live roster.
- ESPN Scoreboard API uses `CHW` for the White Sox; our PRO_TEAM_MAP uses `CWS`. An abbreviation normalization map is required to bridge the two systems. Other potential mismatches (KCR, TBR, SDP, SFG, WSN) added preemptively.
- Last-name-only pitcher matching is fragile for common surnames like "Smith" — full name or player ID matching will be needed for a robust fix.
- `espn.py` was duplicating the MLB Stats API call that `mlb.py` already handles better. Importing `get_starts_for_players` from `mlb.py` eliminates the duplication and keeps probable pitcher logic in one place.
- sessionStorage cache shape needs a version check — old cached data missing new fields (like `matchupDates`) causes silent failures on page load. Auto-fetching when key fields are missing is the right defensive pattern.

### PR #21 — Schedule grid
Replaced simple roster table with a full day-by-day schedule grid on both My Team and Free Agents.
- `components/ScheduleGrid.tsx` — new shared component, used by both pages
- Day columns inserted between Slot and Starts, dynamic length based on matchup period
- ✅ for MLB-confirmed starts, blue P badge for ESPN-projected starts, ✓ for past confirmed starts
- Non-start game days show `vs OPP` / `@OPP` in gray; no-game days show `—`
- Today's column: bold header, green underline, highlighted background + "TODAY" label
- IL players grayed out at 50% opacity
- `mlb.py` `fetch_espn_probables` expanded to return full game schedule (all teams, all days) alongside probable pitchers — no additional API calls required
- `espn.py` refactored to import from `mlb.py` via `get_starts_for_players` — eliminates duplicate MLB Stats API block
- `schedule` and `matchupDates` added to ESPN API response and persisted in sessionStorage
- Stale cache auto-refresh: if cached data missing `matchupDates`, auto-fetch instead of rendering empty grid
- Abbreviation normalization map added to `mlb.py` (CHW→CWS and other ESPN Scoreboard variants)
- Fix: removed `scoringPeriodId` from roster fetch — was pinning roster to day 1 of season
- Fix: IL classification now uses lineup slot only, not `injuryStatus` field

---

## Session 3 — March 28, 2026

Probable pitcher data integration, matchup period dropdown, roster data fixes, and ESPN team map rebuild. Two PRs shipped.

### Key learnings this session
- ESPN Scoreboard API (`site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD`) is public, no auth required, and returns probable starters up to 7 days out — far better than FantasyPros or FanGraphs which are JS-rendered and can't be scraped server-side
- MLB Stats API only confirms probables 1-2 days out but is the authoritative "confirmed" source
- ESPN's `proTeamId` mapping completely changed in 2026 — the old map was ~2019 era. Full verified 2026 map now in memory and code
- ESPN's fantasy API caches roster data server-side for several hours after transactions — cache-busting query params don't help
- Squash-merged PRs in GitHub cause git to think local branches are "not fully merged" — use `git branch -D` to force delete
- FantasyPros probables: JS-rendered, returns HTML shell with no data — dead end for server-side scraping
- FanGraphs probables: also JS-rendered client-side, even with paid account — dead end

### PR #18 — ESPN Scoreboard API probable pitcher integration
Replaced hardcoded `starts = 2` fallback with real probable pitcher data from two merged sources.
- `api/mlb.py` — new standalone endpoint at `/api/mlb?period=N`
- MLB Stats API provides confirmed probables 1-2 days out (`confirmed: true`)
- ESPN Scoreboard API provides projected starters up to 7 days out (`confirmed: false`)
- Each start carries a per-date `confirmed` boolean for future frontend indicators
- Fallback is 0 starts when pitcher has no data in either source (was hardcoded 2)
- `api/espn.py` updated to use real starts data for roster SPs and free agents
- Brought forward 3 unmerged commits from `feature/mlb-stats-api` via cherry-pick
- Fixed `jr.`/`sr.`/`ii`/`iii` suffix bug — `"Fernando Tatis Jr."` was producing key `"jr."` instead of `"tatis"`

### PR #19 — BACKLOG and CHANGELOG docs update
Session 2 documentation committed.

### PR #20 — Matchup period dropdown + roster data fixes
- Matchup period dropdown added to My Team and Free Agents pages
- `api/config.py` updated to return full 22-period matchup table to frontend
- Period selection persists in sessionStorage across page navigations
- Starts limit updates automatically when period changes
- Removed `starts = 2` and `Math.random()` fallbacks from frontend
- Removed Status column from My Team roster table
- My Team now auto-fetches on first visit if no cached data exists
- Complete ESPN PRO_TEAM_MAP rebuild — all 32 IDs verified via live ESPN API player lookups
- `get_pro_team_map()` helper added to `espn.py` with dynamic fetch + hardcoded fallback
- Main branch protection enabled on GitHub

---

## Session 2 — March 28, 2026 (earlier)

Probable pitcher integration via dual-source API merge. One PR shipped.

### PR #18 — ESPN Scoreboard API probable pitcher integration
Replaced hardcoded `starts = 2` fallback with real probable pitcher data sourced from two APIs, merged with a confidence tier system.
- `api/mlb.py` — new standalone endpoint at `/api/mlb?period=N`
- MLB Stats API (`statsapi.mlb.com`) provides confirmed probables 1-2 days out (`confirmed: true`)
- ESPN Scoreboard API (`site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard`) provides projected starters up to 7 days out (`confirmed: false`)
- Each start carries a per-date `confirmed` boolean for future frontend confidence indicators (✅ confirmed, 🕐 projected)
- Fallback is now 0 starts when pitcher has no data in either source (was hardcoded 2)
- `api/espn.py` updated to use real starts data for both roster SPs and free agents
- Brought forward 3 unmerged commits from `feature/mlb-stats-api` branch via cherry-pick
- FantasyPros scraping attempted and abandoned — JS-rendered page, data not accessible server-side
- Main branch protection ruleset created on GitHub

---

## Session 1 — March 27, 2026

Full architecture rebuild from single-page step wizard to multi-page SaaS product. Four PRs shipped and deployed to production.

### PR #14 — NextAuth credentials login
Replaced hand-rolled cookie auth with NextAuth.js.
- `lib/auth.ts` — NextAuth config with credentials provider
- `pages/api/auth/[...nextauth].ts` — catch-all NextAuth route
- `pages/_app.tsx` — wrapped app in `SessionProvider`
- `pages/login.tsx` — rebuilt to use `signIn()` / `signOut()`
- `middleware.ts` — swapped cookie check for NextAuth `withAuth`
- `pages/api/auth.ts` — deleted (replaced by NextAuth)
- `.gitignore` — fixed to properly exclude `node_modules` and `.next`
- Next.js upgraded from 15.3.6 → 15.5.14 (patched multiple CVEs)
- Added `APP_USERNAME`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL` to env vars

### PR #15 — Sidebar layout + multi-page routing
Replaced step wizard with persistent sidebar and four real Next.js pages.
- `components/Layout.tsx` — sidebar + top header, logout button
- `pages/dashboard.tsx` — ESPN connect screen + "How it works"
- `pages/my-team.tsx` — roster table, metrics, refresh button, starts editor
- `pages/free-agents.tsx` — FA table with SP filter and checkboxes
- `pages/recommendations.tsx` — Claude analysis output with add/drop/watch sections
- `pages/index.tsx` — now redirects to `/dashboard`
- `pages/_app.tsx` — wraps all pages in Layout (login page excluded)
- Data persists across pages via `sessionStorage`
- Empty states on each page when no data loaded

### PR #16 — ESPN API bug fixes
Fixed three data bugs in `api/espn.py`.
- Team name fixed — was using `location + nickname` (both empty), now uses `name` field
- Free agents fixed — corrected data structure parsing (`playerPoolEntry` vs direct), added SP-only filter (slot 14), increased limit to 100
- Injury status labels cleaned up — `SIXTY_DAY_DL` → `IL60`, `FIFTEEN_DAY_DL` → `IL15`, `DAY_TO_DAY` → `DTD`
- IL players correctly show 0 starts and 0 projFpts (was already working, confirmed)

### PR #17 — MLB Stats API probable pitcher integration
Replaced hardcoded `starts = 2` fallback with real probable pitcher data from MLB Stats API.
- `api/mlb.py` — new endpoint, fetches probable pitchers for any matchup period via `statsapi.mlb.com`
- All 22 regular season matchup periods hardcoded with exact dates and starts limits
- `weekStart` / `weekEnd` now derived from matchup period table — no longer empty
- Probable pitcher name matching applied to both roster SPs and free agent SPs
- Conservative fallback of 1 start when pitcher not yet announced (vs old hardcoded 2)
- Discovered: MLB Stats API only confirms probables 1-2 days in advance — secondary source needed for days 3-10 (resolved in session 3 via ESPN Scoreboard API)

---

## Pre-session baseline (before March 27, 2026)

Initial working prototype. Single-page step wizard architecture.

- ESPN API connection via `espn_s2` + `SWID` cookies
- Roster pulls with real player names, team abbreviations, slot labels
- Hand-rolled cookie-based password protection
- Claude AI analysis via Anthropic API (`/api/analyze.py`)
- Sort order: SP → RP → IL, then starts desc, then FPTS desc
- IL/RP/SP badge colors, Active/IL status badges
- Team ID and starts limit pre-populated from env vars
- Next.js upgraded to 15.3.6 (CVE-2025-66478 patched)
- Vercel deployment stable at `https://the-skipper-iota.vercel.app`
- Branch/PR workflow established
