# The Skipper — Changelog

---

## Session 25 — April 25, 2026

A diagnostic-heavy session that started with three reported bugs on the accuracy dashboard and ended with two PRs shipped. The lead bug — Apr 23 showing only 2 of 15 expected actual entries — turned out to be yesterday's daily cron silently writing partial data and NX-locking it permanently. PR #108 added three layers of defense against that exact failure mode: instrumented `fetch_game_logs` with per-outcome counters, force-refresh of game-log and season-stats caches on every cron run, and a floor check that skips NX-writes for suspiciously small daily slates. PR #109 closed the cosmetic gaps on the accuracy dashboard — lowercase player names and a missing matchup column — and surfaced a backlog item for proper case+accent preservation upstream. Both PRs verified in production within the same session.

### Key learnings this session
- **The 24h cache TTL aligned with the 24h cron schedule creates a race that turns transient failures permanent under NX-write-once.** When the cache fills with partial data and the cron then writes that partial data with NX, *it cannot self-heal* — the next cron's fresh data gets blocked by the existing key. We saw this concretely: yesterday's cron wrote `actual-all:2026-04-23` with 2 entries (Cavalli + Skubal) from a partial `fetch_game_logs` result; today's cron rebuilt the full 15+ entries dict in memory but NX correctly refused to overwrite. The data was permanently locked-in-bad until manually deleted. PR #108's force-refresh of `cache:mlb-stats` and `cache:game-logs` at the top of every cron run breaks this cycle — staleness is no longer a risk vector for write-once paths.
- **Silent failures need defense, not detection alone.** Session 24 added per-step counters; that helped us *see* the failure mode in this session's diagnostic. But seeing isn't enough — we still ended up with permanent bad data because the writer had no defense. PR #108's `ACTUALS_FLOOR = 4` is the missing piece: any date with fewer than 4 entries gets skipped rather than written, on the heuristic that regular-season MLB days reliably have 10+ starts. The floor is generous enough not to false-positive on legitimate small slates (it fired once today on what was almost certainly Opening Day) and tight enough to catch the kind of partial fetches we've seen.
- **Counter granularity matters more than counter count.** Pre-PR-#108, `fetch_game_logs` had a single `errors` counter that only tracked thread-pool exceptions. The actual silent-failure mode was HTTP 200 with empty splits — completely invisible. The new shape splits this into `with_data`, `empty`, `http_errors`, `exceptions`. A future spike like "empty: 240 of 250" jumps out immediately in `cache:cron-summary`; previously it was indistinguishable from a healthy run in any log line.
- **Hypothesis-test-confirm beats reading-code-first when chasing silent failures.** Initial hypothesis: call-up rookies were missing because `mlb_stats_current` was stale. Wrong — the actuals KV blob had all 18 expected pitchers (15 projected + 3 spot-starters), not 8-9. Reading code afterward showed the actuals iteration was clean; the bug was upstream in cache freshness. Asking for a `GET actual-all:2026-04-23` early in the diagnosis would have ruled out the wrong hypothesis in 30 seconds; the byte-size estimate I worked from was sloppy (260 bytes/entry was wrong; actual was ~140). Lesson: when you can cheaply check actual data, do that before spinning theories about code paths.
- **Forward-only is sometimes the right scope.** PR #109's matchup-column fix only populates `opponent` and `isHome` for new `proj2all:` lock values. Legacy keys still show `@?`. Trying to retroactively backfill would require re-running ESPN/MLB schedule lookups for every locked date, and the keys cycle out naturally as new data accrues. Better to ship the shape change forward-only than block on a backfill mechanism.
- **Display lifts that look small often bottom out at upstream data shape.** The `titleCase()` helper covers most of the lowercase-names bug, but McCullers / deGrom / DeJong / JT Brubaker all reveal the limit: case info that wasn't preserved at ingestion can't be perfectly reconstructed at render. The proper fix lives in `fetch_season_stats` (store `_fullName` alongside `_mlbId`) and the cron's actuals writer (carry the original-cased name through to the actual-all entry). That's a separate PR, but worth flagging the dependency in the backlog so the v1 fallback isn't mistaken for the final answer.
- **Sandbox git operations leave lock files even when read-only.** Running `git status` and `git diff` from the sandbox to verify changes left `.git/index.lock` that the user's terminal couldn't acquire. Session 24's "Claude edits, Conner drives git" rule was insufficient — it needs to extend to *all* git invocations including inspection. Validation in the sandbox is now restricted to non-VCS commands (Python `ast.parse`, `tsc --noEmit`, etc.).

### Diagnostic detour: tracing the partial actuals
Before any code was written, ~90 minutes went into KV inspection to nail down the failure mode. The arc:

1. Three bugs reported on the accuracy page: lowercase names, `@?` in the matchup column, and Apr 23 only showing 2 starts with no Apr 24 data at all.
2. First KV pass: `actual-all:2026-04-23` existed (380 bytes), `actual-all:2026-04-24` didn't, `cache:cron-summary:2026-04-25` was nil. Today's cron either hadn't run or had failed silently.
3. Time-zone math saved the next misstep: response headers showed it was 15:19 UTC, scheduled cron is 17:00 UTC — today's run hadn't fired yet, that wasn't a failure. The real anomaly was yesterday's partial Apr 23.
4. Manual cron trigger after rotating `CRON_SECRET` (local `.env.local` was stale from session 24's rotation playbook missing a step). Response: `actualsStored: 1` with NX correctly skipping the existing partial blob — exactly what NX is designed for, but exactly the wrong outcome when the existing data is bad.
5. `DEL actual-all:2026-04-23` + manual retrigger. New write produced a 2297-byte blob with 18 entries (15 projected + 3 spot-starters: JR Ritchie, Christian Scott, Matt Waldron). The hypothesis I'd been chasing — "call-ups are missing" — turned out to be wrong; everyone was there in the fresh fetch. Yesterday's cron had hit a transient silent-failure window in `fetch_game_logs` that today's run no longer reproduced.
6. Reading the cron + fetcher + mlb code with that data point in hand made the actual root cause obvious: `if games:` filtered out empty per-player results without counting them, so a partial fetch looked successful at every layer. Hence PR #108.

### PR #108 — Cron actuals silent-failure hardening
Three files, 157 insertions / 28 deletions. Behavior changes mapped directly to the failure modes the diagnostic surfaced.

- `api/mlb.py` — `fetch_game_logs` returns `(data, stats)` instead of `data`. Stats include `requested`, `with_data`, `empty`, `http_errors`, `exceptions`, `total_game_rows`. The internal `_fetch_one` helper now returns `(name_key, games_list, status)` where status is `"ok"`, `"http"`, or `"exception"` so the iteration can correctly bucket each outcome. The aggregation print line adds `empty` to its summary so it's visible in Vercel logs (within retention window) and in the new `cache:cron-summary:` blob (60-day window).
- `api/fetcher.py` — `load_cached_data` unpacks the new tuple and surfaces `game_log_stats` in its return dict. Cache-hit path leaves `game_log_stats` as `{}` since no fresh fetch happened; only fresh fetches carry meaningful counter values. Defensive: if `fetch_game_logs` raises, both `game_logs_current` and `game_log_stats` reset to `{}` rather than leaking partial state.
- `api/cron.py` — three behavior changes consolidated into one PR:
  1. **Force-refresh** of `cache:mlb-stats:{year}` and `cache:game-logs:{year}` at the top of `lock_all_mlb_projections`. Inline comment captures why other caches (savant, team-woba, team-win-data) are NOT force-refreshed — those change more slowly and don't feed write-once data paths.
  2. **`ACTUALS_FLOOR = 4`** check before each `actual-all:{date}` NX-write. If `len(pitchers) < ACTUALS_FLOOR`, skip with a print line capturing the date and entry count. New `actuals_skipped_partial` counter surfaced in summary. First production run fired once on what was almost certainly Opening Day's small slate — defensive behavior working as intended.
  3. **`cache:cron-summary:{date}`** blob written by the handler with 60-day TTL, regardless of whether MLB or ESPN locks succeeded. The whole `result` dict goes in. This was the single biggest observability gap from session 24's diagnostic — the summary writer was conceptual but not actually firing. Now it fires on every run, captured before the HTTP response is returned, in a try/except so write failures here can never break the response itself.

Production verification post-deploy: `actualsStored: 0` (Apr 23+24 already exist, NX-skipped), `actualsSkippedPartial: 1` (the floor working), `gameLogStats: {requested: 519, with_data: 519, empty: 0, http_errors: 0, exceptions: 0}` (clean fresh fetch — exactly the picture-perfect run we want as the baseline), `cache:cron-summary:2026-04-25` written and matches the response byte-for-byte.

### PR #109 — Accuracy page display polish
Two files, ~30 lines net. Both fixes are forward-only and contained.

- `api/cron.py` — `proj2all:` matchup sub-dict gains `opponent` and `isHome`, mirroring the shape `api/projection.py` writes for `proj2:`. The frontend already reads these fields (`accuracy.tsx` lines 359/373); the bug was that the cron path simply didn't write them. New locks from tomorrow's 17:00 UTC scheduled cron onward populate correctly; legacy `proj2all:` keys continue to surface `@?` until they cycle out of the rolling window.
- `pages/accuracy.tsx` — `titleCase()` helper using `\b\w` regex applied to `s.player` rendering. Idempotent for already-cased names ("Garrett Crochet" stays "Garrett Crochet") so safe to apply universally regardless of scope. Edge cases that the regex can't recover: internal capitals ("Mccullers" should be "McCullers", "Degrom" should be "deGrom") and 2-letter all-caps initials ("Jt Brubaker" should be "JT Brubaker"). Acceptable for v1; backlog item captures the proper fix (server-side `fullName` preservation in mlb_stats and actual-all entries).

Production verification: All MLB scope shows properly cased names across the table. Matchup column still `@?` for Apr 24/25 entries that were locked before the deploy; new entries from tomorrow forward will populate.

### Decision punted: cron schedule cadence
Discussed during PR #108's design but not acted on. Hobby plan permits 2 cron jobs and we're using 1 (the daily 17:00 UTC run that does both projection-locking and actuals-writing). Theoretical split:
- ~14:00 UTC (9am CT) → projections only — locks today's projections after probable starters and ESPN Forecaster have firmed up
- ~08:00 UTC (3am CT) → actuals only — runs after Pacific games end, locks yesterday's actuals immediately

Wins: slightly fresher actuals for next-morning users, failure isolation between the two jobs. Costs: refactor `lock_all_mlb_projections` and `lock_espn_projections` to be invokable independently, conditional logic in the handler based on a query/header parameter, vercel.json schedule entries for both, additional counter surfaces.

Outcome: deferred. The brittleness was the bug, not the schedule. After PR #108's hardening, the case for splitting becomes purely UX-driven and can be revisited if/when fresher actuals materially change user behavior.

### Ops — manual KV cleanup + CRON_SECRET re-rotation
- `DEL actual-all:2026-04-23` to clear the partial 380-byte blob from yesterday's failed cron, then manual `/api/cron` curl to write the full 18-entry replacement. Confirmed via `STRLEN` (380 → 2297 bytes) and accuracy dashboard refresh (2 → 15 matched starts after the data fix).
- `CRON_SECRET` rotated again — local `.env.local` had a value pre-dating session 24's rotation, since session 24's playbook captured "saved to password manager → updated Vercel env var" but didn't include "and update `.env.local`." Future rotations should explicitly update `.env.local` as part of the playbook.

---

## Session 24 — April 19, 2026

Three PRs shipped on a single branch of focus — the Accuracy dashboard — plus a multi-hour diagnostic detour that uncovered a silent MLB Stats API failure affecting every production projection. PR #104 collapsed the matchup-period dropdown into an all-time aggregation and fixed a long-standing roster-scope FA leak. The "All MLB tab shows zero results" report that surfaced afterward turned out to be two tightly-coupled bugs: `fetch_game_logs()` was silently returning `{}` because the MLB Stats API does not support `gameLog + playerPool=all` (it returns HTTP 200 with empty `stats[]`), and the cron-time slug computation was mismatching accented-name pitchers because one side preserved accents while the other side stripped them. Both fixed in PR #105. PR #106 then added the MAE timeline chart that's been on the backlog since session 18 — a Skipper-vs-ESPN line chart with 7-day rolling averages and vertical markers for model-changing deploys.

### Key learnings this session
- **Silent API failures are the worst kind of failure.** `curl https://statsapi.mlb.com/api/v1/stats?stats=gameLog&playerPool=all&group=pitching&season=2026&gameType=R&limit=5000` returns HTTP 200 with `{"copyright":"…","stats":[]}` — no error, no warning, no rate-limit signal, just the successful return of nothing. The bulk endpoint looked fine in code review for weeks and passed every happy-path test we had. The real tell was downstream: `recentForm: null` on every projection, zero `actual-all:` keys in KV even though the cron was running cleanly. Lesson: when a function returns `{}` or `[]`, the next layer up needs to print a clear diagnostic (`"[mlb.py] Game logs: 0 pitchers with entries"`) so the silence becomes visible. PR #105 added these exact counters to both `fetch_game_logs()` and `cron.py`'s actuals block — if this class of bug returns, it shows up in logs immediately.
- **Cross-source name normalization must be enforced at one choke point, not many.** `fetch_mlb_probables()` returned pitcher names with accents preserved (`"eury pérez"`). `fetch_season_stats()`, `fetch_savant_pitchers()`, and `fetch_game_logs()` all keyed their dicts by `strip_accents(name)` (`"eury perez"`). The `_make_slug()` regex `[^a-z0-9]+` then converted the accented characters to dashes, producing keys like `proj2all:2026:3:eury-p-rez:2026-04-19` that could never match the `strip_accents`-based `actual-all:` entries. The fix was a one-line `pitcher_name_lower = strip_accents(pitcher_name_raw)` at the top of the cron loop — but only after spending 30+ minutes convinced the bug was somewhere else. When multiple data sources disagree about a primary key, normalize at ingestion, not at comparison.
- **When logs are time-limited, KV is the debugger.** Vercel Hobby only surfaces logs from the last 1 hour. For intermittent or once-per-day cron bugs, the logs are already gone by the time you look. Upstash's Data Browser became the diagnostic tool — `KEYS proj2all:*`, `KEYS actual-all:*`, `STRLEN cache:game-logs:2026`, `GET proj2all:2026:3:garrett-crochet:2026-04-19` — each answered "did this step actually write?" and "what shape did it write?" without waiting for the next cron cycle. Design cron-style write paths with this in mind: every significant step should leave a verifiable artifact in KV.
- **Silent failures deserve write-path observability, not just read-path.** Added counters to `cron.py`'s actuals block: `total_game_rows`, `actuals_dates_eligible`, `actuals_stored`, `actuals_write_errors`. On the next run these print as a single summary line that tells the whole story: "processed 1,847 game rows across 247 pitchers → 26 eligible dates → wrote 25 new, 1 already existed, 0 errors." A future silent regression (e.g. someone changes the cache key shape) will now surface as "wrote 0 new" in production logs instead of disappearing into a no-op. Cheap insurance; always worth it in cron paths.
- **Client-side chart data is cheaper than a new endpoint.** PR F's first design instinct was to add a `/api/accuracy/timeline` endpoint returning pre-aggregated daily MAE series. But `/api/accuracy` already attaches `espnFpts`/`espnError` to every matched start when `scope="all"`, and the group-by-date + rolling-window math is trivial to do in the browser off that existing payload. Net result: zero backend changes, entirely frontend-only PR. Rule of thumb: before adding an endpoint, grep the existing payload — the data is often already in the response.
- **Calendar-day-windowed rolling averages handle sparse data better than row-window.** A naïve 7-row rolling average on sparse date-bucketed data over-smooths: 7 "rows" can span 30 calendar days if MLB had an off-day stretch. The weighted-by-sample-count calendar-day window in `MaeTimelineChart.rollingAvg()` uses actual date arithmetic and weights each day by its matched-start count, so a date with 5 starts counts more than a date with 1. This matches what "7-day MAE" intuitively means and degrades gracefully through sparse stretches.
- **Dev-server env var gaps don't surface until you actually run dev.** Local `npm run dev` hit `[next-auth][error][NO_SECRET]` because `NEXTAUTH_SECRET` and `NEXTAUTH_URL` were never added to `.env.local` — we'd always deployed straight to preview/prod. The three local-only env vars that matter (`NEXTAUTH_SECRET`, `NEXTAUTH_URL=http://localhost:3000`, `APP_USERNAME`) are now captured in the setup notes in KNOWLEDGE.md. Also worth knowing: local and production `APP_PASSWORD` do NOT need to be the same — treat local as its own credential world.
- **Sandbox git lock files persist past session boundaries.** When Claude's sandbox runs `git pull`, the ORIG_HEAD.lock file can't be cleaned up on sandbox exit due to filesystem permissions, and the next `git pull` from the user's local terminal then fails with "unable to create .git/ORIG_HEAD.lock". One-time fix: `rm .git/ORIG_HEAD.lock`. Permanent fix: all git operations from here on run in the user's terminal, never in the sandbox. Claude edits files; Conner drives git.

### PR E — All-time accuracy aggregation + roster-scope FA leak fix (PR #104)
- `api/accuracy.py`:
  - `period` parameter is now optional. Handler accepts `?period=` (empty or absent) as "all-time" and calls `get_accuracy_data(season, period=None, scope=scope)`. Explicit integer still scopes to a single period for backward compat if any external caller passes one.
  - When `period is None`, the proj-key glob becomes `{proj_prefix}:{season}:*:*` — scans across all 22 periods instead of one. Same for the ESPN lookup path (`_fetch_espn_lookup(season, period=None)` becomes `projection-espn:{season}:*`).
  - **Roster-scope FA leak filter.** `proj2:` keys accumulate locks for any pitcher viewed through the Free Agents surface — session 13's pattern was "lock on view," which is correct for My Team but means the `proj2:` namespace fills up with FA pitchers who were never actually rostered. The fix uses the `my_team` dict already written into each `cache:daily:{date}` entry (by `get_actual_fpts()` in session 19's PR #81) as the authoritative "who was on my roster that day" index. The match loop now computes `my_team_by_date: {date → set(full_names)}` and drops any matched start where `matched_name not in my_team_by_date[date]`. Dropped counts surface as `filteredNonRoster` in the response. Conservative behavior: if a date has no `my_team` entry in its cache (pre-session 19 caches exist), the start is dropped rather than risk re-polluting the roster view.
  - Diagnostic prints extended to break out `filtered_non_roster` when scope is roster.
- `pages/accuracy.tsx`:
  - Period dropdown removed entirely. Header subtitle now reads "All-time projected vs actual per-stat breakdown — every locked start, every period."
  - Filter strip logic simplified; period state eliminated. Data fetch uses `fetch('/api/accuracy?season=2026&scope=...')` with no period param.
  - Small FA-leak diagnostic appears below the starts table when `filteredNonRoster > 0`: "X non-roster start(s) hidden (locked via Free Agents view)" — gives a visible hint about what the new filter is doing.
- Deploy verification: before PR E, roster scope showed ~60 starts polluted with dropped FA projections; after, 12–18 starts matching the actual roster. All MLB scope unaffected by the filter (by design — scope="all" skips the FA check entirely).

### PR G — Fix silent game_logs failure + accented-name slug mismatch (PR #105)
- **Root cause discovery.** The All MLB Accuracy tab was returning zero matched starts even though both Skipper and ESPN had projections locked. KV inspection showed 29 `proj2all:2026:3:*:2026-04-19` keys but zero `actual-all:*` keys — the actuals writer wasn't writing. Direct curls to MLB Stats API revealed that `stats=gameLog&playerPool=all` silently returns `{"stats":[]}` with HTTP 200 (no error). The per-player `/api/v1/people/{id}/stats?stats=gameLog&group=pitching&season=2026&gameType=R` endpoint returns full 7KB game log responses. The bulk endpoint had never worked for gameLog; the code only appeared to work because nothing downstream tested "did game_logs actually populate?"
- `api/fetcher.py`:
  - `fetch_season_stats(year)` now attaches `"_mlbId"` to each stat dict from `splits[].player.id`. Shallow-copies the stat dict so upstream mutations don't leak. Every downstream consumer already keys by `strip_accents(fullName)` → adding `_mlbId` as a separate field doesn't break anything.
  - `load_cached_data()` now passes `mlb_stats_current` to `fetch_game_logs(year_int, mlb_stats_current)` so the game-log fetcher can iterate per-player IDs. Inline comment explains why.
- `api/mlb.py`:
  - `fetch_game_logs(season, mlb_stats)` rewritten to use the per-player endpoint with `ThreadPoolExecutor(max_workers=10)`. Extracts `(name_key, player_id)` pairs from `mlb_stats.items()` where `_mlbId` is populated; submits one future per pitcher; aggregates results. Handles per-player HTTP failures gracefully (returns empty games list for that pitcher, counts toward an `errors` total that's logged).
  - Defensive guard: if `mlb_stats` is empty or no entries have `_mlbId`, returns `{}` immediately with a clear log line. This is what surfaces when running against a stale cached `cache:mlb-stats:2026` from a pre-PR-G build.
  - Diagnostic line on success: `"Game logs: {N} pitchers with entries, {total} total game rows ({errors} per-player fetches errored)"`. First deploy printed `"Game logs: 247 pitchers with entries, 1847 total game rows (0 per-player fetches errored)"`.
- `api/cron.py`:
  - Name normalization added at the top of the lock loop: `pitcher_name_lower = strip_accents(pitcher_name_raw)`. All downstream lookups (`mlb_stats_current.get(pitcher_name_lower)`, `savant_data.get(pitcher_name_lower)`, `game_logs_current.get(pitcher_name_lower)`) and slug generation now use the stripped name consistently. Inline comment captures the pre-PR-G slug mismatch (`eury-p-rez` vs `eury-perez`) so future readers know what this line is guarding against.
  - Actuals-block observability counters added: `total_game_rows`, `actuals_dates_eligible`, `actuals_stored`, `actuals_write_errors`. Summary prints on every run so a future silent regression surfaces in logs instead of silently no-op'ing.
  - Skip-early print when `game_logs_current` is empty: `"Skipping actual-all: writes — game_logs_current is empty"`.
- **Deploy + backfill sequence:**
  1. Merge PR #105 → Vercel auto-deploys production.
  2. Delete `cache:mlb-stats:2026` in Upstash (stale cached dict from pre-PR-G build has no `_mlbId` values).
  3. Rotate `CRON_SECRET` (exposed in curl debug output during diagnostic session) — generate new 32-byte value, update Vercel env vars, redeploy to pick up new secret.
  4. Manual trigger: `curl -i "https://the-skipper-iota.vercel.app/api/cron" -H "Authorization: Bearer $NEW_SECRET"`. Response: `{"ok": true, …, "actualsStored": 25, …}`. Before PR G, `actualsStored` was always 0.
  5. Verified `KEYS actual-all:*` in Upstash now returns 25 date keys. Verified `GET proj2all:2026:3:pj-poulin:2026-04-19` shows `recentForm` populated as a number (previously `null`).
- Note on URL confusion: `the-skipper.vercel.app` is squatted by a wedding site (documented in CHANGELOG Session 21). The real production URL is `the-skipper-iota.vercel.app`. Accidentally used the squatted URL once during diagnostics; got a 404 serving HTML from the squatted site. Always verify with the `-iota` URL.

### PR F — Daily MAE timeline chart: Skipper vs ESPN with 7-day rolling (PR #106)
- `components/MaeTimelineChart.tsx` (new, ~200 lines):
  - Self-contained chart component taking only `{starts: Start[]}` as props. No backend changes — consumes the existing `starts` array from `/api/accuracy` which already attaches `espnFpts`/`espnError` to each matched start when `scope === 'all'`.
  - `bucketByDate(starts)` — groups by date, computes per-day Skipper MAE and per-day ESPN MAE (only from starts where `espnError != null`), tracks per-day sample counts for each series.
  - `rollingAvg(rows, windowDays)` — trailing rolling average weighted by per-day sample count, using calendar-day arithmetic (not row count) so sparse data doesn't over-smooth. A date with 5 matched starts contributes more to the smoothed line than a date with 1.
  - Renders 4 lines via `recharts`: Skipper daily (solid blue), ESPN daily (solid orange), Skipper 7-day rolling (dashed blue), ESPN 7-day rolling (dashed orange). Legend, tooltip, responsive container provided by recharts.
  - Three vertical `ReferenceLine` markers for model-changing deploys:
    - `2026-04-12` — "Vegas W/L + xERA" (PRs #75, #77, #78)
    - `2026-04-18` — "Blended wOBA + weather" (PRs #83, #84, #85, #102)
    - `2026-04-19` — "PR G: recentForm fix" (PR #105)
  - Empty states: returns `null` when `daily.length === 0`; renders a friendly "will populate once matched actuals accumulate across multiple days" card when `daily.length < 2`. The first state means we shouldn't be rendered at all (no starts); the second means rendered but not enough data to plot meaningfully.
- `pages/accuracy.tsx`:
  - Import added for `MaeTimelineChart`.
  - Chart wired into the `starts.length > 0 && scope === 'all'` branch, positioned between the `EspnHeadToHead` card and the summary tiles. **Not** rendered on roster scope (ESPN projections are whole-MLB and don't map to a single fantasy roster; no meaningful roster-scoped version exists).
- `package.json`: added `recharts: ^2.x` as a runtime dependency. ~90kb gzipped; provides tooltips, legend, responsive container, reference lines. Considered hand-rolled SVG (zero deps, ~150 lines) and ruled out because recharts gives all the interactive polish for free and we'll likely add more chart surfaces over time.
- Adding a new milestone marker is a one-line edit to the `MILESTONES` array in the component. Docstring at the top of the file captures this along with guidance on keeping the list short (≤5 markers).
- Deploy verification: production renders the empty state correctly today (`starts.length === 0` → chart hidden entirely; ESPN head-to-head card still shows "0 overlap · 30 ESPN locked"). Chart will begin appearing after the April 20 17:00 UTC cron writes `actual-all:2026-04-19` and tomorrow's match loop finds overlap with today's `proj2all:2026:3:*:2026-04-19` locks. Meaningful 7-day rolling averages arrive around April 26.

### Ops — `CRON_SECRET` rotation (no PR)
- Exposed the old value in terminal output during PR G diagnostics. Rotated following the session 22 playbook: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` → saved to password manager → updated Vercel env var (production scope) → redeployed with "Use existing Build Cache" unchecked so the new value is picked up.
- Verified post-rotation with a fresh `curl -i .../api/cron -H "Authorization: Bearer $NEW"` call returning 200.
- Local `APP_PASSWORD` in `.env.local` was also exposed during login-help; confirmed local and production APP_PASSWORD are separate values, so the exposed local credential does not grant production access. Low-priority rotation recommended but not blocking.

---

## Session 23 — April 18, 2026

Shipped two PRs closing Session 22's loose ends and advancing the projection model: PR #101 polished the ESPN head-to-head empty state so it renders when Skipper has no locked projections yet, and PR #102 (Weather Phase 2) wired Session 20's weather factor into the live projection pipeline. Direct folder access through Cowork's `request_cowork_directory` replaced the copy/paste workflow for the first time — established the pattern of Claude editing files while Conner runs git and deploy commands locally.

### Key learnings this session
- **Refactor shared logic into module-level helpers when two control flow paths need the same computation.** PR #101's backend change had two call sites (the normal-return path and the early-return path when no `proj_keys` exist) that both needed to compute the ESPN lookup and summary. Extracting `_fetch_espn_lookup()` and `_compute_espn_summary()` into module-level helpers — rather than repeating the logic inline — made both branches look identical and kept the "what does scope=all do" contract in one place. Rule of thumb: if a nontrivial computation needs to run in two places, the right refactor is usually the helper, not a copy.
- **Frontend empty states earn their own design pass.** The empty state after PR C shipped was *correct* (no Skipper data yet) but *wrong* in spirit — the head-to-head block was the entire point of that PR, and hiding it during the exact window when it has the most marginal value (before first overlap) was the opposite of what we wanted. Wrapping the empty branch in a React fragment and composing `<EspnHeadToHead>` above the empty card was a 2-line change that flipped the UX from "nothing here yet" to "here's what we're already tracking, Skipper data arrives tomorrow." Small bit of wiring with outsized effect.
- **Safe-default design makes integration PRs trivial.** PR #102 adding weather as a fourth multiplier went in with no guards, no feature flags, and no per-start null checks in the consumer — because `get_weather_factor()` is *guaranteed* to return `{"factor": 1.0, ...}` on every failure path (dome override, unknown park, Open-Meteo 5xx, cache miss, exception). When the upstream contract is "never break the caller," integration sites can treat the output as always-valid and the math simplifies to `start_base * woba * park * weather`. Contrast with APIs that raise or return None — those spread `if x is None:` checks through every consumer.
- **Mirror computations verbatim across read and write paths.** `api/projection.py` has a live per-start loop that computes `start_proj` and a lock path that rebuilds the same value for storage. The weather factor had to be applied in both sites identically — otherwise accuracy analysis would be comparing a weather-aware locked projection to a weather-naïve actuals calc, or vice versa. When auditing new multipliers, always grep for "start_proj =" and "start_proj =" in both the display path and the persistence path.
- **Direct folder access removes the worst part of the iteration loop.** Pre-session 23, each change required: Claude writes file → copy code block out of chat → paste into Cursor/editor → save → run tests. With `request_cowork_directory` mounting `~/Developer/the-skipper` into Claude's sandbox, the loop is: Claude edits file → Conner runs `git diff` → commit/push. Sandbox permission limits mean Claude can't write to `.git/` or delete staged files, so the clean division of labor is "Claude edits; Conner commits/deploys" — which is actually a better mental model anyway (Claude never accidentally pushes). Worth the 30 seconds of setup.

### PR #101 — Accuracy dashboard ESPN empty-state polish
- `api/accuracy.py`:
  - Extracted `_fetch_espn_lookup(season, period) -> {slug:date → fpts}` helper at module scope — scans `projection-espn:{season}:{period}:*` keys, skips placeholders, returns a flat lookup dict. Guards against missing Redis (returns `{}`).
  - Extracted `_compute_espn_summary(espn_lookup, starts) -> {totalStarts, mae, skipperMaeOnIntersection, espnKeysFound}` — mutates `starts` in place to attach `espnFpts`/`espnError`, computes the intersection subset, returns the summary dict. Handles empty-intersection gracefully with `mae: null` and still surfaces `espnKeysFound` so the frontend can render "X ESPN projections locked for this period" before any overlap exists.
  - Early-return path `if not proj_keys: return {...}` now calls `_compute_espn_summary(_fetch_espn_lookup(season, period), [])` when `scope == "all"` — response gains `espnSummary` even with no Skipper projections. The ~60-line inline ESPN block at the end of `get_accuracy_data` replaced by ~10 lines calling the two helpers.
- `pages/accuracy.tsx`:
  - Empty-state branch (`starts.length === 0`) wrapped in a React fragment so both the `EspnHeadToHead` block and the existing "No accuracy data yet" card render when `scope === 'all'` and `espnSummary` is non-null.
  - Empty-state subtext extended: when `espnSummary.espnKeysFound > 0`, shows "{N} ESPN projections locked for this period" in small mono type so users see data accumulating.
- Deploy verified on production against period with no Skipper locks — `EspnHeadToHead` now renders with "No overlap yet" contextual copy, and the lock count appears in the empty card.

### PR #102 — Weather Phase 2: wire `get_weather_factor()` into projection pipeline
- `api/projection.py`:
  - `from weather import get_weather_factor` added alongside existing mlb/kv imports.
  - Live per-start loop (`not is_rp and start_dates`): after computing `park_factor`, calls `get_weather_factor(park_team, start_date_str)` (with safe fallback dict if park_team or date are empty). Extracts `factor`, `temp_f`, `source`. Chains into `start_proj = start_base * woba_factor * park_factor * weather_factor`. Appends three new keys to `per_start_details`: `weather` (rounded 3dp), `tempF` (raw float or null), `weatherSource` ("forecast"|"dome"|"default").
  - Lock path (`if today_str and start_dates and not is_rp`): mirrors the same calc — `lock_weather = get_weather_factor(park_tm, date)`, `weather_f` multiplied into `start_proj`, and a new `"weather": { factor, tempF, source }` sub-dict added to the locked breakdown JSON.
  - Breakdown schema now: `{fpts, stats, matchup, weather, model}` — the new `weather` block enables factor-contribution analysis on the accuracy dashboard (same pattern as the existing `matchup` block).
- `components/ProjectionTooltip.tsx`:
  - `StartDetail` interface extended with optional `weather?: number`, `tempF?: number | null`, `weatherSource?: string`.
  - Single-start tooltip mode: new `Row` after Park — `Weather (72°F) ×1.012` with a `FactorLabel`. Only rendered when `weatherSource === 'forecast'` (dome and default hide to reduce noise).
  - Total tooltip mode per-start summary: compact weather `FactorLabel` appended after park between the park factor and win-probability chip. Same `weatherSource === 'forecast'` guard.
- Safety (no change from Phase 1): `get_weather_factor` always returns `factor=1.0` on any failure (dome override, unknown park, Open-Meteo timeout, cache error, exception). 3hr Redis TTL under `cache:weather:{park}:{date}` prevents per-refresh API pressure. ±5% hard cap prevents pathological weather from distorting the model.
- Integration test: TypeScript `tsc --noEmit` clean; Python `ast.parse` clean on both `projection.py` and `weather.py`; `import projection` succeeds with `get_weather_factor` resolving.
- Deploy verified — tooltips now show weather row on outdoor-park starts, dome parks stay clean, diagnostic endpoint still functional.

### Workflow note — direct folder access
- Invoked `request_cowork_directory` at Conner's prompt ("How can I give access to the correct local folder so I don't need to download, copy/paste, save files?").
- User selected `~/Developer/the-skipper`, mounted under `/sessions/eloquent-serene-curie/mnt/the-skipper` in Claude's sandbox.
- Claude can read/edit files directly, run `python3 ast.parse`, `tsc --noEmit`, `git status`, `git diff`, `git log`. Cannot reliably write to `.git/` (sandbox permission model blocks some operations on lock files).
- Division of labor established: **Claude edits source files and does dry-run checks; Conner runs `git commit`, `git push`, `gh pr create`, `vercel --prod`**. Keeps commit authorship clean and lets Conner gate every deploy.
- Two PRs shipped under the new pattern (#101, #102) with no copy/paste friction — confirms the workflow is production-ready.

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
