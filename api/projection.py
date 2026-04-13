"""
api/projection.py — Projection model for pitcher fantasy points.

Hybrid model combining:
  - Savant expected stats (luck-adjusted H, ER)
  - MLB Stats API counting stats (skill-based IP, K, BB, HBP, W, L, SV)
  - Year-over-year blending (2025 ↔ 2026) by innings pitched
  - Recent form weighting: 60% season / 40% last-4-starts (Layer 2)
  - Opponent quality adjustment via team wOBA factors (Layer 1)
  - Park factor adjustment per start (Layer 3)

Extracted from espn.py during session 18 refactor.
"""

import unicodedata

from mlb import compute_recent_form_fpts, get_park_factor
from kv import get_locked_projection, set_locked_projection, set_locked_projection_v2


# ── League scoring formula ────────────────────────────────────────────
# Points per stat, matching ESPN league settings for "Good Season Imanagas"
SCORING = {
    "ip":  3,
    "so":  1,
    "h":  -1,
    "bb": -1,
    "er": -2,
    "hb": -1,
    "w":   5,
    "l":  -5,
    "sv":  5,
}

# Year-over-year blend thresholds: how many IP before we fully trust
# this year's data over last year's.
IP_THRESHOLD_SP = 50.0   # ~9 starts, ~6 weeks
IP_THRESHOLD_RP = 20.0   # ~20 appearances, ~6 weeks

# Minimum games before trusting per-game averages
MIN_STARTS_SP = 3
MIN_APPEARANCES_RP = 5

# Starter win share: probability that the starting pitcher gets the W
# given the team wins. Historically ~55-60% of team wins go to starters.
# The rest go to relievers (starter leaves tied/trailing, bullpen takes over).
# Using 0.57 as a league-wide average.
STARTER_WIN_SHARE = 0.57

# Default team win probability when Vegas odds are unavailable.
# 0.5 = coin flip, same as the old flat discount behavior.
DEFAULT_WIN_PROB = 0.5


def strip_accents(s: str) -> str:
    """Normalize accented characters for name matching across data sources.
    e.g. 'Edwin Díaz' -> 'edwin diaz' to match ESPN's 'Edwin Diaz'."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).lower()


def parse_ip(ip_str) -> float:
    """Parse MLB's innings pitched string format.
    '6.2' means 6 innings + 2 outs = 6.667 actual innings."""
    try:
        parts = str(ip_str).split(".")
        full  = int(parts[0])
        outs  = int(parts[1]) if len(parts) > 1 else 0
        return full + outs / 3
    except Exception:
        return 0.0


def per_game_avgs(stat: dict, games: int, is_rp: bool = False) -> dict:
    """Compute per-game averages from MLB Stats API season totals.
    Returns None if below minimum sample threshold."""
    min_games = MIN_APPEARANCES_RP if is_rp else MIN_STARTS_SP
    if games < min_games:
        return None
    ip = parse_ip(stat.get("inningsPitched", "0.0")) / games
    h  = int(stat.get("hits",         0)) / games
    bb = int(stat.get("baseOnBalls",   0)) / games
    hb = int(stat.get("hitBatsmen",    0)) / games
    return {
        "ip": ip,
        "so": int(stat.get("strikeOuts", 0)) / games,
        "h":  h,
        "bb": bb,
        "er": int(stat.get("earnedRuns", 0)) / games,
        "hb": hb,
        "w":  int(stat.get("wins",       0)) / games,
        "l":  int(stat.get("losses",     0)) / games,
        "sv": int(stat.get("saves",      0)) / games,
        # Extra field needed for Savant hybrid: approximate TBF per game
        "batters_faced": ip * 3 + h + bb + hb,
    }


def apply_savant_adjustments(avgs: dict, savant_data: dict) -> dict:
    """
    Replace luck-influenced stats with Savant expected values.
    - H per start → xBA × batters_faced (removes BABIP luck)
    - ER per start → xERA × (IP / 9) (removes sequencing luck)
    W/L are NOT adjusted here — they are scaled per-start using Vegas
    implied win probabilities in the matchup adjustment loop.
    Returns a new dict with adjusted values.
    """
    adjusted = dict(avgs)  # copy
    xba  = savant_data.get("xba", 0)
    xera = savant_data.get("xera", 0)

    if xba > 0 and adjusted["batters_faced"] > 0:
        adjusted["h"] = xba * adjusted["batters_faced"]

    if xera > 0 and adjusted["ip"] > 0:
        adjusted["er"] = xera * (adjusted["ip"] / 9)

    return adjusted


def apply_formula(avgs: dict) -> float:
    """Apply league scoring formula to per-game averages."""
    return sum(avgs[stat] * pts for stat, pts in SCORING.items())


def get_projected_fpts(player_starts: list, team_woba_factors: dict = None,
                      season: int = 2026, period: int = 1,
                      today_str: str = "",
                      savant_current: dict = None,
                      savant_previous: dict = None,
                      mlb_stats_current: dict = None,
                      mlb_stats_previous: dict = None,
                      game_logs: dict = None) -> tuple:
    """
    Project fantasy points per pitcher using the hybrid model.

    player_starts: [{"name": "...", "starts": 2, "is_rp": False,
                     "startDates": [{"date": "...", "opponent": "COL", "is_home": True}]}, ...]
    team_woba_factors: { "LAD": 1.08, "CWS": 0.91, ... }
    savant_current:  { "sandy alcantara": {"xwoba": .186, "xera": 1.36, ...} }
    savant_previous: { "sandy alcantara": {"xwoba": .300, "xera": 3.80, ...} }
    game_logs:       { "sandy alcantara": [{"date": "...", "ip": 6.0, ...}, ...] }

    Returns tuple:
      proj_fpts:      { "Garrett Crochet": 34.2, ... }
      proj_blend:     { "Garrett Crochet": 0.3, ... }  ← this-year weight
      fpts_per_start: { "Garrett Crochet": 17.1, ... }  ← baseline, pre-matchup
      proj_details:   { "Garrett Crochet": { breakdown for tooltip } }
    """
    team_woba_factors = team_woba_factors or {}
    savant_current    = savant_current or {}
    savant_previous   = savant_previous or {}
    game_logs         = game_logs or {}
    if not player_starts:
        return {}, {}, {}, {}

    starts_by_name = {strip_accents(p["name"]): p for p in player_starts}

    # Use pre-fetched (and potentially cached) MLB stats
    stats_2026 = mlb_stats_current or {}
    stats_2025 = mlb_stats_previous or {}

    proj_fpts      = {}
    proj_blend     = {}
    fpts_per_start = {}
    proj_details   = {}

    for name_lower, player_info in starts_by_name.items():
        full_name        = player_info["name"]
        projected_starts = player_info["starts"]
        is_rp            = player_info.get("is_rp", False)

        stat_26 = stats_2026.get(name_lower, {})
        stat_25 = stats_2025.get(name_lower, {})

        if is_rp:
            gs_26 = int(stat_26.get("gamesPlayed", 0))
            gs_25 = int(stat_25.get("gamesPlayed", 0))
        else:
            gs_26 = int(stat_26.get("gamesStarted", 0))
            gs_25 = int(stat_25.get("gamesStarted", 0))

        ip_26 = parse_ip(stat_26.get("inningsPitched", "0.0"))

        # Blend weight: ramp from 0% to 100% this year as IP crosses threshold
        ip_threshold     = IP_THRESHOLD_RP if is_rp else IP_THRESHOLD_SP
        this_year_weight = min(1.0, ip_26 / ip_threshold)
        last_year_weight = 1.0 - this_year_weight

        avgs_26 = per_game_avgs(stat_26, gs_26, is_rp)
        avgs_25 = per_game_avgs(stat_25, gs_25, is_rp)

        if avgs_26 is None and avgs_25 is None:
            proj_fpts[full_name]  = 0.0
            proj_blend[full_name] = 0.0
            continue
        elif avgs_26 is None:
            this_year_weight = 0.0
            last_year_weight = 1.0
        elif avgs_25 is None:
            this_year_weight = 1.0
            last_year_weight = 0.0

        # ── Apply Savant adjustments to each year's averages ──────────
        savant_26 = savant_current.get(name_lower, {})
        savant_25 = savant_previous.get(name_lower, {})
        used_savant = False

        if avgs_26 is not None:
            if savant_26 and savant_26.get("xera", 0) > 0 and not is_rp:
                avgs_26 = apply_savant_adjustments(avgs_26, savant_26)
                used_savant = True
        if avgs_25 is not None:
            if savant_25 and savant_25.get("xera", 0) > 0 and not is_rp:
                avgs_25 = apply_savant_adjustments(avgs_25, savant_25)
                used_savant = True

        # ── Blend years ───────────────────────────────────────────────
        if avgs_26 is not None and avgs_25 is not None:
            blended = {
                s: avgs_26[s] * this_year_weight + avgs_25[s] * last_year_weight
                for s in avgs_26
            }
        elif avgs_26 is not None:
            blended = avgs_26
        else:
            blended = avgs_25

        fpts_per_game = apply_formula(blended)
        model_label = "savant" if used_savant else "stats"
        season_base = round(fpts_per_game, 1)

        # ── Layer 2: Recent form weighting ─────────────────────────────
        recent_form_fpts = None
        if not is_rp and game_logs:
            pitcher_games = game_logs.get(name_lower, [])
            if pitcher_games:
                recent_form_fpts = compute_recent_form_fpts(pitcher_games, n_starts=4)

        if recent_form_fpts is not None:
            season_fpts = fpts_per_game
            fpts_per_game = season_fpts * 0.6 + recent_form_fpts * 0.4
            print(f"[projection.py]   ↳ {full_name} recent form: {recent_form_fpts:.1f} | "
                  f"season: {season_fpts:.1f} → blended: {fpts_per_game:.1f}")

        adjusted_base = round(fpts_per_game, 1)

        # ── Opponent quality + Park factor + Vegas W/L (Layers 1, 3, 4) ──
        # Each start gets three adjustments:
        #   1. wOBA factor — how good is the opposing lineup?
        #   2. Park factor — is this a hitter or pitcher park?
        #   3. Vegas W/L — replace flat W/L with game-specific win probability
        #
        # W/L handling: instead of a flat 50% discount on season W/L rates,
        # we use Vegas moneyline odds to get game-specific team win probability,
        # then multiply by STARTER_WIN_SHARE (0.57) to estimate the pitcher's
        # chance of getting the W or L in that specific start.
        #
        # Formula per start:
        #   base_no_wl = IP×3 + K×1 + H×(-1) + BB×(-1) + ER×(-2) + HBP×(-1) + SV×5
        #   w_contrib  = raw_w_rate × win_prob × STARTER_WIN_SHARE × 5
        #   l_contrib  = raw_l_rate × (1 - win_prob) × STARTER_WIN_SHARE × (-5)
        #   start_proj = (base_no_wl + w_contrib + l_contrib) × woba × park
        start_dates = player_info.get("startDates", [])
        per_start_details = []
        if not is_rp and start_dates:
            # Compute base FPTS excluding W/L (those are applied per-start)
            base_no_wl = (
                blended["ip"] *  3 +
                blended["so"] *  1 +
                blended["h"]  * -1 +
                blended["bb"] * -1 +
                blended["er"] * -2 +
                blended["hb"] * -1 +
                blended["sv"] *  5
            )
            raw_w = blended["w"]  # raw per-game win rate (not discounted)
            raw_l = blended["l"]  # raw per-game loss rate

            adjusted_total = 0.0
            for sd in start_dates:
                opp       = sd.get("opponent", "")
                is_home   = sd.get("is_home", True)
                win_prob  = sd.get("win_prob") or DEFAULT_WIN_PROB
                woba_factor = team_woba_factors.get(opp, 1.0) if team_woba_factors else 1.0
                park_team   = opp if not is_home else player_info.get("team", "")
                if not park_team:
                    park_factor = 1.0
                else:
                    park_factor = get_park_factor(park_team)
                # W/L contribution for this specific start
                w_contrib = raw_w * win_prob * STARTER_WIN_SHARE * 5
                l_contrib = raw_l * (1 - win_prob) * STARTER_WIN_SHARE * (-5)
                start_base = base_no_wl + w_contrib + l_contrib
                start_proj = start_base * woba_factor * park_factor
                adjusted_total += start_proj
                location = "vs" if is_home else "@"
                per_start_details.append({
                    "label":    f"{location} {opp}",
                    "date":     sd.get("date", ""),
                    "woba":     round(woba_factor, 3),
                    "park":     round(park_factor, 3),
                    "parkTeam": park_team,
                    "winProb":  round(win_prob, 3),
                    "proj":     round(start_proj, 1),
                })
            projected = round(adjusted_total, 1)
            avg_factor = round(adjusted_total / (fpts_per_game * len(start_dates)), 3) if start_dates and fpts_per_game else 1.0
        elif is_rp:
            days_in_period = player_info.get("days_in_period", 7)
            projected_appearances = round(days_in_period / 7 * 4)
            projected = round(fpts_per_game * projected_appearances, 1)
            avg_factor = 1.0
        else:
            projected = round(fpts_per_game * projected_starts, 1)
            avg_factor = 1.0

        proj_fpts[full_name]      = projected
        proj_blend[full_name]     = round(this_year_weight, 2)
        fpts_per_start[full_name] = round(fpts_per_game, 1)

        # ── Projection breakdown for tooltip ──────────────────────────
        proj_details[full_name] = {
            "seasonBase":   season_base,
            "modelType":    model_label,
            "blendWeight":  round(this_year_weight, 2),
            "recentForm":   round(recent_form_fpts, 1) if recent_form_fpts is not None else None,
            "adjustedBase": adjusted_base,
            "starts":       per_start_details,
            "total":        projected,
        }

        # ── Per-start locking ─────────────────────────────────────────
        if today_str and start_dates and not is_rp:
            for sd in start_dates:
                date = sd.get("date", "")
                if date and date <= today_str:
                    existing = get_locked_projection(season, period, full_name, date)
                    if existing is None:
                        # V1: float for frontend compatibility
                        set_locked_projection(season, period, full_name, date,
                                              round(fpts_per_game, 1))
                        # V2: full breakdown for accuracy tracking
                        opp       = sd.get("opponent", "")
                        is_home   = sd.get("is_home", True)
                        win_prob  = sd.get("win_prob") or DEFAULT_WIN_PROB
                        woba_f    = team_woba_factors.get(opp, 1.0) if team_woba_factors else 1.0
                        park_tm   = opp if not is_home else player_info.get("team", "")
                        park_f    = get_park_factor(park_tm) if park_tm else 1.0
                        # Compute per-start W/L using Vegas odds
                        w_adj = blended["w"] * win_prob * STARTER_WIN_SHARE
                        l_adj = blended["l"] * (1 - win_prob) * STARTER_WIN_SHARE
                        base_no_wl_lock = (
                            blended["ip"] *  3 + blended["so"] *  1 +
                            blended["h"]  * -1 + blended["bb"] * -1 +
                            blended["er"] * -2 + blended["hb"] * -1 +
                            blended["sv"] *  5
                        )
                        start_proj = (base_no_wl_lock + w_adj * 5 + l_adj * (-5)) * woba_f * park_f
                        breakdown = {
                            "fpts": round(start_proj, 1),
                            "stats": {
                                "ip": round(blended["ip"], 2),
                                "so": round(blended["so"], 2),
                                "h":  round(blended["h"], 2),
                                "bb": round(blended["bb"], 2),
                                "er": round(blended["er"], 2),
                                "hb": round(blended["hb"], 2),
                                "w":  round(w_adj, 3),
                                "l":  round(l_adj, 3),
                                "sv": round(blended["sv"], 3),
                            },
                            "matchup": {
                                "opponent": opp,
                                "woba":     round(woba_f, 3),
                                "park":     round(park_f, 3),
                                "parkTeam": park_tm,
                                "isHome":   is_home,
                                "winProb":  round(win_prob, 3),
                            },
                            "model": {
                                "type":         model_label,
                                "blendWeight":  round(this_year_weight, 2),
                                "recentForm":   round(recent_form_fpts, 1) if recent_form_fpts is not None else None,
                                "seasonBase":   season_base,
                                "adjustedBase": adjusted_base,
                            },
                        }
                        set_locked_projection_v2(season, period, full_name, date, breakdown)

        print(f"[projection.py] {full_name} [{model_label}]: "
              f"{round(this_year_weight*100)}% '26 / {round(last_year_weight*100)}% '25 | "
              f"{fpts_per_game:.1f} pts/game × {avg_factor:.3f} = {projected}"
              f"{' [recent form applied]' if recent_form_fpts is not None else ''}")

    return proj_fpts, proj_blend, fpts_per_start, proj_details
