"""
api/projection.py — Projection model for pitcher fantasy points.

Hybrid model combining:
  - Savant expected stats (luck-adjusted H, ER)
  - MLB Stats API counting stats (skill-based IP, K, BB, HBP, W, L, SV)
  - Year-over-year blending (2025 ↔ 2026) by innings pitched
  - Recent form weighting: 60% season / 40% last-4-starts (Layer 2)
  - Opponent quality adjustment via team wOBA factors (Layer 1)
  - Park factor adjustment per start (Layer 3)
  - Vegas/Pythagorean win probability for W/L per start (Layer 4)

Extracted from espn.py during session 18 refactor.
Vegas W/L and Pythagorean model added session 18.
"""

import unicodedata

from mlb import compute_recent_form_fpts, get_park_factor, compute_matchup_win_prob
from kv import get_locked_projection, set_locked_projection, set_locked_projection_v2


# ── League scoring formula ────────────────────────────────────────────
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

IP_THRESHOLD_SP = 50.0
IP_THRESHOLD_RP = 20.0
MIN_STARTS_SP = 3
MIN_APPEARANCES_RP = 5

# Starter win share: probability that the starting pitcher gets the W
# given the team wins. Historically ~55-60%, trending down as starters
# pitch fewer innings. 0.57 is a league-wide average.
STARTER_WIN_SHARE = 0.57

# Default team win probability when neither Vegas odds nor Pythagorean
# model data is available. 0.5 = coin flip.
DEFAULT_WIN_PROB = 0.5


def strip_accents(s: str) -> str:
    """Normalize accented characters for name matching across data sources."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).lower()


def parse_ip(ip_str) -> float:
    """Parse MLB's innings pitched string format."""
    try:
        parts = str(ip_str).split(".")
        full  = int(parts[0])
        outs  = int(parts[1]) if len(parts) > 1 else 0
        return full + outs / 3
    except Exception:
        return 0.0


def per_game_avgs(stat: dict, games: int, is_rp: bool = False) -> dict:
    """Compute per-game averages from MLB Stats API season totals."""
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
        "batters_faced": ip * 3 + h + bb + hb,
    }


def apply_savant_adjustments(avgs: dict, savant_data: dict) -> dict:
    """
    Replace luck-influenced stats with Savant expected values.
    - H per start → xBA × batters_faced (removes BABIP luck)
    - ER per start → xERA × (IP / 9) (removes sequencing luck)
    W/L are NOT adjusted here — they are scaled per-start using Vegas
    or Pythagorean win probabilities in the matchup adjustment loop.
    """
    adjusted = dict(avgs)
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
                      game_logs: dict = None,
                      team_win_data: dict = None,
                      schedule: dict = None) -> tuple:
    """
    Project fantasy points per pitcher using the hybrid model.

    Returns tuple:
      proj_fpts, proj_blend, fpts_per_start, proj_details
    """
    team_woba_factors = team_woba_factors or {}
    savant_current    = savant_current or {}
    savant_previous   = savant_previous or {}
    game_logs         = game_logs or {}
    team_win_data     = team_win_data or {}
    schedule          = schedule or {}
    if not player_starts:
        return {}, {}, {}, {}

    starts_by_name = {strip_accents(p["name"]): p for p in player_starts}

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

        # ── Apply Savant adjustments ──────────────────────────────────
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

        # ── Layers 1, 3, 4: wOBA + Park + Vegas/Pythagorean W/L ──────
        # Each start gets:
        #   1. wOBA factor (opponent lineup quality)
        #   2. Park factor (hitter/pitcher park)
        #   3. Win probability for W/L scaling:
        #      - Vegas moneyline (if available, ~1-2 days out)
        #      - Pythagorean + Log5 + pitcher adjustment (fallback)
        #      - 0.5 default (if neither available)
        #
        # W/L per start:
        #   base_no_wl = all stats except W/L
        #   w_contrib  = raw_w_rate × win_prob × STARTER_WIN_SHARE × 5
        #   l_contrib  = raw_l_rate × (1 - win_prob) × STARTER_WIN_SHARE × (-5)
        #   start_proj = (base_no_wl + w_contrib + l_contrib) × woba × park
        start_dates = player_info.get("startDates", [])
        per_start_details = []
        if not is_rp and start_dates:
            # Base FPTS excluding W/L (those are applied per-start)
            base_no_wl = (
                blended["ip"] *  3 +
                blended["so"] *  1 +
                blended["h"]  * -1 +
                blended["bb"] * -1 +
                blended["er"] * -2 +
                blended["hb"] * -1 +
                blended["sv"] *  5
            )
            raw_w = blended["w"]
            raw_l = blended["l"]

            # Our pitcher's xERA for Pythagorean adjustment
            our_xera = (savant_current.get(name_lower, {}).get("xera")
                        or savant_previous.get(name_lower, {}).get("xera"))

            adjusted_total = 0.0
            for sd in start_dates:
                opp       = sd.get("opponent", "")
                is_home   = sd.get("is_home", True)
                vegas_wp  = sd.get("win_prob")  # from ESPN scoreboard moneyline
                woba_factor = team_woba_factors.get(opp, 1.0) if team_woba_factors else 1.0
                park_team   = opp if not is_home else player_info.get("team", "")
                park_factor = get_park_factor(park_team) if park_team else 1.0

                # Win probability: Vegas → Pythagorean → default
                if vegas_wp:
                    win_prob = vegas_wp
                    wp_source = "vegas"
                elif team_win_data and player_info.get("team") and opp:
                    win_prob = compute_matchup_win_prob(
                        team_abbrev=player_info.get("team", ""),
                        opp_abbrev=opp,
                        team_win_data=team_win_data,
                        pitcher_xera=our_xera,
                        opp_pitcher_xera=None,  # TODO: thread opponent starter xERA
                    ) or DEFAULT_WIN_PROB
                    wp_source = "pyth"
                else:
                    win_prob = DEFAULT_WIN_PROB
                    wp_source = "default"

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
                    "wpSource": wp_source,
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
                        set_locked_projection(season, period, full_name, date,
                                              round(fpts_per_game, 1))
                        opp       = sd.get("opponent", "")
                        is_home   = sd.get("is_home", True)
                        vegas_wp  = sd.get("win_prob")
                        woba_f    = team_woba_factors.get(opp, 1.0) if team_woba_factors else 1.0
                        park_tm   = opp if not is_home else player_info.get("team", "")
                        park_f    = get_park_factor(park_tm) if park_tm else 1.0
                        # Use same win_prob logic as projection
                        if vegas_wp:
                            lock_wp = vegas_wp
                        elif team_win_data and player_info.get("team") and opp:
                            lock_wp = compute_matchup_win_prob(
                                player_info.get("team", ""), opp,
                                team_win_data, pitcher_xera=our_xera if 'our_xera' in dir() else None,
                            ) or DEFAULT_WIN_PROB
                        else:
                            lock_wp = DEFAULT_WIN_PROB
                        w_adj = blended["w"] * lock_wp * STARTER_WIN_SHARE
                        l_adj = blended["l"] * (1 - lock_wp) * STARTER_WIN_SHARE
                        lock_base = (
                            blended["ip"] * 3 + blended["so"] * 1 +
                            blended["h"] * -1 + blended["bb"] * -1 +
                            blended["er"] * -2 + blended["hb"] * -1 +
                            blended["sv"] * 5
                        )
                        start_proj = (lock_base + w_adj * 5 + l_adj * (-5)) * woba_f * park_f
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
                                "winProb":  round(lock_wp, 3),
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
