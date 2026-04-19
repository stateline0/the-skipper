# The Skipper — Changelog

---

## Session 22 — April 18, 2026

Executed the two PRs designed at the end of session 21 (ESPN projection locking + accuracy dashboard head-to-head) plus a security chore patching a `.gitignore` gap that surfaced during debugging. Three PRs shipped in one session: PR #97 (cron locks ESPN Forecaster), PR #98 (`.gitignore` tightened for Vercel env dumps), PR #99 (ESPN MAE head-to-head on accuracy dashboard). All three verified in production; the head-to-head comparison will populate with real numbers tomorrow once the next cron writes `actual-all:2026-04-18`.

### Key learnings this session
- **Vercel "Sensitive" environment variables are write-only.** When `CRON_SECRET` was tagged Sensitive in the dashboard, neither the dashboard UI nor `vercel env pull --environment=production` would return its value — the pull emitted `CRON_SECRET=""` with no warning. Spent a chunk of time debugging a 401 Unauthorized that was really a mismatched secret between local and production. Rotation via `openssl rand -hex 32`, saved to `.env.local` **and** updated in the Vercel dashboard **and** redeployed is the only path back. Worth flagging in KNOWLEDGE.md — the "Sensitive" toggle is not obvious and the failure mode is silent.
- **`vercel env pull` writes an untracked secret file into the working tree** with whatever environment's values you pulled. Our `.gitignore` only covered `.env*.local`, so `.env.vercel.prod` sat there one `git add -A` away from getting committed. PR #98 fixes this with an explicit `.env.vercel*` pattern. Never use `git add -A`; always name files explicitly — but belt-and-suspenders on the `.gitignore` is still cheap insurance.
- **Name normalization must be consistent on both sides of a reconciliation join.** ESPN Forecaster capitalizes accented pitchers ("Eury Pérez") while MLB Stats API preserves case ("eury pérez" after lowercasing). Naïve lowercase comparison hits but also silently misses on any variant. Pattern that works: `strip_accents(name.lower())` on both sides before comparing. Our `strip_accents()` helper in `api/fetcher.py` does NFD-normalize + combining-mark strip, which is the right primitive. Then use the original MLB-keyed name when building downstream slugs so everything aligns with existing `proj2all:` keys.
- **Apples-to-apples MAE requires recomputing Skipper's MAE on the intersection subset.** Comparing full Skipper MAE (all 29 starts) against ESPN MAE (only the starts ESPN also covered, say 25) is misleading — you're comparing different denominators. PR C's `skipperMaeOnIntersection` computes Skipper's MAE on only the overlap set, so the head-to-head comparison is valid. Small but important — easy to ship the wrong version by default.
- **SETNX + date-filter is the right lock shape for speculative data.** Conner's concern on PR B was valid on its face: locking a 10-day-out ESPN projection would be premature because those values drift before game day. The mitigation lives in the ingestion filter — only the `date == today` entries get locked, so we never store a value that hasn't fully "baked" in the source. SETNX then guarantees same-day idempotency without ever overwriting. Two separate concerns (stale input vs. concurrent writes) handled by two separate mechanisms.
- **Ship backend + frontend in the same PR when the data contract is new.** PR C's backend adds `espnSummary` to the response and the frontend consumes it immediately. Splitting into two PRs (backend first, then frontend) would have meant landing a payload field that nothing reads and deploying an unused API shape. Tight coupling here is a feature, not a smell.

### PR B — Daily cron locks ESPN Forecaster projections to KV (PR #97)
- `lock_espn_projections()` added to `api/cron.py`:
  1. Fetch today's MLB-confirmed probables via `fetch_mlb_probables(today, today)`.
  2. Build `confirmed_lookup: {accent_stripped_name → original_mlb_key}` keyed on the names where `today_str in dates`.
  3. Fetch `fetch_forecaster()`, filter to entries where `date == today_str` and `is_placeholder == False`.
  4. For each surviving entry, `strip_accents(entry["pitcher"])` and look up in `confirmed_lookup`. Misses → `skipped_unconfirmed += 1`. Hits → build slug from the *MLB* key (so it aligns with `proj2all:` slugs) and SETNX-write `projection-espn:{year}:{period}:{slug}:{date}` with 60-day TTL.
- Value shape: `{fpts, team, opp, opp_is_home, throws, player_id, is_placeholder: false, locked_at}`.
- Handler updated to call MLB and ESPN locking in independent `try/except` blocks; returns `{ok: mlb.ok AND espn.ok, mlb: {...}, espn: {...}}` so a partial failure is visible.
- Production verification: first run `locked_new: 29, skipped_unconfirmed: 1, skipped_placeholder: 0`. Second run (idempotency) `locked_new: 0, locked_skipped_existing: 29`. Confirmed accent handling end-to-end — Eury Pérez correctly matched.
- `ESPN_LOCK_TTL_SECONDS = 60 * 86400` constant added alongside existing `PROJ_LOCK_TTL_SECONDS`.

### `.gitignore` tightening (PR #98)
- Added `.env.vercel*` to the environment-files block so `vercel env pull --environment=<env>` outputs (e.g. `.env.vercel.prod`) are excluded by default.
- Existing `.env*.local` pattern stays — covers the standard local dev file.
- Trigger: `.env.vercel.prod` appeared in `git status` during CRON_SECRET debugging. No harm done (nothing was committed), but one `git add -A` away from leaking a production secret dump into history. Cheap insurance.

### PR C — Accuracy dashboard ESPN MAE head-to-head (PR #99)
- `api/accuracy.py` (+61 lines): when `scope == "all"`, after the existing match loop:
  - `_redis.keys("projection-espn:{season}:{period}:*")` → `{slug:date → fpts}` lookup, skipping placeholders.
  - For each matched start, attach `espnFpts` and `espnError = round(espnFpts - actualFpts, 1)` when an ESPN projection exists at the same slug+date.
  - Build `intersection: [starts_with_both_proj_and_actual_and_espn]`.
  - Compute `espnSummary: {totalStarts, mae, skipperMaeOnIntersection, espnKeysFound}` — ESPN's MAE plus Skipper's MAE **re-computed on the same intersection subset** for an apples-to-apples comparison. When intersection is empty, still returns `espnSummary` with `mae: null` and `espnKeysFound` populated so the frontend can render an informative empty state.
  - Returned at top level under `espnSummary` key.
- `pages/accuracy.tsx` (+92 lines):
  - New `EspnHeadToHead` component renders when `scope === 'all'` and `espnSummary` is present. Three tiles (Skipper MAE, ESPN MAE, Advantage) above the existing summary tiles. Winning side highlighted soft-green; ties show "— tied"; no-overlap state shows contextual copy with ESPN lock count.
  - New `HeadToHeadTile` sub-component for the three tiles — same visual language as existing `SummaryTile` but with highlight + color props.
  - Optional `ESPN` column added to the starts table between `Proj` and `Actual` when `scope === 'all'`. Renders `espnFpts` or em-dash when no ESPN projection existed for that start.
  - Expanded-row `colSpan` adjusted dynamically: 7 when scope is All MLB (ESPN column present), 6 otherwise.
  - Interface additions: `StartComparison.espnFpts?/espnError?`, new `EspnSummary`, `AccuracyData.espnSummary?`.
- Deploy verification: Roster scope rendered unchanged (empty state for period 3 historical reasons — expected). All MLB scope currently shows the existing empty state because no `actual-all:2026-04-18` keys exist yet (today's games in flight). Tomorrow morning after the 17:00 UTC cron writes today's actuals, the head-to-head block will populate with real numbers.
- Two small UX gaps flagged to BACKLOG:
  - Backend early-return (`if not proj_keys`) bypasses ESPN computation — should still surface `espnSummary` when Skipper has no `proj2all:` keys.
  - Frontend empty-state branch (`starts.length === 0`) never renders the ESPN block — should pass `espnSummary` through so ESPN locks surface before the first overlap exists.

### CRON_SECRET rotation (no PR — ops)
- Generated new 32-byte hex secret with `openssl rand -hex 32`.
- Updated `.env.local` and Vercel dashboard (production, preview, development — all three scopes).
- Redeployed with `vercel --prod` to pick up new env value. Verified `curl -H "Authorization: Bearer $CRON_SECRET" /api/cron` returned a valid lock summary.
- Root cause: Vercel marks env vars as "Sensitive" by default on some UIs, making their values write-only. `vercel env pull` silently pulled an empty string instead of erroring.

---

## Session 21 — April 18, 2026

Spike confirmed ESPN's Fantasy API does not publish per-day FPTS projections under any filter shape, so we pivoted to scraping the public Forecaster article. Shipped the scraper + diagnostic endpoint, a Washington-team-abbreviation normalization fix, and a middleware change that exempts public read-only / cron / auth API routes so Vercel Cron and plain-curl verification stop getting 307'd to `/login`. Four PRs shipped (#92–#95) plus four spike iterations (#88–#91) that closed out the Fantasy API investigation. PR B (daily cron locking ESPN projections to KV) and PR C (accuracy dashboard ESPN MAE column) are designed and queued for the next session.

### Key learnings this session
- ESPN's Fantasy API `kona_player_info` view only ever returns **full-season** projections under `statSourceId: 1` — `statSplitTypeId: 0` with `scoringPeriodId: 0`. No combination of `filterStatsForSourceIds`, `filterStatsForSplitTypeIds`, `filterStatsForTopScoringPeriodIds`, or `filterStatsForCurrentSeason` surfaces per-day projections. KNOWLEDGE.md's March 2026 warning that the API "returns empty/zero early in season" was actually understating it — the per-day data simply doesn't exist there. Four spike iterations to prove this definitively, which is the right bar before building on a shaky foundation.
- The Forecaster article (id=31165100) is **server-rendered HTML**, not JS-hydrated — one `<table class="inline-table">`, 30 team rows interleaved with spacers, each `<td>` holding 10 `<br>`-delimited per-date values. Pitcher `<a>` hrefs carry the same numeric IDs as the Fantasy API (`/mlb/player/_/id/{id}/…`). Ship a probe endpoint first to confirm the render model before writing a scraper — 2 minutes of work that de-risks the whole approach.
- `<br>`-delimiter splitting via `cell.get_text(separator="|")` is unreliable for ESPN markup because some cells wrap content in `<div>` or `<span>` — descendants vs direct children matters. The pattern that works: find the deepest single-element container holding the `<br>` tags, walk its *direct* children, and accumulate text into buckets that reset on each `<br>`. OFF days become empty strings by construction, which keeps the date-column index aligned.
- Placeholder detection needs **exact equality** (`fpts == 1.0`), not a threshold (`fpts <= 1.0`). Coors Field pitchers legitimately project negative for bad matchups (observed: -3.2 FPTS), and a threshold check silently mislabels those as placeholders. Worth a one-line code comment so the next person doesn't "fix" it.
- ESPN is internally inconsistent on team abbreviations: the Forecaster logo filename for Washington is `was.png`, but the opp column, scoreboard API, roster API, and everywhere else use `WSH`. Downstream joins (e.g. reconciliation against MLB Stats API confirmed probables keyed by abbrev) silently drop rows when the abbrev doesn't match. Catch and normalize at ingestion time, not at join time.
- `vercel.app` domain namespace is global and first-come — `the-skipper.vercel.app` was squatted by another project (a wedding site, of all things). Project deployments land at a random-hash URL unless you attach a custom domain; the auto-assigned "Greek-letter" production URL (in our case `the-skipper-iota.vercel.app`) does count as a custom domain and bypasses Standard Protection for the Vercel SSO gate. `vercel ls` + `vercel project` are the canonical way to find the real production URL.
- Vercel's "Standard Protection" vs "All Deployments" dropdown does NOT control what I assumed: "Standard Protection" on Hobby still gates all auto-generated preview URLs, but exempts domains you've attached via **Domains** settings. Attaching any `*.vercel.app` subdomain (free) or custom domain makes that URL publicly reachable while preview hashes stay gated. Preferable to disabling protection wholesale.
- The 307 redirect we were chasing wasn't Vercel's SSO gate — it was **our own Next.js middleware** (`middleware.ts` using `next-auth/middleware`'s `withAuth`) with a matcher that covered literally every non-static route including `/api/*`. The SSO bypass worked fine; the app's own auth was the real gate. When debugging "I can't hit my API from curl," always check the app's own middleware before chasing the platform layer.
- NextAuth matcher pattern: `'/((?!_next/static|_next/image|favicon.ico|api/auth|api/cron|api/forecaster|…).*)'` — a single negative-lookahead listing prefix exemptions. Easy to forget new public routes as the app grows, so the commit message spelled out what's exempt and why.
- `zsh` history-expansion eats `!` in one-liners — `(?!...)` in a `node -e "…"` command breaks with `event not found`. Fix: heredoc into a temp file with single-quoted `'EOF'` so the shell passes characters through untouched, or `setopt no_banghist` for the session.

### ESPN per-day projection spike closeout (PRs #88–#91)
- **PR #88** (initial probe): roster + kona_player_info fetch with no filter. Confirmed `stats[]` arrays empty in response — couldn't tell if API was restricting or if data didn't exist.
- **PR #89** (unconditional sample dump): removed the "skip if stats[] empty" guard so diagnostic output showed the response shape even when no projections were returned. Confirmed stats[] was empty in all responses.
- **PR #90** (filter back-off): tried aggressive `filterStatsForSourceIds` + `filterStatsForSplitTypeIds` + `filterStatsForTopScoringPeriodIds` + `filterStatsForCurrentSeason` combination → HTTP 400. Backed off to minimal filter shape.
- **PR #91** (final minimal + source IDs): minimal filter `{filterIds, filterStatsForSourceIds: [0, 1]}`, no `scoringPeriodId` restriction. Response now contained `statSourceId: 1` entries — but all with `statSplitTypeId: 0` and `scoringPeriodId: 0` (full-season projections). Definitively confirmed no per-day data exists in the Fantasy API.

### Forecaster probe (PR #92)
- `api/forecaster_probe.py` — stdlib-only diagnostic (regex + http.server), reports http_status, tag_counts, hydration_markers, pitcher_name_presence, and returns a 3KB sample of HTML starting at the first `<table>` tag
- Output confirmed: 1 `<table>`, 60 `<tr>`, no `__NEXT_DATA__` / `__INITIAL_STATE__` / `__APOLLO_STATE__`, no `loading...` indicators, and all 5 sample rostered pitcher names present in the HTML → safe to parse with DOM scraping

### Forecaster scraper module (PR #93)
- `api/forecaster.py` (~290 lines) — `fetch_forecaster()` HTTP client + `parse_forecaster_html(html, year)` pure parser + `handler` diagnostic endpoint
- `_split_br(cell)` walks the deepest single-child container with `<br>` tags, accumulates direct-child text into buckets, handles OFF days as empty strings to keep per-date indexing aligned
- `_split_pitcher_cell(cell)` returns `(name, player_id)` tuples — pulls numeric IDs from `<a href="/mlb/player/_/id/{id}/…">`
- `_team_from_logo(img_src)` parses `/mlb/500/ari.png` → `"ARI"` via regex + `LOGO_TO_TEAM_OVERRIDES` normalization
- `PLACEHOLDER_FPTS_VALUE = 1.0` with inline comment explaining why exact equality (not threshold) is required — COL negative projections must not be flagged
- Output entry shape: `{date, team, opp, opp_is_home, player_id, pitcher, throws, fpts, is_placeholder}`
- Production verification: 260 entries across all 30 teams, 10-day rolling window, rostered pitchers captured correctly, Coors negative FPTS correctly **not** flagged as placeholders
- `beautifulsoup4==4.12.3` added to `requirements.txt`

### Washington team abbreviation fix (PR #94)
- ESPN Forecaster uses logo filename `was.png` for Washington, but opp column, scoreboard API, and roster API all use `WSH`. Without normalization, Washington-originated rows would show `team: "WAS"` while other teams' rows show `opp: "WSH"` — PR B's reconciliation join against MLB-confirmed probables (keyed by abbreviation) would silently drop every Washington start.
- Added `"was": "WSH"` to `LOGO_TO_TEAM_OVERRIDES` alongside the existing `"wsh": "WSH"` entry so both slug variants normalize to the same canonical abbreviation.
- Verified in production: `"WSH"` present in both `team` and `opp` sets in `/api/forecaster` output, `"WAS"` absent.

### Middleware exemption for public API routes (PR #95)
- `middleware.ts` matcher previously protected every non-static route: `'/((?!_next/static|_next/image|favicon.ico).*)'`. This meant every anonymous `curl` to `/api/*` got redirected to `/login`, including routes that have no user-specific data and routes that Vercel Cron needs to reach (no session).
- Extended the negative-lookahead to exempt five prefixes:
  - `api/auth/*` — NextAuth's own handler (belt-and-suspenders; `withAuth` probably bypasses internally)
  - `api/cron/*` — Vercel Cron targets; authorized via `CRON_SECRET` header check inside `api/cron.py`
  - `api/forecaster` — public ESPN scrape, no PII
  - `api/forecaster_probe` — diagnostic, no PII
  - `api/espn_proj` — diagnostic, no PII
- User-specific endpoints (`/api/projection`, `/api/accuracy`, `/api/espn` roster, `/api/analyze`, `/api/mlb`, `/api/weather`, `/api/savant`, `/api/config`) stay behind NextAuth unchanged — they're called from the UI which carries a session cookie.
- Verified in production: `curl /api/forecaster` → JSON 200; `curl /api/projection` → 307 to `/login`. Exactly what we wanted.

### Design decisions locked in for PR B (next session)
- Reconciliation source: **MLB Stats API** probable-pitcher feed (`fetch_mlb_probables` already imported in `api/cron.py`). Authoritative "who's actually starting today" — ESPN Forecaster is speculative up to 10 days out.
- KV key shape: **`projection-espn:{year}:{period}:{slug}:{date}`**, matching existing `proj2all:` / `proj2:` patterns so PR C can share key-building helpers.
- Orphan handling: **skip silently.** When ESPN projects pitcher X but MLB confirms pitcher Y, we just don't lock X. Don't persist orphans to a parallel key — if we ever want ESPN miss-rate data we can re-fetch Forecaster history.
- Write semantics: **SETNX** (write-once, never overwrite). 60-day TTL.
- Filter: skip entries with `is_placeholder: true` (exact FPTS == 1.0).
- Hook: extend `api/cron.py` with a new `lock_espn_projections()` function, called from the same handler that runs `lock_all_mlb_projections()`. No new cron schedule.

### Vercel deployment detour worth capturing
- The project's real production URL is `https://the-skipper-iota.vercel.app` — not the squatted `the-skipper.vercel.app`, and not the per-deploy random-hash URLs. The `-iota` Greek-letter suffix is Vercel's auto-assigned production domain and counts as a "custom domain" for Standard Protection exemption purposes.
- Standard Protection on Hobby: exempts attached domains but gates preview hashes. We don't need to disable protection or open the OPTIONS allowlist — just always verify via the `iota` URL.
- If a `curl -i` returns HTML with a `<title>` that isn't your app's title, you're hitting a squatted / wrong domain — check `vercel ls` for the real one before blaming Vercel auth.

---

## Session 20 — April 18, 2026

Projection model improvements: cached team wOBA factors, blended recent team form into opposing-lineup wOBA, and shipped a standalone weather data fetcher (Open-Meteo) with a 3-hour cache and diagnostic endpoint. Three PRs shipped (#83–#85).

### Key learnings this session
- The MLB Stats API supports `stats=byDateRange&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD` on the `teams/stats` endpoint — same response shape as `stats=season`, which made recent-form wOBA drop in cleanly with a shared helper. Single API call for all 30 teams, no per-team loops needed.
- Extracting `_compute_team_woba_factors(splits, min_games, label)` as a pure helper let season / recent / blended paths share code. Parallel fetching via `ThreadPoolExecutor(max_workers=2)` keeps the blended call roughly as fast as a single call.
- NextAuth middleware (`withAuth`) protects every non-static route — any anonymous `curl` against `/api/*` returns a 307 redirect to `/login`. Production endpoint testing has to happen in the browser after login, or via an authenticated fetch. Spent a round-trip forgetting this.
- Open-Meteo is genuinely free and auth-free. Hourly forecasts 16 days out, with a `temperature_unit=fahrenheit` query param and `timezone=auto` to get local hours (picking `T19:00` as the canonical game slot). Graceful fallback to `T13:00` then to the first available hour handles edge cases.
- For a new external dependency like weather data, shipping the fetcher + diagnostic endpoint independently from projection wiring is the safer pattern — you can verify the API works in production before touching a core path. A GET endpoint that returns the raw fetch result is 20 lines and saves one deploy round-trip of debugging later.
- Retractable-roof stadiums are worth treating as domes rather than applying outside weather — the roof state isn't knowable in advance, so shipping a neutral 1.0 factor is strictly better than being sometimes-wrong. Eight parks flagged: TB, TOR, MIL, ARI, HOU, MIA, SEA, TEX.
- The park-factor dampening pattern (50% toward neutral, ±5% cap) ported cleanly to temperature: `raw = 1 + (temp - 70) / 1000` → dampened 50% → clamped to ±5%. Matches the existing Layer 3 formula so the tooltip UX stays consistent when weather is wired in.
- Sandbox git holds file locks that the user's terminal doesn't (`.git/index.lock`, `.git/objects/maintenance.lock`). Rule of thumb: any git command that writes (commit, push, merge) should run in Conner's local terminal, not the sandbox. Sandbox git is read-only in practice.

### Cache team wOBA factors (PR #83)
- Mirrored the PR #77 `team_win_data` caching pattern in `api/fetcher.py`
- `cache:team-woba:{year}` with 24hr TTL — eliminates one MLB Stats API call per request
- Removed now-redundant direct calls in `api/espn.py` and `api/cron.py` — both consumers read `cached["team_woba_factors"]`

### Opposing lineup recent form (PR #84)
- `api/mlb.py`: extracted `_compute_team_woba_factors(splits, min_games, label)` pure helper
- `get_team_woba(season)` refactored to call the helper with `min_games=10, label="season"`
- New `get_team_woba_recent(season, days=14)` — calls `stats=byDateRange` with computed start/end dates, `min_games=3` (lower bar for short window), `label="recent"`
- New `get_team_woba_blended(season, recent_days=14, recent_weight=0.35)`:
  - `ThreadPoolExecutor(max_workers=2)` fetches season + recent in parallel
  - Weighted blend: `0.65 × season + 0.35 × recent` per team
  - Falls back to season-only if recent fetch fails or a team has insufficient recent games
  - Serial fallback path if the executor itself fails
- `api/fetcher.py` switched import from `get_team_woba` to `get_team_woba_blended` — same cache key, blended value now cached
- Consumers already use `.get(abbrev, 1.0)` — safe to return only qualifying teams

### Weather data fetcher (PR #85)
- New `api/weather.py` (315 lines) — Open-Meteo client + factor computation + diagnostic endpoint
- `PARK_COORDS` — home plate lat/lng for all 30 MLB parks (±0.01° accuracy is fine; Open-Meteo resolution is ~1km)
- `DOME_PARKS = {TB, TOR, MIL, ARI, HOU, MIA, SEA, TEX}` — conservative list including retractables (neutral factor beats sometimes-wrong)
- `fetch_weather(lat, lng, date_str)` — hourly forecast via Open-Meteo, picks `T19:00` local, falls back to `T13:00` or first available hour
- `compute_temp_factor(temp_f)`:
  - Baseline: 70°F = 1.0
  - Raw: `1 + (temp_f - 70) / 1000` (~1% per 10°F)
  - Dampened 50% (only H/ER are temp-sensitive)
  - Clamped to ±5%
  - Examples: 40°F → 0.985, 70°F → 1.000, 95°F → 1.0125
- `get_weather_factor(park, date)` orchestrator: dome check → cache lookup → fetch → compute → cache with 3hr TTL under `cache:weather:{park}:{date}`. Unknown parks / API failures return neutral 1.0 with `source: "default"`.
- `BaseHTTPRequestHandler` diagnostic at `/api/weather?park=X&date=Y` — returns the full factor dict for inspection
- Phase 2 (future PR): wire into `get_projected_fpts()` as per-start multiplier, expose in tooltip and v2 locked projections

### Verification
- `cache:team-woba:{year}` populated correctly in Upstash after first production request
- `/api/weather?park=NYY&date=2026-04-18` → 58.2°F, factor 0.9941, source "forecast" ✅
- `/api/weather?park=COL&date=2026-04-18` → 56.4°F, factor 0.9932, source "forecast" ✅
- `/api/weather?park=TB&date=2026-04-18` → factor 1.0, source "dome" ✅
- `/api/weather?park=XYZ&date=2026-04-18` → factor 1.0, source "default" ✅
- Malformed date param (second URL accidentally pasted into date value) → factor 1.0, source "default" — confirmed graceful fallback path

### KNOWLEDGE.md updates included in this PR
- Added Open-Meteo section under external APIs
- MLB Stats API section: added `byDateRange` statsType under team splits
- Projection Model section: updated opponent quality adjustment with blended formula (65/35, 14-day window, fallback chain)
- Upstash KV schema: added `cache:weather:{park}:{date}` (3hr TTL) and noted `cache:team-woba:{year}` now stores the blended factor

### `.gitignore`
- Added `__pycache__/` and `*.pyc` — Python bytecode cache was showing up in `git status` from sandbox Python imports during development. Not a functional issue, but keeps `git status` clean for the next session.

---

## Session 19 — April 16, 2026

Single bug fix that surfaced two related display issues in adjacent code surface. One PR shipped (#81).

### Key learnings this session
- ESPN field naming for IL status is inconsistent across player categories: roster players get `slot === 'IL'` (set explicitly in `get_slot_label()` from the `player.injured` boolean), while free agents get `injuryStatus === 'IL15' | 'IL60'` (mapped via `inj_label_map` from ESPN's `FIFTEEN_DAY_DL` / `SIXTY_DAY_DL` strings). Filters that need to detect IL across both categories must check both fields.
- KNOWLEDGE.md is only useful if you actually consult it before writing code that touches fields it warns about. The `injuryStatus` field on roster players returning empty string is documented at 10/10 confidence — and was still missed when first writing the IL filter. Cost a deploy round-trip to catch.
- The `confirmed` boolean on a start is forward-looking only: it answers "did MLB Stats API list this as a confirmed probable for an upcoming game" not "is this start locked in." Once a game is in the past, the field stops being meaningful and any UI keying off it for past dates is buggy by construction. Display logic should derive `isLockedIn = confirmed || isPast || isToday` rather than mutate `confirmed` server-side.
- Tile aggregations and per-row data are two separate code paths in `pages/my-team.tsx`. Fixing the per-row data (backend) does not automatically fix the tiles (frontend) — they sum from different arrays. When fixing a "missing data" bug, always grep for parallel aggregations.
- A function that operates on a `player_names` parameter but does whole-MLB fetches internally has a subtle performance trap: calling it twice doubles the API load even though only the filtering changes. Caching the heavy fetches by `matchup_period` would make repeat calls free — backlogged for a future session.
- When applying multiple related fixes mid-session, prefer `git commit --amend` over a chain of fix-up commits while the branch is unpushed. Squash-merge collapses them anyway, but a clean single commit is easier to read in `git log` and easier to revert if needed.

### Dropped streamer start counting (PR #81)

**Backend (`api/espn.py`):**
- Pre-filter dropped names to SP-eligible only before doing any work
- Build `dropped_team_map` from `my_team_pitchers_by_day` (mirrors `roster_team_map`)
- Call `get_starts_for_players` for dropped names — same pattern as roster + FAs
- **Intersect each player's `startDates` with their `days_on_team`** — only counts starts that happened while the player was on roster
- Feed intersected start data into `get_projected_fpts` so projection details render in schedule grid tooltip
- Guarded with `if dropped_sp_info:` — zero added latency when no dropped streamers

**Frontend (`pages/my-team.tsx`):**
- Tile aggregation now iterates `[...spRoster, ...dropped]` instead of `spRoster` alone
- Tile filters changed from `s.confirmed` to `s.date <= today || s.confirmed` — past-dated starts always count regardless of original probables source
- Rostered SPs tile excludes `slot === 'IL'` players

**Frontend (`components/ScheduleGrid.tsx`):**
- Past/today indicator now derives `isLockedIn = startInfo.confirmed || isPast || isToday`
- Both the indicator symbol and color key off `isLockedIn` instead of `confirmed`
- Future-game branch unchanged — `confirmed` still correctly distinguishes upcoming MLB-confirmed probables from ESPN scoreboard projections

### Verification

Reynaldo Lopez test case — was on roster April 14 (started vs MIA, +7.0 FPTS), then dropped. After fix:
- Lopez row: Starts 0 → 1, Act FPTS 0.0 → +7.0, Apr 14 indicator blue P → green ✓
- Actual Starts tile: 7 → 8
- Projected Starts tile: 11 → 12 (correctly hits 12/12 weekly limit)
- Rostered SPs tile: 10 → 9 (Pepiot on IL no longer counted)
- Active roster pitchers unchanged

### KNOWLEDGE.md updates needed
- Add note under ESPN Fantasy API → Injury detection: roster players get `slot === 'IL'`, free agents get `injuryStatus === 'IL15' | 'IL60'`. Two different field conventions for the same underlying state.
- Clarify that the `confirmed` boolean on a start is forward-looking — only meaningful for upcoming games. UI logic for past/today dates should not key off it.

---

## Session 18 — April 12, 2026

Major architecture refactor, accuracy dashboard enhancements, Vegas/Pythagorean win probability model, daily cron job, and multiple UI improvements. Five PRs shipped (#73–#77).

### Key learnings this session
- ESPN scoreboard API includes DraftKings moneyline odds inline — zero additional API calls needed.
- American odds → implied probability: negative = |odds|/(|odds|+100), positive = 100/(odds+100). Normalize to remove vig.
- Pythagorean win expectation (RS^1.83 / (RS^1.83 + RA^1.83)) is more predictive than raw W/L record early season.
- Log5 formula converts two teams' win percentages into head-to-head probability.
- Vegas odds only available ~12-24hrs before game time — Pythagorean fills the gap for future games.
- Starting pitchers get the W in only ~57% of team wins. Must multiply team win prob by starter share.
- Pitcher quality adjustment: pitcher xERA vs team ERA, capped 0.7–1.4 to prevent extremes.
- Opponent starter xERA available from ESPN scoreboard probables — already parsed, just needed threading.
- Factor contribution analysis: compute counterfactual "what if we removed this factor" by reverse-engineering locked projections.
- Vercel Hobby plan allows 2 cron jobs, each once per day. Secured with CRON_SECRET env var.
- Pure refactors should be separate PRs from feature work.
- Suspended (SSPD) players may not appear in ESPN mRoster response — needs investigation.

### espn.py refactor (PR #73)
- Split 1220-line monolith into projection.py, fetcher.py, espn.py
- Pure refactor — API response identical

### Factor contribution analysis + refresh (PR #74)
- Accuracy dashboard: counterfactual analysis for wOBA, park, combined, recent form
- Refresh button on accuracy page

### Vegas + Pythagorean win probability (PR #75)
- Three-tier fallback: Vegas → Pythagorean+Log5+pitcher xERA → default 0.5
- Per-start W/L: raw_rate × win_prob × 0.57 starter share
- winProb + wpSource in tooltip and v2 locked projections

### Daily cron for all-MLB tracking (PR #76)
- `/api/cron` endpoint runs daily at noon CT (17:00 UTC)
- Projects FPTS for all ~60 probable MLB starters, locks to `proj2all:` KV keys
- Stores actual FPTS from game logs under `actual-all:` keys
- Accuracy page: My Roster / All MLB scope toggle
- Secured with CRON_SECRET

### UI improvements + caching (PR #77)
- Cache team_win_data with 24hr TTL (eliminates 2 API calls per page load)
- Opponent starter xERA threaded through schedule → projection model
- Schedule grid shows adjusted per-start projection (with wOBA, park, W/L)
- W/L impact shown in projection tooltip
- Compact grid cells: indicator inline with opponent label
- Free Agents: sortable Act FPTS column, date sort uses adjusted projection
- My Team: roster sorted by per-start quality (projFpts/starts)

---

## April 12, 2026 (Session 2)

### Midnight dark theme + font refresh (PR #71)
- Complete visual redesign: light sage theme → dark premium "Midnight" palette
- Deep charcoal base (#0F1114), cool gray surfaces (#161920, #1E2128), teal accent (#2EC4A0)
- Replaced Syne font with Inter (body/headings) for clean, professional legibility
- Replaced IBM Plex Mono with JetBrains Mono (data/labels)
- Fixed projection tooltip: hardcoded dark surface so it's always readable
- Fixed dashboard cookie instructions box: replaced hardcoded yellow with theme-aware variables
- Fixed all primary button text contrast across 4 pages
- Fixed accuracy page dropdown readability
- All colors defined as CSS variables — entire theme changed via one file (globals.css)

### Key learnings this session
- Semantic CSS variable naming (--ink = text, --paper = background) enables full theme swaps by changing only variable values — every component automatically updates
- Tooltips and other "floating" UI elements should use hardcoded colors, not theme variables, since they need to look consistent regardless of theme
- `var(--white)` as a variable name becomes misleading in a dark theme (it's actually dark gray) — but renaming would touch every file, so the tradeoff is to keep the name and document the semantic meaning
- Button text on colored backgrounds (green, teal) needs hardcoded dark color, not `var(--white)`, in dark themes
- `git commit --amend --no-edit` adds changes to the previous commit without creating a new one — keeps PRs clean
- Google Fonts @import in sandboxed iframes may not load — use standalone HTML files for reliable font previews

---

## Session 16 - April 12, 2026

### Mobile-responsive layout (PR #69)
- Sidebar collapses on mobile (768px and below), hidden by default
- Hamburger button (☰/✕) in header toggles sidebar open/closed
- Dark overlay behind sidebar when open — tapping outside closes it
- Nav link clicks auto-close the sidebar after navigating
- Reduced content padding on mobile for more breathing room
- iPad portrait gets mobile layout, iPad landscape gets full desktop layout
- Moved layout-structural styles from inline React to globals.css to enable @media queries

### Key learnings this session
- React inline `style={}` props cannot use `@media` queries — responsive breakpoints require real CSS (in a .css file or CSS-in-JS library)
- 768px is the standard mobile breakpoint — iPad portrait hits this exactly, iPad landscape (1024px) gets desktop layout
- `position: fixed` with `left: -260px` / `left: 0` + `transition` is the standard pattern for slide-in mobile sidebars
- Keep visual/branding changes (color scheme) in separate PRs from structural/layout changes for cleaner review and easier rollback

---

## Session 15 — April 12, 2026

ESPN stat ID verification, actual per-stat storage, accuracy tracking dashboard. Three PRs shipped (#66–#68).

### Key learnings this session
- ESPN per-game stat IDs for W/L are 53/54 (per-game), NOT 32/33 (which are season cumulative totals). Verified by cross-referencing two pitchers with opposite W/L outcomes.
- ESPN condensed box score doesn't show HBP column — must check detailed pitching notes or play-by-play. Both Joe Ryan and Kyle Harrison had 1 HBP that was invisible in the condensed view but confirmed by the formula check.
- When verifying stat ID mappings, always use two pitchers with different values for ambiguous stats (e.g., H=4 vs ER=2 for Harrison definitively distinguished stat 37 from stat 45).
- `actual_stats` in daily cache only contains league-rostered players — free agents don't appear in `mRoster` view. Known ESPN API limitation.
- Adding `actual_stats` to daily cache doesn't break old cached days — they simply don't have the field, and code handles the absence gracefully.

### Verified ESPN stat ID mapping (PR #66)
- Corrected W/L from stat 32/33 to stat 53/54
- Verified all 9 scoring stats against two box scores:
  - Joe Ryan (W, 7IP/2H/2ER/1BB/1HBP/5K) = 23.0 FPTS ✅
  - Kyle Harrison (L, 4.1IP/4H/2ER/1BB/1HBP/1K) = -1.0 FPTS ✅
- `ESPN_PITCHING_STAT_IDS` constant added to `espn.py`

### Actual per-stat extraction (PR #66)
- `get_actual_fpts()` now extracts all 9 scoring stats from ESPN `raw_stats` per game
- Stored in daily cache as `actual_stats` field: `{player_name: {fpts, stats: {ip, so, h, bb, er, hb, w, l, sv}}}`
- Structure mirrors v2 projection breakdown for direct comparison

### Accuracy tracking dashboard (PR #67/68)
- New `api/accuracy.py` serverless endpoint
- New `pages/accuracy.tsx` dashboard with summary tiles, per-stat MAE bar chart, expandable start rows
- Added "Accuracy" to sidebar navigation

---

## Session 14 — April 11, 2026

V2 projection locking with per-stat breakdown, ESPN stat ID mapping discovery. One PR shipped (#64).

### Key learnings this session
- Upstash Redis stores JSON natively via `json.dumps()` — same NX (write-once) flag works for JSON values as for floats.
- `proj2:` key prefix separates v2 rich data from v1 floats — both systems coexist without breaking the frontend.
- ESPN per-game `raw_stats` dict uses numeric string keys (e.g., `"34"`, `"57"`) — stat ID mapping not publicly documented.
- Today's data is never cached by `get_actual_fpts()` (`date_str >= today_str` → always fetches fresh).
- `git commit --amend` on `main` after a squash merge causes local/remote divergence — fix with `git reset --hard origin/main`.

### V2 projection locking (PR #64)
- `api/kv.py`: new functions `set_locked_projection_v2()`, `get_locked_projection_v2()`, `get_all_locked_projections_v2()`
- Key schema: `proj2:{season}:{period}:{player-slug}:{date}` → JSON object
- V1 float locking unchanged — frontend compatibility preserved

### ESPN stat ID mapping (discovered, later corrected in session 15)
- Extracted raw ESPN per-game stat dict via terminal API call for Joe Ryan
- Initial mapping obtained — W/L corrected from 32/33 to 53/54 in session 15

---

## Session 13 — April 11, 2026

Projection model layers 2+3, projection breakdown tooltip, option_b rename. One PR shipped (#60).

### Key learnings this session
- MLB Stats API `gameLog` stat type with `playerPool=all` returns per-game stats for ALL pitchers in one call — no need to look up individual player IDs.
- Baseball Savant park factors page is JS-rendered — no CSV endpoint available. Hardcoding 3-year rolling values is the standard approach (FanGraphs does the same). Park factors are driven by physical dimensions and elevation, so they barely change year to year.
- Park factors affect only ~half of fantasy stats (H, ER are park-dependent; IP, K, BB are not). Dampening the raw factor by 50% gives a more accurate FPTS adjustment than applying the full run-environment factor.
- `position: absolute` tooltips get clipped by parent `overflow: auto` containers (like our horizontally-scrollable table). `position: fixed` with `getBoundingClientRect()` coordinates escapes any overflow container.
- `git commit --amend --no-edit` replaces the last commit with updated files — keeps the PR clean when fixing small issues after initial commit.
- When adding a 4th return value to a function, every caller must be updated — grep for all call sites before committing.

### Layer 2: Recent form weighting (PR #60)
- `fetch_game_logs()` in `mlb.py`: fetches per-game pitching stats from MLB Stats API (`stats=gameLog&playerPool=all`) — single call for all pitchers
- `compute_recent_form_fpts()`: filters to actual starts (gs=1), takes last 4, weights at 10/20/30/40% (oldest→newest)
- Blended into projection: 60% season base rate + 40% recent form
- Only applied when pitcher has 4+ starts (avoids overreaction to small samples)
- Game logs cached with 24hr TTL (`cache:game-logs:2026`)

### Layer 3: Park factors (PR #60)
- `PARK_FACTORS` dict in `mlb.py`: 3-year rolling Runs factors from Baseball Savant for all 30 teams (100 = neutral)
- `get_park_factor()`: converts to multiplier and dampens 50% — Coors (115) → 1.075, Oracle Park (92) → 0.96
- Applied per-start alongside wOBA opponent adjustment: `fpts × wOBA_factor × park_factor`
- `is_home` field added to `startDates` in `get_starts_for_players()` — determines whose park the game is at
- Home starts use pitcher's team park, away starts use opponent's park

### Projection breakdown tooltip (PR #60)
- New `components/ProjectionTooltip.tsx` — reusable hover popover with two modes
- Uses `position: fixed` to escape `overflow: auto` table containers

### Cleanup (PR #60)
- Renamed `option_b_inputs` → `projection_inputs` throughout `espn.py`
- Bumped `CACHE_VERSION`: my-team 6→7, free-agents 3→4

---

## Session 12 — April 11, 2026

ESPN API deep-dive, projection model upgrade to Savant-powered hybrid, tile redesign, dropped streamers, caching infrastructure. Eleven PRs shipped (#49–#59).

### Key learnings this session
- ESPN `lineupSlotId` is per-day accurate — verified 98 data points across 7 days × 14 players, zero mismatches against ESPN website screenshots.
- `player.injured` (boolean) is the reliable IL signal. `playerPoolEntry.injuryStatus` returns empty `""` for all rostered players.
- `eligibleSlots` determines SP vs RP (stable). `lineupSlotId` is a daily lineup decision — never use for position classification.
- Baseball Savant CSV endpoints (`&csv=true`) are public, no auth, return rich Statcast data.
- Savant xERA and xBA are more predictive than raw ERA/BA — they remove BABIP luck and sequencing variance.
- Caching static data (2025 stats) permanently and current data with 24hr TTL cuts response time by 50%+.

### Major changes
- Projection sequencing + bench/IL normalization (PR #49)
- KNOWLEDGE.md created with confidence-rated API reference (PR #49)
- Tile redesign (PR #51)
- Dropped streamer detection (PRs #52, #53)
- Baseball Savant data fetcher (PR #54)
- Savant-powered hybrid projection model (PR #56)
- Savant data caching (PR #57), MLB Stats API caching (PR #58), Daily actual FPTS caching (PR #59)
- Response time reduced from ~4.8s to ~2.1s (56% improvement)

---

## Session 11 — April 10, 2026

Upstash KV locked projections, full-name pitcher matching, bench player start fix. Seven PRs shipped (#41–#47).

---

## Session 10 — April 9, 2026

Opponent quality adjustment using team wOBA factors. One PR shipped (#39).

---

## Session 9 — April 9, 2026

Sortable free agents table, SP slot filter fix, FA actual FPTS, projection model fixes. One PR shipped (#37).

---

## Session 8 — April 8, 2026

FA projections, per-start cell projections, actual FPTS column. One PR shipped (#35).

---

## Session 7 — April 7, 2026

Roster transaction lag fix, Option B projected FPTS model, relievers section, period dropdown fixes.

---

## Sessions 1-6 — March 27–30, 2026

Initial build: auth, layout, ESPN API integration, schedule grid, probable pitchers, matchup period dropdown, actual FPTS, bench/IL distinction.

---

## Pre-session baseline

Initial working prototype with ESPN API connection, single-page step wizard, hand-rolled auth, Claude AI analysis.
