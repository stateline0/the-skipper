# The Skipper — Changelog

---

## Session 12 — April 11, 2026

ESPN API deep-dive, projection model upgrade to Savant-powered hybrid, tile redesign, dropped streamers, caching infrastructure. Eleven PRs shipped (#49–#59).

### Key learnings this session
- ESPN `lineupSlotId` is per-day accurate — verified 98 data points across 7 days × 14 players, zero mismatches against ESPN website screenshots.
- `player.injured` (boolean) is the reliable IL signal. `playerPoolEntry.injuryStatus` returns empty `""` for all rostered players.
- `eligibleSlots` determines SP vs RP (stable). `lineupSlotId` is a daily lineup decision — never use for position classification.
- Bench status is irrelevant to The Skipper — daily lineup management, not a player attribute.
- `new Date().toISOString().slice(0,10)` returns UTC date — causes wrong day for late-evening users in US time zones. Use local date construction instead.
- Baseball Savant CSV endpoints (`&csv=true`) are public, no auth, return rich Statcast data. CSV has BOM prefix and combined `"last_name, first_name"` column.
- When a file accumulates too many patches, do a clean rewrite rather than more patches.
- Savant xERA and xBA are more predictive than raw ERA/BA — they remove BABIP luck and sequencing variance.
- W/L should be discounted 50% in projections — too team-dependent (run support, bullpen quality).
- Caching static data (2025 stats) permanently and current data with 24hr TTL cuts response time by 50%+.
- `cache_set` must be defined at module top level in `kv.py` — indentation errors silently hide functions from importers.
- When importing new functions, add them to the top-level import line — runtime imports inside functions can fail in Vercel's module loading.

### Projection sequencing + bench/IL normalization (PR #49)
- Moved transaction lag re-fetch before `option_b_inputs`
- Removed all bench/IL special-casing from projections — all pitchers treated identically
- `get_slot_label()` and `get_status()` now use `player.injured` + `eligibleSlots`
- Added `position` field (SP/RP) independent of IL slot
- Fixed IL players missing from My Team starters grid
- Created `KNOWLEDGE.md` with confidence-rated ESPN API reference

### Docs update (PR #50)
- Updated BACKLOG and CHANGELOG, replaced inline API reference with KNOWLEDGE.md pointer

### Tile redesign (PR #51)
- ACTUAL STARTS: past/today confirmed starts for SP-position players
- PROJECTED STARTS: actual + future starts (replaces SCHEDULED)
- ROSTERED SPs: SP-position count only (was counting all pitchers)
- Fixed UTC date bug in tile calculation — now uses local time

### Dropped streamers (PRs #52, #53)
- `get_actual_fpts()` tracks which pitchers were on our team each past day
- Detects players dropped mid-period by comparing past vs current roster
- David Peterson appears with EX badge and -2.0 Act FPTS from his starts
- Sort order: active SPs → EX (dropped) → IL
- Clean rewrite of `my-team.tsx` to fix accumulated patch bugs

### Baseball Savant data fetcher (PR #54)
- `api/savant.py`: fetches expected stats, Statcast leaderboard, pitch arsenal
- Public CSV endpoints — no auth, no scraping
- Verified: 250 pitchers with expected stats, 144 with Statcast data

### Docs with model roadmap (PR #55)
- Full 5-layer projection model architecture documented in BACKLOG
- Savant data source documented in KNOWLEDGE.md

### Savant-powered hybrid projection model (PR #56)
- H per start → xBA × batters faced (removes BABIP luck)
- ER per start → xERA × (IP/9) (removes sequencing luck)
- K, BB, HBP, IP unchanged from MLB Stats API (skill-based)
- W/L discounted 50% (too team-dependent)
- Falls back to counting-stat model when Savant data unavailable
- Notable changes: Gavin Williams 13.7→10.2, Shane Baz 6.5→8.3, Dylan Cease 12.7→13.9

### Savant data caching (PR #57)
- 2025 Savant data cached permanently in Upstash KV
- 2026 Savant data cached with 24hr TTL
- `cache_get()` and `cache_set()` added to `api/kv.py`

### MLB Stats API caching (PR #58)
- Extracted `fetch_season_stats` to top-level function
- 2025 MLB stats cached permanently, 2026 with 24hr TTL
- Uncached ~4.5s → cached ~2.3s

### Daily actual FPTS caching (PR #59)
- Completed days cached permanently as `cache:daily:{date}`
- Caches unfiltered data (all league pitchers) so cache works for any player set
- Today never cached (live games)
- Performance: first load ~4.4s → cached ~2.1s

---

## Session 11 — April 10, 2026

Upstash KV locked projections, full-name pitcher matching, bench player start fix, and multiple bug fixes. Seven PRs shipped (#41–#47).

### Key learnings this session
- Vercel removed native KV — Upstash for Redis is the direct replacement, same `upstash-redis` Python library, same REST API pattern.
- Upstash Eviction must be OFF for projection storage — eviction silently deletes keys when storage fills up.
- Redis NX flag (`set key value nx=True`) is the correct pattern for write-once locks.
- Key schema design matters: `proj:{season}:{period}:{slug}:{date}` makes prefix queries trivial.
- Last-name-only pitcher matching was fragile — full-name matching eliminates surname collisions.
- `git reset --hard origin/main` is the correct fix when local main diverges from origin after a squash merge.

### Upstash KV infrastructure (PR #41, #42)
- `api/kv.py`: new module with `get_locked_projection()`, `set_locked_projection()` (NX flag), `get_all_locked_projections()`
- `api/espn.py`: locks `fpts_per_game` into KV for each past/today start
- Frontend: `lockedProjections` wired through state, cache, and ScheduleGrid

### Full-name probable pitcher matching (PR #43)
- Replaced last-name-only key with `full_name.strip().lower()` throughout `mlb.py`
- Fixes Shane Baz and Shane Smith probable pitcher detection

### Bench player starts fix (PR #46)
- Bench player `startDates` filter changed from `< today_str` to `<= today_str`

---

## Session 10 — April 9, 2026

Opponent quality adjustment using team wOBA factors. One PR shipped (#39).

### Opponent quality adjustment
- `api/mlb.py`: `get_team_woba()` — fetches team hitting stats, computes wOBA factors relative to league average
- Per-start opponent adjustment applied in `get_projected_fpts()`
- RPs excluded from matchup adjustment

---

## Session 9 — April 9, 2026

Sortable free agents table, SP slot filter fix, FA actual FPTS, and projection model fixes. One PR shipped (#37).

### Sortable free agents table
- Click any column header to sort with ↓/↑ indicators
- Checkbox toggles via name-based lookup instead of index

### Fix: SP slot filter on free agent fetch
- Added `filterSlotIds: [14]` — free agent count jumped from 29 to 100

### Actual FPTS for free agents
- `get_actual_fpts()` now fetches stats for FA names alongside roster names

### Projection model fixes
- Minimum sample size threshold: 3 starts for SPs, 5 appearances for RPs

---

## Session 8 — April 8, 2026

FA projections, per-start cell projections, actual FPTS column. One PR shipped (#35).

### Free agent projections
- Same Option B blended model as roster players

### Per-start projections in schedule grid cells
- Future start cells show per-start projection below badge
- Past start cells show `(proj: +X.X)` below actual FPTS

### Actual FPTS column
- Sums actual points earned per pitcher across the period

---

## Session 7 — April 7, 2026

Roster transaction lag fix, Option B projected FPTS model, relievers section, period dropdown fixes.

### Roster transaction lag fix
- Detect `in_progress`/`final` games → re-fetch at `scoringPeriodId + 1`

### Option B projected FPTS model
- Blended 2025/2026 MLB Stats API season stats
- League scoring formula: IP×3, K×1, H×-1, BB×-1, ER×-2, HB×-1, W×+5, L×-5, SV×+5

### Relievers section
- Separate grid with saves tracking, bench-day strikethrough

### Period dropdown + cache version system
- Auto-fetch on period change, `CACHE_VERSION` pattern

---

## Sessions 1-6 — March 27–30, 2026

Initial build: auth, layout, ESPN API integration, schedule grid, probable pitchers, matchup period dropdown, actual FPTS, bench/IL distinction.

---

## Pre-session baseline

Initial working prototype with ESPN API connection, single-page step wizard, hand-rolled auth, Claude AI analysis.
