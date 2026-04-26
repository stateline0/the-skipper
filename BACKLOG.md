# The Skipper — Backlog

Last updated: April 25, 2026 (session 27)

---

## 🔜 Next session priorities

### Stats view tab on My Team / Free Agents
Pitcher-first feature designed in session 25:
- [ ] Tab toggle on each existing page (Schedule view ↔ Stats view); same data fetch, different lens — design choice was tabs over a separate sidebar entry
- [ ] Columns: % rostership (from ESPN `kona_player_info.percentOwned`), FPTS/game, season counters (W/L, ERA, K/9, BB/9), Savant-derived expecteds (xERA, xwOBA, woba_diff, Barrel%, Whiff%)
- [ ] Luck indicator badge (3-state: Trending up / On pace / Trending down) computed from `fpts_per_start_actual` vs `fpts_per_start_expected` delta — show the underlying deltas in a tooltip rather than a continuous-scale number
- [ ] Projected season pace FPTS — `actual_fpts_to_date + expected_fpts_per_start × estimated_remaining_starts`. Pace is a comparator, not a prediction
- [ ] Column system data-driven from a config array per role so a future hitter expansion is cheap; `PITCHER_COLUMNS` const for v1
- [ ] Source data already cached: `cache:savant`, `cache:mlb-stats`, `cache:game-logs` — only `% rostership` requires extending the existing `kona_player_info` extraction (already called for free-agent projections)

### Weekly planner / decision automation MVP
The big-picture feature still on the roadmap but not next-up:
- [ ] AI-powered weekly optimization: recommend add/drop sequence and start/sit decisions
- [ ] Teach Anthropic API about ESPN transaction rules (daily locks, waiver priority)
- [ ] Hybrid mode: AI suggests plan, user picks A/B for key decisions, AI outputs full sequence
- [ ] Uses projection model data as input

### Model Improvements
- [ ] Weather impact — Phase 3: wind direction model (add `PARK_OUTFIELD_BEARING` per park, compute out-to-outfield wind component, combine with temp into single weather multiplier)
- [ ] ProjectionTooltip: split opponent wOBA display into season + last-14-day components (currently shows only the blended factor; show `seasonFactor`, `recentFactor`, and `blendedFactor` with weights)

### Pre-acquisition follow-ups (deferred from session 26 PR #111)
PR #111 fixed the user-visible aggregates for mid-week pickups but deliberately punted on three downstream concerns. Two remain; the third closed as PR #115 in session 27. None are user-blocking; all forward-only.
- [ ] **`projection.py` lock-skip for pre-acquisition starts.** PR #111 tags `preAcquisition` post-hoc in `espn.py` after `get_projected_fpts` has already run, so per-start `proj2:` locks may be written for starts the user never benefited from. Forward-fix requires moving the actuals fetch above projection (so tagging precedes locking) — a substantial reorder of `get_league_data`. Practical impact today is low because most pre-acq starts already have `proj2:` locks from the cron all-MLB path or from prior owners' roster fetches.
- [ ] **Accuracy dashboard "My Roster" scope filter for pre-acq starts.** Even after the lock-skip above, legacy `proj2:` locks from before pre-acq tagging existed will still match the current owner's roster slug and surface in the accuracy view. Symmetric fix to PR #104's FA-leak filter: drop matched starts where the matched date falls outside the rostered window (use the same `my_team_by_date` index already in scope).
- [x] ~~**Dropped player post-drop `actualFpts` pruning.**~~ (Resolved in session 27 PR #115 — `info["player_fpts"]` now intersected with `days_on_team_set` in the dropped-player branch of `api/espn.py`. Symmetric closure of the rostered-window invariant — see KNOWLEDGE.md.)

### Dropped-player per-start projection display
- [ ] Schedule grid reads `projectionDetails?.[pitcher.name]` from a global map populated only from `roster_sps`. Dropped players' per-start details live on `pitcher.projDetails` (set on the player object directly at `api/espn.py` line 622), which is never reached by the cell rendering logic. Net effect: any dropped pitcher with future or live-day starts displays a confirmed indicator without a `+X.X` projection underneath. Surfaced during PR #114 verification when the pre-fix Montero case landed in `droppedPlayers`. Two fix options: (1) merge dropped players' `projDetails` into `proj_details_roster` in `api/espn.py` before returning so the global map covers them, or (2) update `ScheduleGrid.tsx` cell paths to fall back to `pitcher.projDetails` when the global lookup misses. Option (1) is cleaner because it doesn't fork the frontend's data source. Low urgency — most dropped pitchers' starts are in the past where the cell shows actual FPTS instead.

### Display polish (low priority)
- [ ] Title-case edge cases on accuracy page: store original `fullName` (case + accents preserved) in `mlb_stats_current` and `actual-all:` entries so the dashboard renders "Lance McCullers Jr." (not "Mccullers"), "Eury Pérez" (not "Perez"), "JT Brubaker" (not "Jt"). PR #109's `\b\w` regex client-side `titleCase()` is the v1 fallback; proper fix is server-side preservation of original case + accents

---

## 📋 Backlog (lower priority)

### Projection model — Layer 5: Platoon splits
- [ ] Pitcher performance vs left-heavy vs right-heavy lineups
- [ ] Team handedness composition from MLB Stats API

### Projection model — Layer 6: Rest & workload
- [ ] Days since last start (4 vs 5+ day rest performance)
- [ ] Season pitch count trajectory (fatigue effects)
- [ ] Most meaningful mid-to-late season

### Prospect monitor
- [ ] Track top MLB prospects approaching call-up
- [ ] MLB Stats API minor league rosters + prospect rankings
- [ ] Alert when top-50 prospect + 40-man roster + corresponding MLB spot opening
- [ ] 12-24 hour edge over league competitors

### Hitter nudge engine
- [ ] Lighter-weight than pitcher optimizer — "this waiver wire guy is outperforming your current 2B"
- [ ] Not a full streamer optimizer, more of a watchlist with performance alerts

### Dropped streamers refinement
- [x] ~~Pull locked projections from KV for dropped players' past starts~~
- [x] ~~Show proj FPTS for the starts they made while rostered~~
- (Both resolved in session 19 PR #81 — dropped players now route through `get_projected_fpts`)

### Additional caching opportunities
- [ ] Pro team map (permanent — barely changes)

### Dashboard at-a-glance component
- [ ] Projected starts vs limit, current period dates, quick links

---

## 🐛 Known bugs

- [x] ~~**Pitcher added mid-day during a locked period renders empty in My Team**~~ — resolved by session 27 PR #113 (`starts_map` rebuild) + PR #114 (period-based trigger). See KNOWLEDGE.md → "Transaction lag behavior" for the full state.
- [ ] Suspended players (SSPD) not appearing in roster — Reynaldo Lopez added but missing from mRoster response. Likely ESPN uses different eligibleSlots or lineupSlotId for suspended players.
- [ ] Free agent actual FPTS only available for players who were rostered at time of start — ESPN API limitation (affects accuracy dashboard too)
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue)

---

## ✅ Completed (session 27 — April 25, 2026)
- [x] **PR #113 — Rebuild `starts_map` after transaction-lag refetch (Montero case).** Inside the existing `if today_has_started(schedule):` branch in `api/espn.py`, after the refetch reassigns `roster_entries` from the next-period mRoster, re-extract `all_player_names` and `roster_team_map` and re-call `get_starts_for_players` to rebuild `starts_map`. Schedule from this call is discarded — original `schedule` is still authoritative. New log line `[espn.py] Lag-fix rebuild: starts_map refreshed for {N} players; new names: [...]` makes future regressions visible in Vercel logs at deploy time. Closes the diagnosed-but-not-fixed bug from session 26.
- [x] **PR #114 — Trigger lag-fix branch off scoring period, not UTC today (Montero EX-slot).** Verification of PR #113 in production surfaced a deeper bug: the lag-fix trigger silently skipped during evening usage. `today_has_started(schedule)` keyed off UTC today; ESPN's scoring-period boundary tracks ET, not UTC; whenever UTC had crossed midnight while ET hadn't (typical CT/PT evening), the check returned False and the lag-fix branch never ran. Replaced `today_has_started(schedule)` with `period_has_started(schedule, current_week)` in `api/fetcher.py` — derives the date from the scoring period ESPN just returned and checks game status on that date. Removes the timezone dependency entirely. Updated comment block in `api/espn.py` to explain the history so the next reader doesn't re-introduce the regression. `today_has_started` removed (single caller; no need to leave a footgun).
- [x] **PR #115 — Prune dropped player Act FPTS to rostered window (PR #81/#111 symmetry).** Closes the third of the three follow-ups from PR #111. `info["player_fpts"]` is now intersected with `days_on_team_set` in the dropped-player branch of `api/espn.py` before being stored into `roster_actual_fpts`. Without this, a dropped pitcher's post-drop relief appearance (or anything else ESPN attributes via the FA actual_fpts path) silently inflated the row total. Added `[espn.py] Dropped Act FPTS pruning: ...` log line, fires only when entries actually got pruned. JSON shape unchanged — frontend reads the same `actualFpts` map; values are now correct.
- [x] **Architecture pattern: rostered-window invariant.** Articulated in KNOWLEDGE.md as a new section with PRs #81, #111, #114, and #115 as the four enforcement points. Reads: "any per-pitcher value the user sees on the My Team page must be scoped to dates that pitcher was actually on the roster within the matchup window." When a future aggregation in `api/espn.py` sums or counts a per-date value, the invariant is the first thing to check.
- [x] **Workflow lesson: verification at the user-action layer surfaces the next bug class.** Three PRs shipped because each PR's verification in production exposed the next problem. PR #113's verification surfaced PR #114 (Montero in EX with no projection). Without running a real-user-action verification flow, both PR #114 and #115 would have stayed invisible. Pre-deploy theorycraft is no substitute for the actual reload-and-look pass.
- [x] **Workflow lesson: don't queue up the next PR's edits while the user is mid-workflow on the previous PR.** Mid-session, Claude proposed PR #114's edits while Conner was still finishing PR #113's git workflow, leaving uncommitted changes on a branch that needed to be checked out. Recovery cost a stash-and-re-branch dance. The rule that crystallized: one PR fully through the workflow (commit → push → PR → deploy → verify → merge → pull → branch off main) before the next edit lands in the working tree.
- [x] **New backlog item logged: dropped-player per-start projection display.** Surfaced during PR #114 verification when Montero (pre-fix) landed in `droppedPlayers`. Schedule grid only reads the global `projectionDetails` map; dropped players' details live on the player object as `pitcher.projDetails` and are never reached. Two fix options sketched in BACKLOG. Low urgency.

## ✅ Completed (session 26 — April 25, 2026)
- [x] **PR #111 — Roster-window bug for mid-week pickups (Wrobleski case).** Generalizes PR #81's `startDates ∩ days_on_team` intersection from dropped streamers to all currently-rostered pitchers. Mid-week pickups whose `startDates` included pre-roster dates were inflating Projected Starts (13/12 → 12/12 once corrected), Actual Starts, per-row `projFpts`, and the per-row Act FPTS column. Approach is "tag, don't drop": pre-acquisition starts stay in the data flow with a `preAcquisition: true` flag so the schedule grid can render them in muted styling (gray opp label, em-dash instead of ✓, gray FPTS, opaque `ProjectionTooltip` variant explaining "this start happened before you picked up this pitcher"). Backend tagging is post-hoc in `api/espn.py` after `my_team_pitchers_by_day` is populated, then recomputes effective `starts` count and subtracts pre-acq per-start projections from `projFpts` and `breakdown.total`. Frontend Act FPTS row total filters out pre-acq dates via the `startDates` flag; `pages/my-team.tsx` `actual` aggregate filters too. JSON shape stays backward-compatible (`preAcquisition` only present when true). Three downstream concerns deliberately deferred to backlog (lock-skip in projection.py, accuracy roster scope filter, dropped-player Act FPTS symmetry).
- [x] **Workflow lesson reinforced: deferred concerns belong in BACKLOG, not in the PR.** PR #111 had three obvious-once-you-look-at-them follow-ups (lock-skip, accuracy filter, dropped-player Act FPTS). Rather than scope-creep PR #111 into a lock-path refactor, all three were captured as backlog items with a one-line "why this is forward-only safe to defer" rationale each. The rule that crystallized: when scope creep tempts, ask "does the user lose anything visible if we ship without this?" — if no, defer with explicit notes; if yes, expand the PR.
- [x] **Diagnosed but not fixed: transaction-lag refetch leaves `starts_map` stale (Montero case).** Surfaced after PR #111 deployed when Conner added Keider Montero mid-day during the locked scoring period. Symptom: Montero appeared in roster_sps but his @CIN start tomorrow rendered with no green ✓ and the row showed `starts=0`, `projFpts=0.0`. Diagnosis: the existing transaction-lag block in `api/espn.py` (lines 154-181, from session 18 PR #73) updates `roster_entries` from the next-period mRoster but does NOT refresh `all_player_names`, `roster_team_map`, or `starts_map` — those were computed from the first fetch's player list, which doesn't include same-day pickups added during the locked window. Newly-added pitchers fall through `starts_map.get(name, {})` to the empty default. Bug has existed since session 18 PR #73; only surfaced now because Conner happened to add a player during the narrow locked-period window. Logged below as a known bug; fix promoted to next session priorities.

## ✅ Completed (session 25 — April 25, 2026)
- [x] **PR #108 — Cron actuals silent-failure hardening.** Long diagnostic detour traced an accuracy-dashboard data gap (Apr 23 showing 2 entries vs ~15 expected) to yesterday's cron run partially failing in `fetch_game_logs` — most per-player MLB Stats API calls returned HTTP 200 with empty splits, the `if games:` filter silently dropped them, the actuals block wrote a 380-byte 2-pitcher blob, and NX-write-once on `actual-all:2026-04-23` permanently locked it in. Three-layer fix: (1) `api/mlb.py` `fetch_game_logs` now returns `(data, stats)` where stats distinguishes 4 outcomes — `with_data`, `empty` (the silent-failure mode that was previously invisible), `http_errors`, `exceptions`. (2) `api/cron.py` invalidates `cache:mlb-stats:{year}` and `cache:game-logs:{year}` at the top of `lock_all_mlb_projections` to break the 24h-TTL/24h-cron race that was reusing stale partial data. (3) `ACTUALS_FLOOR = 4` skips NX-writes for any date with fewer than 4 entries — regular-season MLB days reliably have 10+ starts, so anything below 4 is almost certainly partial. Cron handler also now writes `cache:cron-summary:{date}` with 60-day TTL so post-hoc debugging survives Vercel Hobby's 1hr log retention. Verified in production: `gameLogStats: {requested: 519, with_data: 519, empty: 0, http_errors: 0, exceptions: 0}` — picture-perfect.
- [x] **PR #109 — Accuracy page display polish: lowercase names + missing matchup column.** Two bugs visible on the All MLB scope: player names rendered lowercase (`cade cavalli`) because they came from `actual-all:` keys which are accent-stripped and lowercased per session 24's slug normalization, and every row's matchup column showed `@?` because the `proj2all:` lock value's matchup sub-dict only stored `winProb` and `wpSource` (the projection.py path for `proj2:` already wrote `opponent`/`isHome`, but the cron path didn't). Fixes: `api/cron.py` matchup sub-dict gains `opponent` and `isHome` (now mirrors `projection.py`'s shape). `pages/accuracy.tsx` adds a `titleCase()` helper using `\b\w` regex applied to `s.player` rendering — idempotent for already-cased names so safe to apply universally regardless of scope. Forward-only on matchup: legacy `proj2all:` keys still show `@?` until they cycle out of the rolling window; new locks from the next 17:00 UTC cron onward populate correctly. Known imperfections logged to backlog: internal capitals (Mccullers/Degrom/Dejong) and 2-letter all-caps initials (Jt/Aj) — proper fix needs server-side `fullName` preservation.
- [x] **Diagnostic infrastructure pattern formalized.** `cache:cron-summary:{date}` joins the existing diagnostic surfaces in KV (`cache:daily:`, `proj2all:`, `actual-all:`, `projection-espn:`). Counter granularity in `gameLogStats` (with_data / empty / http_errors / exceptions split out) makes silent-failure modes spike visible in JSON without needing log retention. The "use KV as the debugger" pattern from session 24 is now a routine practice for any once-a-day cron-style write path.
- [x] **Decision: 24h cron cadence stays.** Discussed splitting projections (~9am CT for ESPN-confirmed probables) and actuals (~3am CT, after Pacific games end) into two cron jobs to use Hobby's 2-cron limit. Outcome: deferred. The win is small (slightly fresher actuals), the cost is real (refactor cron handler to accept a mode, update vercel.json), and the brittleness was the actual problem, not the schedule. After PR #108's hardening the case for splitting becomes purely UX-driven and can be revisited when there's a clearer reason.
- [x] **Workflow lesson reinforced: sandbox git operations are off-limits, even read-only.** Running `git status` / `git diff` from the sandbox left a `.git/index.lock` that blocked the user's terminal. Session 24's "Claude edits files; Conner drives git" rule extends to inspection commands, not just writes. Local validation in the sandbox is now restricted to `python3 ast.parse` and similar non-VCS-touching commands.

## ✅ Completed (session 24 — April 19, 2026)
- [x] **PR E — Accuracy page redesign: all-time aggregation + FA-leak fix** (PR #104). `api/accuracy.py` removed the matchup-period dropdown — endpoint now iterates all locked `proj2:` and `actual-all:` keys across the full season instead of a single period. My-Roster scope: pulls the current roster via `get_my_team_pitchers()` and filters projection keys to roster-slug matches, so FA projections no longer leak into the roster view. `pages/accuracy.tsx` dropped the period selector and updated copy to reflect all-time scope. Shipped alongside a UI tightening pass on the summary tiles.
- [x] **PR G — Silent game-logs API bug fix + accent-normalized slugs** (PR #105). Root cause: `/api/v1/people/{id}/stats?stats=gameLog&playerPool=all` silently returns empty (no error, no warning) when used as a bulk fetch. Switched `fetch_game_logs_for_players()` to per-player `/api/v1/people/{id}/stats?stats=gameLog` calls parallelized via `ThreadPoolExecutor` (12 workers). Added `_strip_accents()` helper and applied it inside `_to_slug()` so accented names (Luis García, José Berríos, etc.) now produce matchable slugs across MLB Stats API, ESPN Fantasy, and ESPN Forecaster sources. Diagnostic detour: since Vercel Hobby only retains logs for 1 hour, used KV keys as the observability surface — added `cache:cron-summary:{date}` write so we could inspect after-the-fact what the cron actually locked.
- [x] **PR F — MAE timeline chart with model milestone markers** (PR #106). New `components/MaeTimelineChart.tsx` renders a recharts `LineChart` on the All-MLB tab of the accuracy dashboard: solid lines for daily Skipper vs. ESPN MAE, dashed lines for 7-day trailing rolling averages (calendar-day window, sample-count weighted — not row-count, which would over-smooth on sparse dates), plus vertical `ReferenceLine` markers for model-changing deploys (Vegas W/L + xERA, Blended wOBA + weather, recentForm fix). Zero backend changes — `/api/accuracy` already attaches `espnFpts`/`espnError` to starts when `scope=="all"`, so all computation is client-side off the existing payload. Scoped to `scope === 'all'` only since ESPN projections are whole-MLB and don't map to a single fantasy roster. `recharts@^2` added as a dep (~90kb gz).
- [x] **Ops — CRON_SECRET rotated** after the old value showed up in a tracked `.env.vercel.prod` dump (caught by PR #98's `.gitignore` pattern). New secret written to Vercel prod env; cron verified green on the next tick.

## ✅ Completed (session 23 — April 18, 2026)
- [x] **PR #101 — ESPN empty-state polish on accuracy dashboard.** Two gaps from session 22's PR C closed: (1) `api/accuracy.py` early-return path now computes `espnSummary` when `scope === 'all'` even with no `proj2all:` keys — refactored ESPN lookup + summary math into two module-level helpers (`_fetch_espn_lookup`, `_compute_espn_summary`) shared between the early-return and normal paths. (2) `pages/accuracy.tsx` empty-state branch now wraps in a fragment and renders `EspnHeadToHead` above the empty card when `scope === 'all'` and `espnSummary` is non-null. Empty-state subtext surfaces ESPN lock count so users can see data accumulating before Skipper actuals exist.
- [x] **PR #102 — Weather Phase 2: wire `get_weather_factor()` into projection pipeline.** Session 20's weather module is now a live per-start multiplier alongside wOBA and park factors. Backend (`api/projection.py`): import added, live loop applies `weather_factor` to `start_proj`, `per_start_details` carries `weather`/`tempF`/`weatherSource`, lock path mirrors the same calc so locked FPTS equals live FPTS, and v2 locked breakdowns gain a new `"weather": { factor, tempF, source }` block for accuracy analysis. Frontend (`components/ProjectionTooltip.tsx`): `StartDetail` interface extended, single-start mode renders `Weather (72°F) ×1.012` row when `weatherSource === 'forecast'`, total mode adds a compact weather `FactorLabel` per start. Dome parks and default-fallback states hide the weather UI to avoid noise. All failure paths in `get_weather_factor` return factor=1.0, so Open-Meteo outages cannot break projections; 3hr Redis cache prevents API spam; ±5% cap enforced on the multiplier.
- [x] Direct folder access established via `request_cowork_directory` — Claude can now read/edit files in `~/Developer/the-skipper` without copy/paste. Git commit/push/deploy still run locally (sandbox can't write `.git/` reliably). Two PRs shipped in one session under the new workflow.

## ✅ Completed (session 22 — April 18, 2026)
- [x] **PR B — Daily cron locks ESPN Forecaster projections to KV** (PR #97). `lock_espn_projections()` added to `api/cron.py`: fetches today's MLB-confirmed probables, builds an accent-stripped name lookup, pulls the ESPN Forecaster for today only, reconciles each entry against the MLB set, and SETNX-writes confirmed matches to `projection-espn:{year}:{period}:{slug}:{date}` with a 60-day TTL. Skips placeholder entries (FPTS == 1.0) and orphans (ESPN pitcher not in MLB's confirmed set). First production run locked 29 new keys with 1 skipped_unconfirmed; idempotency verified on second run (locked_new: 0, locked_skipped_existing: 29). Cron handler now calls MLB and ESPN locking independently and returns a merged `{ok, mlb, espn}` summary so one failure doesn't hide the other's counters.
- [x] **PR #98 — Tighten `.gitignore` to prevent Vercel secret dumps** from ever being tracked. Added `.env.vercel*` pattern after `vercel env pull --environment=production` left `.env.vercel.prod` in the working tree during CRON_SECRET debugging. Previous pattern (`.env*.local`) didn't cover it.
- [x] **PR C — Accuracy dashboard ESPN MAE head-to-head** (PR #99). Backend: when `scope == "all"`, `api/accuracy.py` fetches `projection-espn:{season}:{period}:*` keys, attaches `espnFpts` / `espnError` to each matched start, and computes an `espnSummary` with ESPN MAE plus the apples-to-apples `skipperMaeOnIntersection` (Skipper's MAE recomputed on only the starts where ESPN also had a projection). Frontend: new `EspnHeadToHead` component renders three tiles (Skipper MAE, ESPN MAE, Advantage) above the existing summary when scope is All MLB. Winning side gets a soft-green highlight. Optional ESPN column added to the starts table. Roster scope unchanged. Deploy verified — head-to-head block awaits first completed actuals overlap (expected April 19 after 17:00 UTC cron).

## ✅ Completed (session 21 — April 18, 2026)
- [x] Spike: confirmed ESPN Fantasy API `kona_player_info` returns only full-season projections, not per-day (PRs #88, #89, #90, #91) — `statSourceId: 1` entries all have `statSplitTypeId: 0` and `scoringPeriodId: 0`. No per-day projection data in the Fantasy API at any point in the season.
- [x] Diagnostic endpoint probing ESPN Forecaster article (`/api/forecaster_probe`) — confirmed server-rendered HTML, one `<table>`, 60 `<tr>` rows, no JS hydration, all rostered pitchers present (PR #92)
- [x] PR A — `api/forecaster.py` scraper module + `/api/forecaster` diagnostic endpoint: fetches the ESPN Forecaster article, parses the projection table into per-start entries, returns 260 entries across all 30 teams for the 10-day rolling window (PR #93)
  - `_split_br()` / `_split_pitcher_cell()` helpers handle `<td><div>…<br>…</div></td>` wrapper variants
  - `PLACEHOLDER_FPTS_VALUE = 1.0` flagged via **exact-equality** check (not threshold) — Coors pitchers legitimately project negative, a `<= 1.0` check would wrongly flag them
  - `LOGO_TO_TEAM_OVERRIDES` maps non-standard ESPN slugs to canonical abbrevs
  - `beautifulsoup4==4.12.3` added to `requirements.txt`
- [x] Washington team abbreviation normalization — ESPN Forecaster logo filename is `was.png`, everywhere else uses `WSH`. Added `"was": "WSH"` to `LOGO_TO_TEAM_OVERRIDES` so team/opp join keys stay consistent downstream (PR #94)
- [x] `middleware.ts` matcher extended to exempt `/api/auth/*`, `/api/cron/*`, `/api/forecaster`, `/api/forecaster_probe`, `/api/espn_proj` from NextAuth — unblocks Vercel Cron (no session) and plain-curl verification of public endpoints. Protected endpoints (`/api/projection`, `/api/accuracy`, user-specific routes) stay behind the auth gate. (PR #95)

## ✅ Completed (session 20 — April 18, 2026)
- [x] Cache team wOBA factors with 24hr TTL under `cache:team-woba:{year}` (PR #83)
- [x] Refactored `get_team_woba` to use pure helper `_compute_team_woba_factors(splits, min_games, label)` (PR #84)
- [x] Added `get_team_woba_recent(season, days=14)` using MLB Stats API `byDateRange` statsType (PR #84)
- [x] Added `get_team_woba_blended(season, recent_days=14, recent_weight=0.35)` — parallel fetch via ThreadPoolExecutor, 65% season / 35% last-14-day (PR #84)
- [x] Fetcher switched from `get_team_woba` to `get_team_woba_blended` — same cache key, blended value now cached (PR #84)
- [x] New `api/weather.py` module — Open-Meteo client, 30-park `PARK_COORDS`, 8-park `DOME_PARKS`, temperature-only run environment factor (±5% cap, 50% dampened) (PR #85)
- [x] `get_weather_factor(park, date)` — dome override → cache lookup → Open-Meteo fetch → compute → 3hr TTL under `cache:weather:{park}:{date}`, graceful fallback to 1.0 on any failure (PR #85)
- [x] Diagnostic endpoint `/api/weather?park=X&date=Y` for production verification before wiring (PR #85)
- [x] Added `__pycache__/` and `*.pyc` to `.gitignore`

## ✅ Completed (session 19 — April 16, 2026)
- [x] Dropped streamers: count starts that happened while rostered (PR #81)
- [x] Dropped streamers: route through projection pipeline so per-start projections render in schedule grid (PR #81)
- [x] Backend intersects `startDates` with `days_on_team` — only counts rostered-window starts (PR #81)
- [x] Actual Starts and Projected Starts tiles now include dropped streamers in aggregation (PR #81)
- [x] Tile filters changed from `s.confirmed` to `s.date <= today || s.confirmed` — past starts always count (PR #81)
- [x] Rostered SPs tile excludes IL-slot players (PR #81)
- [x] ScheduleGrid past/today indicator shows green ✓ for any start that has happened or is happening (PR #81)

## ✅ Completed (session 18 — April 12, 2026)
- [x] espn.py refactor: split 1220-line monolith into projection.py, fetcher.py, espn.py (PR #73)
- [x] Factor contribution analysis on accuracy dashboard (PR #74)
- [x] Refresh button on accuracy page (PR #74)
- [x] Vegas moneyline win probability from ESPN scoreboard (PR #75)
- [x] Pythagorean win expectation model with Log5 + pitcher xERA adjustment (PR #75)
- [x] Per-start W/L scaling: team_win_prob × 0.57 starter share (PR #75)
- [x] Win probability shown in tooltip with Vegas/Pythagorean source badge (PR #75)
- [x] Daily cron job for all-MLB projection locking at noon CT (PR #76)
- [x] All-MLB actuals from game logs stored under actual-all: keys (PR #76)
- [x] Accuracy page: My Roster / All MLB scope toggle (PR #76)
- [x] CRON_SECRET env var for cron endpoint security (PR #76)
- [x] Cache team_win_data with 24hr TTL (PR #77)
- [x] Opponent starter xERA threaded through schedule → projection model (PR #77)
- [x] Schedule grid shows adjusted per-start projection instead of base rate (PR #77)
- [x] W/L impact shown in projection tooltip (PR #77)
- [x] Free Agents: sortable Act FPTS column (PR #77)
- [x] Free Agents: date column sort uses adjusted projection (PR #77)
- [x] Compact grid cells: indicator inline with opponent label (PR #77)
- [x] My Team: roster sorted by per-start quality (projFpts/starts) (PR #77)

## ✅ Completed (session 17 — April 12, 2026)
- [x] Color scheme refresh — midnight dark theme with Inter + JetBrains Mono (PR #71)

## ✅ Completed (session 16 — April 12, 2026)
- [x] Sidebar collapses on mobile (PR #69)
- [x] Top header gets hamburger menu on small screens (PR #69)

## ✅ Completed (session 15 — April 12, 2026)

- [x] ESPN stat ID mapping verified (10/10 confidence) — W/L corrected to stat 53/54 (PR #66)
- [x] `ESPN_PITCHING_STAT_IDS` constant added to `espn.py` (PR #66)
- [x] Actual per-stat extraction in `get_actual_fpts()` — all 9 scoring stats from ESPN raw_stats (PR #66)
- [x] `actual_stats` stored in daily cache alongside fpts/saves/bench/my_team (PR #66)
- [x] Accuracy dashboard: `api/accuracy.py` endpoint + `pages/accuracy.tsx` page (PR #67/68)
- [x] Summary tiles, per-stat MAE bar chart with bias, expandable per-start comparison table
- [x] Added to sidebar navigation (PR #67/68)
- [x] Old daily caches cleared to re-populate with actual_stats

## ✅ Completed (session 14 — April 11, 2026)

- [x] V2 projection locking — `set_locked_projection_v2()` stores full JSON breakdown per start (PR #64)
- [x] V2 key schema: `proj2:{season}:{period}:{player-slug}:{date}` → JSON (PR #64)
- [x] V1 float locking preserved for frontend compatibility (PR #64)

## ✅ Completed (session 13 — April 11, 2026)

- [x] Layer 2: Recent form weighting (PR #60)
- [x] Layer 3: Park factors (PR #60)
- [x] Projection tooltip with total + per-start breakdown modes (PR #60)
- [x] Renamed `option_b_inputs` → `projection_inputs` throughout (PR #60)

## ✅ Completed (session 12 — April 11, 2026)

- [x] Savant-powered hybrid projection model (PR #56)
- [x] All caching infrastructure — Savant, MLB Stats, daily FPTS (PRs #57-59)
- [x] Dropped streamer detection (PRs #52-53)
- [x] KNOWLEDGE.md, tile redesign, bench/IL normalization (PRs #49-51, 54-55)
- [x] Response time reduced from ~4.8s to ~2.1s

## ✅ Completed (sessions 1-11)

See CHANGELOG.md for full history of PRs #1-#47.

---

## 💡 Future ideas

- Trade analyzer with forward-looking schedule context
- Waiver wire rankings personalized to roster needs and matchup context
- Live game decision engine (real-time starts limit optimization)
- Schedule advantage alerts (2-3 week lookahead for favorable/unfavorable stretches)
- Opponent scouting report per matchup period
- Push notifications for pitcher changes, injury news, prospect call-ups
- Multi-user support / league sharing
- Mobile app (React Native)
- Pay for a proper probable pitchers data source once serving real users

---

## 🔧 Environment variables

All set in both `.env.local` (local) and Vercel dashboard (production):

| Variable | Purpose |
|---|---|
| `APP_USERNAME` | Login username |
| `APP_PASSWORD` | Login password |
| `NEXTAUTH_SECRET` | JWT encryption key |
| `NEXTAUTH_URL` | `https://the-skipper-iota.vercel.app` |
| `ESPN_LEAGUE_ID` | Fantasy league ID (77651433) |
| `ESPN_SEASON` | `2026` |
| `ESPN_S2` | ESPN auth cookie |
| `ESPN_SWID` | ESPN auth cookie |
| `ESPN_TEAM_ID` | Your team number (6) |
| `ESPN_STARTS_LIMIT` | Weekly pitcher starts limit (12) |
| `ANTHROPIC_API_KEY` | Claude API key |
| `KV_REST_API_URL` | Upstash Redis REST URL |
| `KV_REST_API_TOKEN` | Upstash Redis REST token |

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
**Git workflow:** Feature branches → PR → squash merge. Prefixes: `fix:`, `feat:`, `chore:`, `docs:`

---

## 📚 Reference

All API reference documentation, architecture decisions, league settings, and development workflow are maintained in **[KNOWLEDGE.md](KNOWLEDGE.md)** — the single source of truth for technical reference.
