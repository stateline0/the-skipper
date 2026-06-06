"""
api/projection_hitter.py — Projection model for hitter fantasy points.

Companion to api/projection.py (the pitcher model). Unlike that model — which
scales a single FPTS scalar by run-environment factors — the hitter model
carries a per-game **stat vector** through the factor chain and collapses to
FPTS only at the very end, by dotting the vector with the league scoring dict.

Why a stat vector instead of a scalar:
  * Per-stat factors the roadmap needs (HR-specific park, wind-for-HR, contact
    vs. power platoon splits) can only be applied at the stat level.
  * Points-vs-categories becomes trivial: a points league dots the vector with
    the scoring weights; a category league can read the vector directly.

This file currently implements the foundation (see PHASE markers):
  * Phase 0 — scoring detection from ESPN mSettings (+ a safe default).
  * Phase 1 — baseline per-game stat-vector projection from season-rate stats,
              year-over-year blended by plate appearances.

The matchup / park / weather / volume layers (Phases 2–10 in the plan) are not
applied yet, but the per-game composition routes through `apply_factors()` with
identity multipliers so those layers slot in without reshaping the pipeline.
"""

import unicodedata


# ── Stat vector keys ──────────────────────────────────────────────────
# The canonical per-game hitter stat vector. "h" (total hits) and the
# per-type hit keys (1b/2b/3b/hr) are BOTH carried so a league that scores
# "any hit" and one that scores hit types separately are both expressible
# without double counting — the scoring dict only references the keys it uses.
STAT_KEYS = (
    "pa", "ab", "h", "1b", "2b", "3b", "hr",
    "r", "rbi", "bb", "hbp", "sb", "cs", "so",
)


# ── League scoring formula (fallback) ─────────────────────────────────
# Used when ESPN mSettings can't be parsed. A common points-league hitting
# config that scores hit types separately (so it never also scores "h").
# parse_hitter_scoring() overrides this with the league's actual weights.
DEFAULT_HITTER_SCORING = {
    "1b":  1,
    "2b":  2,
    "3b":  3,
    "hr":  4,
    "r":   1,
    "rbi": 1,
    "bb":  1,
    "hbp": 1,
    "sb":  1,
    "cs": -1,
    "so": -1,
}


# ── ESPN fantasy-baseball hitting stat IDs → our stat keys ─────────────
# ESPN `mSettings.scoringSettings.scoringItems[]` entries carry a numeric
# `statId` and a points value. This maps the hitting stat IDs we score.
#
# NOTE: these IDs are ESPN's documented flb hitting stat IDs, but they MUST be
# verified against a live mSettings dump for this league before Phase 1 ships
# (a Phase-0 spike). parse_hitter_scoring() logs any statId it can't map so an
# unexpected configuration is visible rather than silently dropped.
ESPN_HITTING_STAT_IDS = {
    1:  "h",     # hits (any)
    3:  "2b",    # doubles
    4:  "3b",    # triples
    5:  "hr",    # home runs
    7:  "1b",    # singles
    9:  "bb",    # walks
    11: "hbp",   # hit by pitch
    17: "r",     # runs
    18: "rbi",   # runs batted in
    20: "sb",    # stolen bases
    21: "cs",    # caught stealing
    27: "so",    # strikeouts (batter)
}

# Plate-appearance ramp: weight toward the current season scales linearly to
# 1.0 at this PA count (≈ a third of a season — hitters stabilize faster than
# pitcher peripherals but rate stats still need a sample). Mirrors the IP ramp
# in projection.py.
PA_THRESHOLD = 200.0
MIN_GAMES = 10  # below this, a season-rate vector isn't trustworthy


def strip_accents(s: str) -> str:
    """Normalize accented characters for name matching across data sources."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).lower()


# ── Phase 0: scoring detection ─────────────────────────────────────────

def parse_hitter_scoring(msettings: dict) -> dict:
    """Build a hitter SCORING dict from an ESPN league's mSettings payload.

    Looks at scoringSettings.scoringItems[], maps each hitting statId via
    ESPN_HITTING_STAT_IDS, and reads its points value (preferring an explicit
    pointsOverrides entry, falling back to `points`). Returns DEFAULT_HITTER_
    SCORING if nothing usable is found, so the caller always gets a workable dict.

    Unmapped statIds (e.g. pitching stats, or IDs we don't model) are skipped;
    a one-line summary of unmapped hitting-range IDs is printed for visibility.
    """
    try:
        items = (
            msettings.get("settings", {})
            .get("scoringSettings", {})
            .get("scoringItems", [])
        )
    except AttributeError:
        items = []

    scoring = {}
    unmapped = []
    for item in items or []:
        stat_id = item.get("statId")
        key = ESPN_HITTING_STAT_IDS.get(stat_id)
        if key is None:
            # Only flag IDs in the hitting range so pitching items don't spam.
            if isinstance(stat_id, int) and 0 <= stat_id <= 35:
                unmapped.append(stat_id)
            continue
        # pointsOverrides is keyed by scoring-period type; take any value.
        overrides = item.get("pointsOverrides") or {}
        pts = next(iter(overrides.values()), None) if overrides else item.get("points")
        if pts is None:
            continue
        scoring[key] = pts

    if unmapped:
        print(f"[projection_hitter.py] Unmapped hitting statIds in mSettings: "
              f"{sorted(set(unmapped))} — verify ESPN_HITTING_STAT_IDS")

    if not scoring:
        print("[projection_hitter.py] No hitter scoring parsed from mSettings; "
              "using DEFAULT_HITTER_SCORING")
        return dict(DEFAULT_HITTER_SCORING)

    return scoring


def apply_hitter_formula(vector: dict, scoring: dict) -> float:
    """Collapse a per-game stat vector to FPTS by dotting with the scoring dict.

    Only keys present in `scoring` contribute, so the same vector works for a
    league that scores total hits ("h") and one that scores hit types
    (1b/2b/3b/hr) — whichever keys the league configured.
    """
    return sum(vector.get(stat, 0.0) * pts for stat, pts in scoring.items())


# ── Phase 1: baseline per-game vector ──────────────────────────────────

def per_game_vector(stat: dict, games: int) -> dict:
    """Per-game hitter stat vector from MLB Stats API season totals.

    `stat` is an MLB Stats API hitting `stat` object (group=hitting). Returns
    None when below MIN_GAMES, so the caller can fall back to the other season.
    """
    if not games or games < MIN_GAMES:
        return None

    def g(key):
        try:
            return float(stat.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    h   = g("hits")
    dbl = g("doubles")
    tpl = g("triples")
    hr  = g("homeRuns")
    singles = max(0.0, h - dbl - tpl - hr)

    raw = {
        "pa":  g("plateAppearances"),
        "ab":  g("atBats"),
        "h":   h,
        "1b":  singles,
        "2b":  dbl,
        "3b":  tpl,
        "hr":  hr,
        "r":   g("runs"),
        "rbi": g("rbi"),
        "bb":  g("baseOnBalls"),
        "hbp": g("hitByPitch"),
        "sb":  g("stolenBases"),
        "cs":  g("caughtStealing"),
        "so":  g("strikeOuts"),
    }
    return {k: v / games for k, v in raw.items()}


def blend_vectors(v_cur: dict, v_prev: dict, w_cur: float) -> dict:
    """Year-over-year blend of two per-game vectors by current-year weight.

    Either side may be None (insufficient sample); falls back to the other.
    """
    if v_cur is None and v_prev is None:
        return {k: 0.0 for k in STAT_KEYS}
    if v_cur is None:
        return dict(v_prev)
    if v_prev is None:
        return dict(v_cur)
    return {k: v_cur.get(k, 0.0) * w_cur + v_prev.get(k, 0.0) * (1.0 - w_cur)
            for k in STAT_KEYS}


def pa_blend_weight(pa_cur: float) -> float:
    """Linear ramp of current-season trust from 0 PA → PA_THRESHOLD."""
    if pa_cur <= 0:
        return 0.0
    return min(1.0, pa_cur / PA_THRESHOLD)


def apply_factors(vector: dict, per_stat: dict = None, scalar: float = 1.0) -> dict:
    """Apply per-stat multipliers and a scalar to a stat vector.

    Phase 1 calls this with identity (no factors). Later phases pass:
      * per_stat — e.g. {"hr": 1.12, "h": 0.97} for park/wind/platoon-by-stat
      * scalar   — e.g. opposing-pitcher-quality or regressed-BvP multiplier
    so the per-game composition pipeline doesn't change as layers are added.
    """
    per_stat = per_stat or {}
    return {k: vector.get(k, 0.0) * per_stat.get(k, 1.0) * scalar for k in vector}


def get_projected_hitter_fpts(
    hitters: list,
    scoring: dict = None,
    stat_current: dict = None,
    stat_previous: dict = None,
    season: int = 2026,
    period: int = 1,
) -> tuple:
    """Baseline (Phase 1) hitter projections.

    Args:
        hitters: list of {"name", "team", "gameDates": [...]} dicts. gameDates
                 is the list of dates this hitter is rostered to play in the
                 matchup period (analogue of pitcher startDates).
        scoring: league hitter scoring dict (from parse_hitter_scoring). Falls
                 back to DEFAULT_HITTER_SCORING.
        stat_current / stat_previous: {name_lower: mlb_hitting_stat_obj} for the
                 current and previous seasons.

    Returns (projections, details):
        projections — {name: {"projFpts": period total, "projPerGame": float,
                              "blendWeight": float, "games": int}}
        details     — {name: {"seasonBase", "blendWeight", "perGame", "games",
                              "total"}} breakdown for the frontend tooltip.

    Phases 2–10 (Savant de-luck, recent form, park, weather, platoon,
    opposing-pitcher, BvP, volume) layer on top via apply_factors() per game.
    """
    scoring = scoring or dict(DEFAULT_HITTER_SCORING)
    stat_current = stat_current or {}
    stat_previous = stat_previous or {}

    projections = {}
    details = {}

    for h in hitters:
        name = h.get("name", "")
        name_key = strip_accents(name)
        game_dates = h.get("gameDates", []) or []
        n_games = len(game_dates)

        cur = stat_current.get(name_key)
        prev = stat_previous.get(name_key)

        v_cur = per_game_vector(cur, int(cur.get("gamesPlayed", 0))) if cur else None
        v_prev = per_game_vector(prev, int(prev.get("gamesPlayed", 0))) if prev else None

        pa_cur = float((cur or {}).get("plateAppearances", 0) or 0)
        w_cur = pa_blend_weight(pa_cur)

        base_vector = blend_vectors(v_cur, v_prev, w_cur)
        season_base = apply_hitter_formula(base_vector, scoring)

        # Phase 1: no matchup context — every game uses the season-rate vector.
        per_game = season_base
        total = round(per_game * n_games, 1)

        projections[name] = {
            "projFpts":    total,
            "projPerGame": round(per_game, 2),
            "blendWeight": round(w_cur, 2),
            "games":       n_games,
        }
        details[name] = {
            "seasonBase":  round(season_base, 2),
            "blendWeight": round(w_cur, 2),
            "perGame":     round(per_game, 2),
            "games":       n_games,
            "total":       total,
        }

    return projections, details
