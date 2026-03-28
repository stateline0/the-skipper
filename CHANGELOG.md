# The Skipper — Changelog

---

## Session 2 — March 28, 2026

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
- All 22 regular season matchup periods hardcoded with exact dates and starts limits (sourced from ESPN league schedule)
- `weekStart` / `weekEnd` now derived from matchup period table — no longer empty
- Probable pitcher name matching applied to both roster SPs and free agent SPs
- Conservative fallback of 1 start when pitcher not yet announced (vs old hardcoded 2)
- Discovered: MLB Stats API only confirms probables 1-2 days in advance — secondary source needed for days 3-10 (resolved in session 2 via ESPN Scoreboard API)

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
