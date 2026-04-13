# The Skipper — Changelog

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
