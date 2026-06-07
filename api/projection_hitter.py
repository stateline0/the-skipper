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
    "pa", "ab", "h", "1b", "2b", "3b", "hr", "tb",
    "r", "rbi", "bb", "hbp", "sb", "cs", "so",
)


# ── League scoring formula ────────────────────────────────────────────
# Hardcoded to the league's actual hitter scoring, verified from the league
# settings (Total Bases +1, BB +1, R +1, RBI +1, SB +1, K −1, HBP +1; CS not
# scored). This mirrors how api/projection.py hardcodes its pitcher SCORING
# rather than trusting a parsed mSettings stat-ID map. The "tb" (total bases)
# key carries the offensive value, so hit types (1b/2b/3b/hr) are NOT scored
# separately — that would double-count.
DEFAULT_HITTER_SCORING = {
    "tb":  1,
    "bb":  1,
    "r":   1,
    "rbi": 1,
    "sb":  1,
    "hbp": 1,
    "so": -1,
}


# ── ESPN fantasy-baseball hitting stat IDs → our stat keys ─────────────
# CONFIRMED against the live league via /api/hitters?debug=scoring: the seven
# batting scoringItems were statIds {8,10,12,20,21,23,27}, matching the league
# settings screen {TB, BB, R, RBI, SB, HBP, K}. statId 8=TB and 27=K(batter)
# are certain; the remaining five are all weighted +1, so the resulting scoring
# is identical for any bijection onto {bb, r, rbi, sb, hbp} — the within-group
# identities below are the best-fit assignment and only matter if the league
# ever weights those stats unequally (re-confirm via the debug endpoint then).
# Pitching statIds (≥32) are intentionally absent — parse_hitter_scoring only
# builds the hitter dict and skips everything else.
ESPN_HITTING_STAT_IDS = {
    8:  "tb",    # total bases  (certain)
    10: "bb",    # walks
    12: "hbp",   # hit by pitch
    20: "sb",    # stolen bases
    21: "r",     # runs
    23: "rbi",   # runs batted in
    27: "so",    # strikeouts (batter)  (certain)
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

# A league-average everyday-hitter per-game vector, used only to sanity-check
# a parsed scoring dict (does it score a normal regular positively?).
_REFERENCE_VECTOR = {
    "pa": 4.3, "ab": 3.8, "h": 1.00, "1b": 0.62, "2b": 0.20, "3b": 0.02,
    "hr": 0.16, "tb": 1.72, "r": 0.55, "rbi": 0.52, "bb": 0.38, "hbp": 0.04,
    "sb": 0.08, "cs": 0.03, "so": 1.05,
}
# Keys that represent positive offensive production — a sane points-league
# scoring must reward at least one of them.
_POSITIVE_OFFENSE_KEYS = {"tb", "h", "1b", "2b", "3b", "hr", "r", "rbi"}


def scoring_is_sane(scoring: dict) -> bool:
    """True if a parsed scoring dict looks like a real points-league config:
    it rewards at least one positive offensive stat AND scores a league-average
    hitter positively. Guards against a wrong statId map silently producing the
    all-negative projections we hit in the wire-in."""
    if not scoring:
        return False
    if not any(scoring.get(k, 0) > 0 for k in _POSITIVE_OFFENSE_KEYS):
        return False
    return apply_hitter_formula(_REFERENCE_VECTOR, scoring) > 0


def _resolve_points(item: dict):
    """Read a scoringItem's points. ESPN stores the value in `points`, but some
    leagues carry it (or a per-period override) in `pointsOverrides`. Prefer a
    non-zero override when `points` is missing or zero."""
    pts = item.get("points")
    overrides = item.get("pointsOverrides") or {}
    if overrides:
        ov_val = next((v for v in overrides.values() if v is not None), None)
        if ov_val is not None and (pts in (None, 0)):
            pts = ov_val
    return pts


def parse_hitter_scoring(msettings: dict) -> dict:
    """Build a hitter SCORING dict from an ESPN league's mSettings payload.

    Maps each hitting statId in scoringSettings.scoringItems[] via
    ESPN_HITTING_STAT_IDS and reads its points value. Falls back to the verified
    DEFAULT_HITTER_SCORING when the parse yields nothing OR fails scoring_is_sane
    (a wrong statId map / unexpected config) — so the caller always gets a dict
    that projects hitters positively, never the all-negative regression.
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
            # Only flag IDs in the hitting range so pitching items (≥32) don't spam.
            if isinstance(stat_id, int) and 0 <= stat_id <= 31:
                unmapped.append(stat_id)
            continue
        pts = _resolve_points(item)
        if pts is None or pts == 0:
            continue
        scoring[key] = pts

    if unmapped:
        print(f"[projection_hitter.py] Unmapped hitting statIds in mSettings: "
              f"{sorted(set(unmapped))} — verify ESPN_HITTING_STAT_IDS")

    if not scoring_is_sane(scoring):
        print(f"[projection_hitter.py] Parsed scoring failed sanity check "
              f"(parsed={scoring}); falling back to DEFAULT_HITTER_SCORING")
        return dict(DEFAULT_HITTER_SCORING)

    print(f"[projection_hitter.py] Using mSettings-derived hitter scoring: {scoring}")
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
    # Total bases = 1B + 2·2B + 3·3B + 4·HR (the league's primary offensive stat).
    tb = singles + 2 * dbl + 3 * tpl + 4 * hr

    raw = {
        "pa":  g("plateAppearances"),
        "ab":  g("atBats"),
        "h":   h,
        "1b":  singles,
        "2b":  dbl,
        "3b":  tpl,
        "hr":  hr,
        "tb":  tb,
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


# ── Phase 6: platoon (L/R) multiplier ──────────────────────────────────
PLATOON_REGRESSION_PA = 100.0   # split is half-trusted at this many PA vs a hand
PLATOON_CLAMP = (0.85, 1.15)    # cap the single-factor swing


def platoon_multiplier(ops_vs_hand: float, pa_vs_hand: float, ops_overall: float) -> float:
    """Per-game platoon factor: how a batter fares vs the day's starter hand,
    relative to their overall line, regressed toward 1.0 by sample size.

    factor_raw = OPS_vs_hand / OPS_overall, then blended toward neutral with
    weight pa/(pa+K) so a 30-PA split barely moves and a full-season split
    counts. Returns 1.0 (no-op) when any input is missing — so the layer
    degrades gracefully when splits or the opposing hand are unknown.
    """
    if not ops_vs_hand or not ops_overall or ops_overall <= 0:
        return 1.0
    raw = ops_vs_hand / ops_overall
    w = pa_vs_hand / (pa_vs_hand + PLATOON_REGRESSION_PA) if pa_vs_hand else 0.0
    factor = 1.0 + (raw - 1.0) * w
    lo, hi = PLATOON_CLAMP
    return round(max(lo, min(hi, factor)), 3)


# ── Phase 7: opposing-pitcher quality multiplier ───────────────────────
OPP_PITCHER_DAMPEN = 0.7        # the base already carries the hitter's own talent
OPP_PITCHER_CLAMP = (0.88, 1.12)


def opp_pitcher_multiplier(opp_xwoba: float, league_xwoba: float) -> float:
    """Per-game factor for the opposing starter's quality, from their expected
    wOBA-against relative to league average. xwOBA-against > league = the pitcher
    allows more than average = good for the hitter (factor > 1); an ace (low
    xwOBA-against) suppresses (factor < 1). Dampened (the base already reflects
    the hitter's talent) and clamped. Returns 1.0 when data is missing."""
    if not opp_xwoba or not league_xwoba or league_xwoba <= 0:
        return 1.0
    raw = opp_xwoba / league_xwoba
    factor = 1.0 + (raw - 1.0) * OPP_PITCHER_DAMPEN
    lo, hi = OPP_PITCHER_CLAMP
    return round(max(lo, min(hi, factor)), 3)


def apply_factors(vector: dict, per_stat: dict = None, scalar: float = 1.0) -> dict:
    """Apply per-stat multipliers and a scalar to a stat vector.

    Phase 1 calls this with identity (no factors). Later phases pass:
      * per_stat — e.g. {"hr": 1.12, "h": 0.97} for park/wind/platoon-by-stat
      * scalar   — e.g. opposing-pitcher-quality or regressed-BvP multiplier
    so the per-game composition pipeline doesn't change as layers are added.
    """
    per_stat = per_stat or {}
    return {k: vector.get(k, 0.0) * per_stat.get(k, 1.0) * scalar for k in vector}


def apply_savant_hitter(vector: dict, savant_row: dict) -> dict:
    """Phase 2: replace luck-influenced offense with Savant expected values.

    - Expected hits  = xBA  × AB  (strips BABIP variance)
    - Expected bases = xSLG × AB  (the league's primary stat → expected TB)
    Hit-type cells (1b/2b/3b/hr) are scaled by the TB ratio so the mix stays
    internally consistent. Skill stats (BB/SB/HBP/SO) and context stats (R/RBI)
    are unchanged — they aren't quality-of-contact luck. Returns the vector
    unchanged when there's no usable Savant row or no at-bats.
    """
    if not vector or not savant_row:
        return vector
    ab = vector.get("ab", 0.0)
    xba = savant_row.get("xba", 0) or 0
    xslg = savant_row.get("xslg", 0) or 0
    if ab <= 0 or xba <= 0 or xslg <= 0:
        return vector
    adjusted = dict(vector)
    adjusted["h"] = xba * ab
    new_tb = xslg * ab
    old_tb = vector.get("tb", 0.0)
    adjusted["tb"] = new_tb
    if old_tb > 0:
        ratio = new_tb / old_tb
        for k in ("1b", "2b", "3b", "hr"):
            adjusted[k] = vector.get(k, 0.0) * ratio
    return adjusted


def compute_recent_form_hitter(games: list, scoring: dict,
                               n_games: int = 15, min_games: int = 5) -> float:
    """Recency-weighted FPTS/game from a hitter's last ~N games (Phase 3).

    Each game's counting line is scored with the league scoring dict (same TB
    logic as the season vector), then averaged with linear recency weights
    (newest heaviest). Returns None when there aren't at least `min_games` —
    the caller then falls back to the pure season rate.
    """
    if not games:
        return None
    recent = games[-n_games:]
    if len(recent) < min_games:
        return None
    n = len(recent)
    weights = [i + 1 for i in range(n)]          # oldest→newest, linear ramp
    wsum = sum(weights)
    total = 0.0
    for i, g in enumerate(recent):
        h   = g.get("h", 0)
        dbl = g.get("2b", 0)
        tpl = g.get("3b", 0)
        hr  = g.get("hr", 0)
        singles = max(0, h - dbl - tpl - hr)
        vec = {
            "h": h, "1b": singles, "2b": dbl, "3b": tpl, "hr": hr,
            "tb": singles + 2 * dbl + 3 * tpl + 4 * hr,
            "r": g.get("r", 0), "rbi": g.get("rbi", 0), "bb": g.get("bb", 0),
            "hbp": g.get("hbp", 0), "sb": g.get("sb", 0), "cs": g.get("cs", 0),
            "so": g.get("so", 0), "ab": g.get("ab", 0), "pa": g.get("pa", 0),
        }
        total += apply_hitter_formula(vec, scoring) * weights[i]
    return round(total / wsum, 2)


# Blend weight: season rate vs. recent form (mirrors the pitcher model's 60/40).
RECENT_FORM_WEIGHT = 0.4


def get_projected_hitter_fpts(
    hitters: list,
    scoring: dict = None,
    stat_current: dict = None,
    stat_previous: dict = None,
    savant_current: dict = None,
    savant_previous: dict = None,
    game_logs: dict = None,
    season: int = 2026,
    period: int = 1,
) -> tuple:
    """Hitter projections (Phase 1 baseline + Phase 2 Savant de-luck).

    Args:
        hitters: list of {"name", "team", "gameDates": [...]} dicts. gameDates
                 is the list of dates this hitter is rostered to play in the
                 matchup period (analogue of pitcher startDates).
        scoring: league hitter scoring dict (from parse_hitter_scoring). Falls
                 back to DEFAULT_HITTER_SCORING.
        stat_current / stat_previous: {name_lower: mlb_hitting_stat_obj} for the
                 current and previous seasons.
        savant_current / savant_previous: {name_lower: batter expected-stats}
                 from Baseball Savant; when present, H/TB are de-lucked (Phase 2).

    Returns (projections, details):
        projections — {name: {"projFpts", "projPerGame", "blendWeight",
                              "games", "modelType"}}
        details     — {name: {"seasonBase", "modelType", "blendWeight",
                              "perGame", "games", "total"}} for the tooltip.

    Phases 3–10 (recent form, park, weather, platoon, opposing-pitcher, BvP,
    volume) layer on top via apply_factors() per game.
    """
    scoring = scoring or dict(DEFAULT_HITTER_SCORING)
    stat_current = stat_current or {}
    stat_previous = stat_previous or {}
    savant_current = savant_current or {}
    savant_previous = savant_previous or {}
    game_logs = game_logs or {}

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

        # Phase 2: Savant de-luck, applied to each season before blending.
        model_type = "stats"
        if v_cur is not None and name_key in savant_current:
            v_cur = apply_savant_hitter(v_cur, savant_current[name_key])
            model_type = "savant"
        if v_prev is not None and name_key in savant_previous:
            v_prev = apply_savant_hitter(v_prev, savant_previous[name_key])

        pa_cur = float((cur or {}).get("plateAppearances", 0) or 0)
        w_cur = pa_blend_weight(pa_cur)

        base_vector = blend_vectors(v_cur, v_prev, w_cur)
        season_base = apply_hitter_formula(base_vector, scoring)

        # Phase 3: blend the season rate with recency-weighted recent form.
        recent_form = compute_recent_form_hitter(game_logs.get(name_key), scoring)
        if recent_form is not None:
            per_game = season_base * (1 - RECENT_FORM_WEIGHT) + recent_form * RECENT_FORM_WEIGHT
        else:
            per_game = season_base
        total = round(per_game * n_games, 1)

        projections[name] = {
            "projFpts":    total,
            "projPerGame": round(per_game, 2),
            "blendWeight": round(w_cur, 2),
            "games":       n_games,
            "modelType":   model_type,
            "recentForm":  recent_form,
        }
        details[name] = {
            "seasonBase":  round(season_base, 2),
            "modelType":   model_type,
            "blendWeight": round(w_cur, 2),
            "recentForm":  recent_form,
            "perGame":     round(per_game, 2),
            "games":       n_games,
            "total":       total,
        }

    return projections, details
