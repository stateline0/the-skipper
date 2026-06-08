# Hitter projection model — phased roadmap

Companion to `HITTERS_WIREFRAME.md`. That doc explored *what a hitter view looks
like*; this one is *how we project hitters*, built to mirror the proven pitcher
model (`api/projection.py`) and reuse its data/infra.

## Core design — project a stat vector, not a scalar

The pitcher model multiplies a single FPTS number by run-environment factors.
The hitter model instead carries a **per-game stat vector**
`{pa, ab, h, 1b, 2b, 3b, hr, r, rbi, bb, hbp, sb, cs, so}` through the factor
chain and collapses to FPTS only at the end, by dotting the vector with the
league scoring dict (`apply_hitter_formula`).

Why:
- Per-stat factors the end goal needs (HR-specific park, wind-for-HR, contact
  vs. power platoon splits) can only apply at the stat level.
- Points-vs-categories becomes trivial — a points league dots the vector with
  the scoring weights; a category league reads the vector directly.

Per-game composition (each rostered game day):

```
game_vector = base_vector                    # season+recent blend, Savant-delucked
            ⊙ platoon_split      (per-stat)   # vs LHP/RHP
            ⊙ opp_pitcher_qual   (scalar)     # opposing SP xERA/K%/xwOBA-against
            ⊙ bvp_regressed      (scalar)     # batter-vs-this-pitcher, regressed
            ⊙ park_factor        (per-stat)   # HR-park vs hits/runs-park
            ⊙ weather_wind       (per-stat)   # temp all-stats + wind→HR
            ⊙ volume             (pa-scalar)  # lineup-spot PA / team pace
game_fpts   = dot(game_vector, SCORING)
period_proj = Σ game_fpts over rostered game days
```

Park/weather factors apply **directly** (>1.0 = more offense = good for the
hitter) — the opposite of the pitcher model's `env_to_pitcher_mult()` inversion.

## Phases (each ships independently, accuracy-tracked)

| Phase | Adds | Status |
|---|---|---|
| 0 | Scoring detection from ESPN `mSettings`; keep hitter roster entries; hitter season-stats fetcher; pitcher handedness | **done** (dynamic `mSettings` scoring with sanity-check fallback to a verified default + `?debug=scoring`; `fetch_season_stats_hitting`; hitter roster parse; handedness + Savant batter mode deferred to their phases) |
| 1 | Baseline per-game stat vector from season-rate stats, year-blended by PA | **done** (`projection_hitter.py`) |
| **Wire-in** | `/api/hitters` endpoint + Hitters page consuming real roster/schedule/projections (falls back to mock) | **done** |
| 2 | Savant expected-stat de-luck (xBA/xSLG) | **done** (`fetch_expected_stats_batter` + `apply_savant_hitter`: expected H = xBA·AB, expected TB = xSLG·AB) |
| 3 | Recent form (weighted last ~15 games, 60/40) | **done** (`compute_recent_form_hitter` + `fetch_game_logs_hitting`, blended into `projPerGame`) |
| 4 | Park factor (direct, per-game) | **done** (`get_park_factor` applied un-inverted) |
| 5 | Weather (temp; reuse `get_weather_factor`) | **done** (precomputed per host-park/future-date, applied direct) |
| 6 | Platoon (L/R) splits vs the probable starter | **done** (`platoon_multiplier` + per-day factor stack; per-day detail popover) |
| 7 | Opposing-pitcher quality (xwOBA-against) | **done** (`opp_pitcher_multiplier` vs league avg; + `fetch_probable_pitcher_ids` → 100% starter-id/handedness coverage) |
| 8 | Regressed batter-vs-pitcher history | planned |
| 9 | PA / lineup-spot volume (beyond pitchers) | planned |
| 10 | Per-stat park + wind-for-HR (beyond pitchers) | planned |

**End goal:** all layers live; each rostered game day locks a v2 breakdown to
`proj2h:{season}:{period}:{slug}:{date}`; a hitter warm-cron precompute mirrors
`api/warm.py`; `pages/hitters.tsx` swaps mock data for the real model.

## Shipped to date (PRs #132–#143)

The model is **fully matchup-aware**, end-to-end, with actual/live tracking.

**Core model — `api/projection_hitter.py`**
- Stat-vector core: `STAT_KEYS`, `apply_hitter_formula`, `per_game_vector`,
  `blend_vectors`, `pa_blend_weight`, `apply_factors`.
- Scoring: `DEFAULT_HITTER_SCORING` (verified TB-based) + `parse_hitter_scoring`
  (reads `mSettings` with a sanity-check fallback). `ESPN_HITTING_STAT_IDS`
  confirmed against the live league via `?debug=scoring`.
- Phase 2 de-luck: `apply_savant_hitter` (xBA/xSLG).
- Phase 3 recent form: `compute_recent_form_hitter` / `score_game_log`
  (60/40 season/recent).
- Phase 6 platoon: `platoon_multiplier`. Phase 7 opp-SP: `opp_pitcher_multiplier`.
- `get_projected_hitter_fpts(...)` — full entry point; `actuals_from_logs`
  scores game logs by category (the FA-actuals source).
- `api/test_projection_hitter.py` — 22 pure-Python tests.

**Data — `api/fetcher.py` / `api/mlb.py` / `api/savant.py`**
- `fetch_season_stats_hitting`, `load_hitter_stats`, `load_hitter_game_logs`,
  `load_hitter_splits`, `load_player_hands` (by-ID via `/people/{id}`),
  `fetch_expected_stats_batter`, `fetch_statcast_stats_batter`,
  `fetch_probable_pitcher_ids`, `get_park_factor`/`get_weather_factor` (direct).

**Endpoint — `api/hitters.py`**
- Parses hitter roster (slots 0–12), derives game days from the shared
  schedule, runs the model, applies the **per-day matchup stack** (platoon →
  opp-SP → park → weather) in `_build_days`, and captures **actual/live FPTS**
  (ESPN applied total for roster; game-log-by-category for FAs, validated vs
  ESPN). Returns `rosterHitters` + `freeAgentHitters` with per-day cells,
  `factors[]`, `actual`/`status`, season line, and `advanced` block. Cache v23.
  Debug endpoints: `?debug=scoring|savant|platoon`.

**Frontend — `pages/hitters.tsx`, `pages/free-agents.tsx`,
`components/HitterTables.tsx`**
- Hitters page (real data, matchup banner) + FA Pitchers/Hitters toggle.
- Sortable Schedule/Stats tables; advanced Savant columns with league avgs.
- Per-day **detail popover** (`Base → factors → Proj → Actual`); cells show
  bold **actual** + muted `proj` for played games, projection + edge arrow for
  upcoming, `DNP` for missed; `● LIVE` for in-progress. `Act`/`Proj` totals.

### Not yet built
- **Phase 8** regressed BvP, **Phase 9** PA/lineup volume, **Phase 10** per-stat
  park + wind-for-HR (the "beyond pitchers" extras).
- **All-MLB hitter coverage** (the one accuracy gap): hitter locks/actuals are
  written only from the Hitters page, so the dashboard covers the owner's roster,
  not all MLB. The fix is a cron pass mirroring the pitcher all-MLB lock.
  Blockers found while scoping (session 35): `fetch_season_stats_hitting`
  discards each split's team (no hitter→team map to know who plays today), and
  `fetch_game_logs_hitting` is per-player ("not all of MLB"). See BACKLOG.
- **Live freshness:** live totals refresh on the ~30-min payload cache; a
  fresh-on-gameday refresh (like the pitcher page) would make them real-time.

## Accuracy (separate from pitchers) — SHIPPED (session 34, PRs #147–#150)

The hitter model gets its **own** MAE series — never blended into the pitcher
numbers. Pipeline:
- **`proj2h:{season}:{period}:{slug}:{date}`** — per-game projection frozen at
  game start (`status != "scheduled"`, the timezone-independent "game began"
  signal), NX. Stores `fpts` + `base` + the factor stack + `matchup` + `model` +
  `name`. (kv.py `set_locked_hitter_projection` / `get_all_locked_hitter_projections`.)
- **`acth:{date}` = `{slug: {fpts, stats}}`** — actuals from the validated
  game-log scoring (`actuals_with_stats_from_logs`). A game-log row means the
  hitter **played**, so **DNP games are excluded for free** (a 0-fer is kept; a
  no-show has no row). Written read-merge-write.
- **`kind=hitter`** path in `api/accuracy.py` (`get_hitter_accuracy_data`) matches
  `proj2h:` ↔ `acth:` by slug+date → FPTS MAE / max / min / bias / directional.
  Deliberately simpler than pitchers: **no factor counterfactuals** (the model is
  FPTS-centric — no per-stat projection to ablate), **no ESPN overlay** (no
  `projection-espn:` hitter feed), and **no roster filter** (the Accuracy page is
  all-MLB-only as of session 35).
- **Frontend:** a Pitchers/Hitters toggle on `pages/accuracy.tsx`; Hitters render
  a Skipper-only MAE timeline (`MaeTimelineChart kind="hitter"`) and an expandable
  per-game `base × factors = proj` reconciler + actual line.

## Data risks to validate (Phase-0 spikes)

1. **Savant `?type=batter`** — never exercised; confirm columns before relying
   on it (Phase 2 falls back to MLB-Stats actuals).
2. **Platoon & BvP splits** — confirm MLB `statSplits` returns usable bulk data;
   else derive platoon from handedness composition. Phases 6/8 degrade to no-ops.
3. **Lineup feed** — projected daily lineups for Phase 9 volume; fall back to
   season lineup-slot tendency.
4. **`ESPN_HITTING_STAT_IDS`** — verify the statId→key map against a live
   `mSettings` dump (the parser logs unmapped hitting-range IDs).
