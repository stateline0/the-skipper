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
| 0 | Scoring detection from ESPN `mSettings`; keep hitter roster entries; hitter stat/log fetchers; verify Savant `?type=batter`; pitcher handedness | **partial — scoring parser done** |
| 1 | Baseline per-game stat vector from season-rate stats, year-blended by PA | **done (`projection_hitter.py`)** |
| 2 | Savant expected-stat de-luck (xBA/xSLG/xwOBA) | planned |
| 3 | Recent form (weighted last ~12–15 games, 60/40) | planned |
| 4 | Park factor (direct, per-game) | planned |
| 5 | Weather (temp; reuse `get_weather_factor`) | planned |
| 6 | Platoon (L/R) splits vs the probable starter | planned |
| 7 | Opposing-pitcher quality (xERA/K%/xwOBA-against) | planned |
| 8 | Regressed batter-vs-pitcher history | planned |
| 9 | PA / lineup-spot volume (beyond pitchers) | planned |
| 10 | Per-stat park + wind-for-HR (beyond pitchers) | planned |

**End goal:** all layers live; each rostered game day locks a v2 breakdown to
`proj2h:{season}:{period}:{slug}:{date}`; a hitter warm-cron precompute mirrors
`api/warm.py`; `pages/hitters.tsx` swaps mock data for the real model.

## What landed in this PR (Phases 0–1)

- `api/projection_hitter.py` — the stat-vector core:
  - `STAT_KEYS`, `DEFAULT_HITTER_SCORING`, `ESPN_HITTING_STAT_IDS`
  - `parse_hitter_scoring(msettings)` — Phase 0 scoring detection (safe default)
  - `per_game_vector`, `blend_vectors`, `pa_blend_weight` — Phase 1 baseline
  - `apply_hitter_formula` — vector → FPTS
  - `apply_factors(vector, per_stat, scalar)` — identity hook so Phases 2–10
    slot in without reshaping the pipeline
  - `get_projected_hitter_fpts(...)` — baseline entry point
- `api/test_projection_hitter.py` — 11 pure-Python tests (no network) covering
  singles derivation, the scoring dot product (incl. no double-count with "h"),
  the PA ramp, year blend, factor application, and end-to-end projection.

Not yet wired into `api/espn.py` or the frontend — that lands with the data
fetchers in a follow-up, since it touches the live pitcher path and needs the
Phase-0 data spikes (Savant batter mode, MLB hitting splits) verified against
live data first.

## Accuracy (separate from pitchers)

The hitter model gets its **own** MAE series — never blended into the pitcher
numbers — via a `kind=hitter` path in `api/accuracy.py` that reads `proj2h:`
locks, uses the hitter stat list, and computes counterfactuals for the hitter
factor stack. **No ESPN head-to-head overlay** for hitters: there's no
`projection-espn:` hitter feed to compare against, so the hitter view shows
model-vs-actual MAE only. A Pitchers/Hitters toggle on `pages/accuracy.tsx`
swaps the page between the two.

## Data risks to validate (Phase-0 spikes)

1. **Savant `?type=batter`** — never exercised; confirm columns before relying
   on it (Phase 2 falls back to MLB-Stats actuals).
2. **Platoon & BvP splits** — confirm MLB `statSplits` returns usable bulk data;
   else derive platoon from handedness composition. Phases 6/8 degrade to no-ops.
3. **Lineup feed** — projected daily lineups for Phase 9 volume; fall back to
   season lineup-slot tendency.
4. **`ESPN_HITTING_STAT_IDS`** — verify the statId→key map against a live
   `mSettings` dump (the parser logs unmapped hitting-range IDs).
