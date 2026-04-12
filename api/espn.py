"""
/api/espn.py  — Vercel Python serverless function
Fetches roster + free agents from ESPN Fantasy Baseball API.
Probable pitcher data and game schedule come from mlb.py.
"""
import json
import os
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mlb import get_starts_for_players, get_team_woba, MATCHUP_PERIODS, fetch_game_logs, compute_recent_form_fpts, get_park_factor
from kv import (get_locked_projection, set_locked_projection, get_all_locked_projections,
                set_locked_projection_v2, cache_get, cache_set)
from savant import fetch_expected_stats


SEASON_START = datetime(2026, 3, 25)

import unicodedata

def strip_accents(s: str) -> str:
    """Normalize accented characters for name matching across data sources.
    e.g. 'Edwin Díaz' -> 'edwin diaz' to match ESPN's 'Edwin Diaz'."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).lower()


def get_headers_and_cookies():
    espn_s2 = os.environ.get("ESPN_S2", "").strip()
    swid    = os.environ.get("ESPN_SWID", "").strip()
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    return headers, cookies


def get_slot_label(eligible_slots: set, injured: bool) -> str:
    """Determine position label from eligibility and injury status.
    Uses eligibleSlots for SP/RP (stable player attribute) and
    player.injured for IL detection (not lineupSlotId, which is daily)."""
    if injured:
        return "IL"
    if 14 in eligible_slots:
        return "SP"
    if 13 in eligible_slots and 14 not in eligible_slots:
        return "RP"
    return "P"


def get_status(injured: bool) -> str:
    """Simple status label. Bench is not tracked — it's a daily lineup decision."""
    if injured:
        return "IL"
    return "Active"


def get_pro_team_map(headers, cookies):
    """
    Fetch current MLB team ID -> abbreviation mapping from ESPN.
    Falls back to hardcoded 2026 map if the API call fails.
    """
    try:
        year = os.environ.get("ESPN_SEASON", "2026")
        r = requests.get(
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}",
            params={"view": "proTeamSchedules_wl"},
            cookies=cookies,
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            team_map = {}
            for team in data.get("proTeams", []):
                team_id = team.get("id")
                abbrev  = team.get("abbrev", "")
                if team_id and abbrev:
                    team_map[team_id] = abbrev
            if team_map:
                return team_map
    except Exception as e:
        print(f"[espn.py] Failed to fetch pro team map: {e}")

    return {
        1:  "BAL", 2:  "BOS", 3:  "LAA", 4:  "CWS", 5:  "CLE",
        6:  "DET", 7:  "KC",  8:  "MIL", 9:  "MIN", 10: "NYY",
        11: "ATH", 12: "SEA", 13: "TEX", 14: "TOR", 15: "ATL",
        16: "CHC", 17: "CIN", 18: "HOU", 19: "LAD", 20: "WSH",
        21: "NYM", 22: "PHI", 23: "PIT", 24: "STL", 25: "SD",
        26: "SF",  27: "COL", 28: "MIA", 29: "ARI", 30: "TB",
        31: "FA",  32: "FA",
    }


def date_to_scoring_period(date_str: str) -> int:
    """Convert a YYYY-MM-DD date string to ESPN's daily scoring period ID."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - SEASON_START).days + 1


def today_has_started(schedule: dict) -> bool:
    """
    Returns True if any MLB game today is in_progress or final.
    Used to detect whether ESPN has locked today's roster scoring period.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_games = schedule.get(today_str, {})
    return any(
        g.get("status") in ("in_progress", "final")
        for g in today_games.values()
    )


# ── Fetch MLB Stats API season data (both years, parallel) ────────────
def fetch_season_stats(yr: int) -> dict:
    """Fetch season pitching stats from MLB Stats API.
    Returns { fullname_lower: stat_dict }"""
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/stats",
            params={
                "stats": "season", "playerPool": "all",
                "group": "pitching", "season": str(yr),
                "gameType": "R", "limit": 1000,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if r.status_code != 200:
            return {}
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        return {
            strip_accents(s.get("player", {}).get("fullName", "")):
                s.get("stat", {})
            for s in splits if s.get("player", {}).get("fullName")
        }
    except Exception as e:
        print(f"[espn.py] Failed to fetch {yr} MLB stats: {e}")
        return {}

def get_projected_fpts(player_starts: list, team_woba_factors: dict = None,
                      season: int = 2026, period: int = 1,
                      today_str: str = "",
                      savant_current: dict = None,
                      savant_previous: dict = None,
                      mlb_stats_current: dict = None,
                      mlb_stats_previous: dict = None,
                      game_logs: dict = None) -> tuple:
    """
    Project fantasy points per pitcher using a hybrid model:
      - Skill-based stats (IP, K, BB, HBP) from MLB Stats API season averages
      - Luck-adjusted stats (H, ER) from Baseball Savant (xBA, xERA)
      - W/L from MLB Stats API but discounted 50% (too team-dependent)
      - Opponent quality adjustment via team wOBA factors
      - Park factor adjustment per start (Layer 3)
      - Year-over-year blending (2025 ↔ 2026) by innings pitched
      - Recent form weighting: 60% season / 40% last-4-starts (Layer 2)
 
    When Savant data is unavailable for a pitcher, falls back to pure
    counting-stat model so every pitcher gets a projection.
 
    player_starts: [{"name": "...", "starts": 2, "is_rp": False,
                     "startDates": [{"date": "...", "opponent": "COL", "is_home": True}]}, ...]
    team_woba_factors: { "LAD": 1.08, "CWS": 0.91, ... }
    savant_current:  { "sandy alcantara": {"xwoba": .186, "xera": 1.36, "xba": .156, ...} }
    savant_previous: { "sandy alcantara": {"xwoba": .300, "xera": 3.80, "xba": .240, ...} }
    game_logs:       { "sandy alcantara": [{"date": "...", "ip": 6.0, ...}, ...] }
 
    Returns tuple:
      proj_fpts:      { "Garrett Crochet": 34.2, ... }
      proj_blend:     { "Garrett Crochet": 0.3, ... }  ← this-year weight
      fpts_per_start: { "Garrett Crochet": 17.1, ... }  ← baseline, pre-matchup
    """
    team_woba_factors = team_woba_factors or {}
    savant_current    = savant_current or {}
    savant_previous   = savant_previous or {}
    game_logs         = game_logs or {}
    if not player_starts:
        return {}, {}, {}
 
    starts_by_name = {strip_accents(p["name"]): p for p in player_starts}
 
    def parse_ip(ip_str) -> float:
        try:
            parts = str(ip_str).split(".")
            full  = int(parts[0])
            outs  = int(parts[1]) if len(parts) > 1 else 0
            return full + outs / 3
        except Exception:
            return 0.0
 
    def per_game_avgs(stat: dict, games: int, is_rp: bool = False) -> dict:
        """Per-game averages from MLB Stats API season totals.
        Minimum sample: 3 starts for SPs, 5 appearances for RPs."""
        min_games = 5 if is_rp else 3
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
            # Extra fields needed for Savant hybrid
            "batters_faced": ip * 3 + h + bb + hb,  # approximate TBF per game
        }
 
    def apply_savant_adjustments(avgs: dict, savant_data: dict) -> dict:
        """
        Replace luck-influenced stats with Savant expected values.
        - H per start → xBA × batters_faced (removes BABIP luck)
        - ER per start → xERA × (IP / 9) (removes sequencing luck)
        - W/L → discounted 50% (team-dependent noise)
        Returns a new dict with adjusted values.
        """
        adjusted = dict(avgs)  # copy
        xba  = savant_data.get("xba", 0)
        xera = savant_data.get("xera", 0)
 
        if xba > 0 and adjusted["batters_faced"] > 0:
            # Expected hits = xBA × batters faced per game
            adjusted["h"] = xba * adjusted["batters_faced"]
 
        if xera > 0 and adjusted["ip"] > 0:
            # Expected ER = xERA × (IP per game / 9)
            adjusted["er"] = xera * (adjusted["ip"] / 9)
 
        # Discount W/L by 50% — heavily team-dependent
        adjusted["w"] *= 0.5
        adjusted["l"] *= 0.5
 
        return adjusted
 
    def apply_formula(avgs: dict) -> float:
        """Apply league scoring formula to per-game averages."""
        return (
            avgs["ip"] *  3 +
            avgs["so"] *  1 +
            avgs["h"]  * -1 +
            avgs["bb"] * -1 +
            avgs["er"] * -2 +
            avgs["hb"] * -1 +
            avgs["w"]  *  5 +
            avgs["l"]  * -5 +
            avgs["sv"] *  5
        )
 
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
        ip_threshold     = 20.0 if is_rp else 50.0
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
        # Look up Savant expected stats for this pitcher (both years)
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
        season_base = round(fpts_per_game, 1)  # capture pre-adjustment base
 
        # ── Layer 2: Recent form weighting ─────────────────────────────
        # If we have game logs with 4+ starts, compute a weighted average
        # of the last 4 starts (40/30/20/10) and blend with season rate.
        # Blend: 60% season base rate + 40% recent form.
        # This captures hot/cold streaks without overreacting.
        recent_form_fpts = None
        if not is_rp and game_logs:
            pitcher_games = game_logs.get(name_lower, [])
            if pitcher_games:
                recent_form_fpts = compute_recent_form_fpts(pitcher_games, n_starts=4)

        if recent_form_fpts is not None:
            # Blend: 60% season model + 40% recent form
            season_fpts = fpts_per_game
            fpts_per_game = season_fpts * 0.6 + recent_form_fpts * 0.4
            print(f"[espn.py]   ↳ {full_name} recent form: {recent_form_fpts:.1f} | "
                  f"season: {season_fpts:.1f} → blended: {fpts_per_game:.1f}")

        adjusted_base = round(fpts_per_game, 1)  # after recent form blend

        # ── Opponent quality + Park factor adjustment (Layers 1 & 3) ───
        # Each start gets two multipliers:
        #   1. wOBA factor — how good is the opposing lineup?
        #   2. Park factor — is this a hitter or pitcher park?
        # The park is determined by WHO IS HOME:
        #   - If our pitcher is home → our pitcher's team park
        #   - If our pitcher is away → opponent's team park
        start_dates = player_info.get("startDates", [])
        per_start_details = []
        if not is_rp and start_dates:
            adjusted_total = 0.0
            for sd in start_dates:
                opp       = sd.get("opponent", "")
                is_home   = sd.get("is_home", True)
                # wOBA factor: how strong is the opposing lineup
                woba_factor = team_woba_factors.get(opp, 1.0) if team_woba_factors else 1.0
                # Park factor: the HOME team's park is used
                park_team   = opp if not is_home else player_info.get("team", "")
                # If we don't know the pitcher's team, fall back to neutral
                if not park_team:
                    park_factor = 1.0
                else:
                    park_factor = get_park_factor(park_team)
                start_proj = fpts_per_game * woba_factor * park_factor
                adjusted_total += start_proj
                # Build per-start detail for tooltip
                location = "vs" if is_home else "@"
                per_start_details.append({
                    "label":    f"{location} {opp}",
                    "date":     sd.get("date", ""),
                    "woba":     round(woba_factor, 3),
                    "park":     round(park_factor, 3),
                    "parkTeam": park_team,
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
        # Lock projections for starts that have happened (today or past).
        # V1: stores a single float (fpts_per_game) — used by frontend
        # V2: stores full stat breakdown as JSON — used for accuracy tracking
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
                        woba_f    = team_woba_factors.get(opp, 1.0) if team_woba_factors else 1.0
                        park_tm   = opp if not is_home else player_info.get("team", "")
                        park_f    = get_park_factor(park_tm) if park_tm else 1.0
                        start_proj = fpts_per_game * woba_f * park_f
                        breakdown = {
                            "fpts": round(start_proj, 1),
                            "stats": {
                                "ip": round(blended["ip"], 2),
                                "so": round(blended["so"], 2),
                                "h":  round(blended["h"], 2),
                                "bb": round(blended["bb"], 2),
                                "er": round(blended["er"], 2),
                                "hb": round(blended["hb"], 2),
                                "w":  round(blended["w"], 3),
                                "l":  round(blended["l"], 3),
                                "sv": round(blended["sv"], 3),
                            },
                            "matchup": {
                                "opponent": opp,
                                "woba":     round(woba_f, 3),
                                "park":     round(park_f, 3),
                                "parkTeam": park_tm,
                                "isHome":   is_home,
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
 
        print(f"[espn.py] {full_name} [{model_label}]: "
              f"{round(this_year_weight*100)}% '26 / {round(last_year_weight*100)}% '25 | "
              f"{fpts_per_game:.1f} pts/game × {avg_factor:.3f} = {projected}"
              f"{' [recent form applied]' if recent_form_fpts is not None else ''}")
 
    return proj_fpts, proj_blend, fpts_per_start, proj_details


def get_actual_fpts(past_dates: list, player_names: set, headers: dict, cookies: dict, team_id: int = 0) -> tuple:
    """
    Fetch actual fantasy points, saves, and bench status per pitcher per day.
    Caches completed days in KV — only fetches from ESPN for uncached days.
    Also tracks which pitchers were on our team each day (for dropped player detection).
    """
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    base      = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    fpts_result  = {name: {} for name in player_names}
    saves_result = {name: {} for name in player_names}
    bench_result = {name: [] for name in player_names}
    my_team_pitchers_by_day = {}

    # ── Check cache for each past day ─────────────────────────────────────
    # Today is never cached (games may be in progress).
    # Completed days are cached permanently after first fetch.
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dates_to_fetch = []

    for date_str in past_dates:
        if date_str >= today_str:
            # Today or future — always fetch fresh
            dates_to_fetch.append(date_str)
            continue
        try:
            cached = cache_get(f"cache:daily:{date_str}")
            if cached:
                # Restore cached data into our result dicts
                cached_fpts    = cached.get("fpts", {})
                cached_saves   = cached.get("saves", {})
                cached_bench   = cached.get("bench", {})
                cached_my_team = cached.get("my_team", {})
                for name in player_names:
                    if name in cached_fpts:
                        fpts_result[name][date_str] = cached_fpts[name]
                    if name in cached_saves:
                        saves_result[name][date_str] = cached_saves[name]
                    if name in cached_bench:
                        bench_result[name].append(date_str)
                if cached_my_team:
                    my_team_pitchers_by_day[date_str] = cached_my_team
                continue
        except Exception:
            pass
        dates_to_fetch.append(date_str)

    if dates_to_fetch:
        print(f"[espn.py] Fetching actual FPTS for {len(dates_to_fetch)} days (cached {len(past_dates) - len(dates_to_fetch)})")
    else:
        print(f"[espn.py] All {len(past_dates)} days loaded from cache")

    # ── Fetch uncached days from ESPN ─────────────────────────────────────
    def fetch_one_day(date_str: str):
        scoring_period = date_to_scoring_period(date_str)
        try:
            r = requests.get(
                base,
                params=[("view", "mRoster"), ("scoringPeriodId", scoring_period)],
                cookies=cookies,
                headers=headers,
                timeout=15
            )
            if r.status_code != 200:
                return date_str, {}
            return date_str, r.json()
        except Exception as e:
            print(f"[espn.py] Failed to fetch scoring period {scoring_period}: {e}")
            return date_str, {}

    if dates_to_fetch:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_one_day, d): d for d in dates_to_fetch}
            for future in as_completed(futures):
                date_str, data = future.result()
                if not data:
                    continue
                scoring_period = date_to_scoring_period(date_str)

                # Collect ALL pitcher data for this day (unfiltered — for caching)
                day_fpts    = {}
                day_saves   = {}
                day_bench   = set()
                day_my_team = {}

                for team in data.get("teams", []):
                    is_my_team = (team.get("id") == team_id)
                    for entry in team.get("roster", {}).get("entries", []):
                        pool_entry = entry.get("playerPoolEntry", {})
                        player     = pool_entry.get("player", {})
                        name       = player.get("fullName", "")
                        if not name:
                            continue

                        # Track all pitchers on our team (for dropped player detection)
                        if is_my_team:
                            eligible_slots = set(player.get("eligibleSlots", []))
                            if 14 in eligible_slots or 13 in eligible_slots:
                                lineup_slot = entry.get("lineupSlotId", 0)
                                day_my_team[name] = {
                                    "lineupSlotId": lineup_slot,
                                    "team": player.get("proTeamId", 0),
                                    "eligible": sorted(list(eligible_slots)),
                                }

                        # Track bench status
                        lineup_slot = entry.get("lineupSlotId", 0)
                        if lineup_slot == 16:
                            day_bench.add(name)

                        # Pull per-game stats
                        for stat in player.get("stats", []):
                            if (stat.get("statSplitTypeId") == 5 and
                                    stat.get("scoringPeriodId") == scoring_period):
                                fpts = stat.get("appliedTotal", 0.0)
                                if fpts != 0:
                                    day_fpts[name] = round(float(fpts), 1)
                                raw_stats = stat.get("stats", {})
                                sv = raw_stats.get("57", 0)
                                if sv:
                                    day_saves[name] = int(sv)
                                break

                # Apply to result dicts (filtered by player_names)
                for name in player_names:
                    if name in day_fpts:
                        fpts_result[name][date_str] = day_fpts[name]
                    if name in day_saves:
                        saves_result[name][date_str] = day_saves[name]
                    if name in day_bench:
                        bench_result[name].append(date_str)
                if day_my_team:
                    my_team_pitchers_by_day[date_str] = day_my_team

                # Cache this day if it's fully completed (not today)
                if date_str < today_str:
                    try:
                        cache_set(f"cache:daily:{date_str}", {
                            "fpts":    day_fpts,
                            "saves":   day_saves,
                            "bench":   list(day_bench),
                            "my_team": day_my_team,
                        })
                    except Exception:
                        pass

    return fpts_result, saves_result, bench_result, my_team_pitchers_by_day


def get_league_data(team_id: int, week: int) -> dict:
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP     = get_pro_team_map(headers, cookies)
    base = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    # ── Team wOBA factors for opponent quality adjustment ─────────────────
    year_int = int(os.environ.get("ESPN_SEASON", "2026"))
    team_woba_factors = get_team_woba(year_int)

    # ── Fetch Savant expected stats (cached) ──────────────────────────────
    # Previous year: permanent cache (data is final)
    # Current year: 24-hour TTL (updates daily)
    savant_previous = {}
    savant_current  = {}
    try:
        savant_previous = cache_get(f"cache:savant:{year_int - 1}") or {}
        savant_current  = cache_get(f"cache:savant:{year_int}") or {}
    except Exception:
        pass

    if not savant_previous or not savant_current:
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if not savant_previous:
                    futures[executor.submit(fetch_expected_stats, year_int - 1)] = "prev"
                if not savant_current:
                    futures[executor.submit(fetch_expected_stats, year_int)] = "cur"
                for future in as_completed(futures):
                    label = futures[future]
                    result = future.result() or {}
                    if label == "prev":
                        savant_previous = result
                        try:
                            cache_set(f"cache:savant:{year_int - 1}", result)
                        except Exception:
                            pass
                    else:
                        savant_current = result
                        try:
                            cache_set(f"cache:savant:{year_int}", result, ttl_seconds=86400)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[espn.py] Savant fetch failed: {e}")

    print(f"[espn.py] Savant: {len(savant_current)} current, {len(savant_previous)} previous")

    # ── Fetch MLB Stats API season stats (cached) ─────────────────────────
    # Same pattern as Savant: 2025 permanent, 2026 with 24hr TTL
    mlb_stats_previous = {}
    mlb_stats_current  = {}
    try:
        mlb_stats_previous = cache_get(f"cache:mlb-stats:{year_int - 1}") or {}
        mlb_stats_current  = cache_get(f"cache:mlb-stats:{year_int}") or {}
    except Exception:
        pass

    if not mlb_stats_previous or not mlb_stats_current:
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if not mlb_stats_previous:
                    futures[executor.submit(fetch_season_stats, year_int - 1)] = "prev"
                if not mlb_stats_current:
                    futures[executor.submit(fetch_season_stats, year_int)] = "cur"
                for future in as_completed(futures):
                    label = futures[future]
                    result = future.result() or {}
                    if label == "prev":
                        mlb_stats_previous = result
                        try:
                            cache_set(f"cache:mlb-stats:{year_int - 1}", result)
                        except Exception:
                            pass
                    else:
                        mlb_stats_current = result
                        try:
                            cache_set(f"cache:mlb-stats:{year_int}", result, ttl_seconds=86400)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[espn.py] MLB stats fetch failed: {e}")

    print(f"[espn.py] MLB stats: {len(mlb_stats_current)} current, {len(mlb_stats_previous)} previous")

    # ── Fetch game logs for recent form weighting (Layer 2, cached) ───────
    # Current year only — we only care about recent form in this season.
    # 24hr TTL since new games happen daily.
    game_logs_current = {}
    try:
        game_logs_current = cache_get(f"cache:game-logs:{year_int}") or {}
    except Exception:
        pass

    if not game_logs_current:
        try:
            game_logs_current = fetch_game_logs(year_int) or {}
            if game_logs_current:
                try:
                    cache_set(f"cache:game-logs:{year_int}", game_logs_current, ttl_seconds=86400)
                except Exception:
                    pass
        except Exception as e:
            print(f"[espn.py] Game logs fetch failed: {e}")

    print(f"[espn.py] Game logs: {len(game_logs_current)} pitchers with game-level data")

    # ── Matchup period metadata ──────────────────────────────────────────
    mp            = MATCHUP_PERIODS.get(week, {})
    week_start    = ""
    week_end      = ""
    matchup_limit = int(os.environ.get("ESPN_STARTS_LIMIT", "12"))

    if mp:
        def fmt(d):
            return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")
        week_start    = fmt(mp["start"])
        week_end      = fmt(mp["end"])
        matchup_limit = mp["limit"]

    # ── Fetch roster ─────────────────────────────────────────────────────
    r = requests.get(
        base,
        params=[
            ("view", "mRoster"),
            ("view", "mTeam"),
            ("view", "mSettings"),
            ("view", "mMatchupScore"),
            ("_", int(datetime.now().timestamp())),
        ],
        cookies=cookies,
        headers=headers,
        timeout=15
    )
    if r.status_code != 200:
        raise Exception(f"ESPN returned HTTP {r.status_code}")

    data         = r.json()
    teams        = data.get("teams", [])
    my_team      = next((t for t in teams if t.get("id") == team_id), teams[0] if teams else {})
    team_name    = my_team.get("name", "").strip()
    current_week = data.get("scoringPeriodId", week)

    # ── Fetch per-player projected stats ─────────────────────────────────
    xff_roster = json.dumps({
        "players": {
            "filterIds": {"value": [
                e.get("playerId")
                for e in my_team.get("roster", {}).get("entries", [])
                if e.get("playerId")
            ]},
            "filterStatsForCurrentSeasonScoringPeriodId": {"value": [current_week]},
        }
    })
    stats_r = requests.get(
        base,
        params=[("view", "kona_player_info"), ("scoringPeriodId", current_week)],
        cookies=cookies,
        headers={**headers, "x-fantasy-filter": xff_roster},
        timeout=15
    )
    proj_fpts_by_player = {}
    if stats_r.status_code == 200:
        for p in stats_r.json().get("players", []):
            pid  = p.get("id")
            proj = p.get("playerPoolEntry", {}).get("appliedStatTotal", 0)
            proj_fpts_by_player[pid] = round(float(proj or 0), 1)

    # ── Fetch probable pitchers + full game schedule ──────────────────────
    roster_entries   = my_team.get("roster", {}).get("entries", [])
    all_player_names = [
        e.get("playerPoolEntry", {}).get("player", {}).get("fullName", "")
        for e in roster_entries
        if e.get("playerPoolEntry", {}).get("player", {}).get("fullName")
    ]
    # Build team_map so get_starts_for_players can add opponent to each startDate
    roster_team_map = {}
    for e in roster_entries:
        pool   = e.get("playerPoolEntry", {})
        player = pool.get("player", {})
        name   = player.get("fullName", "")
        pro_id = player.get("proTeamId", 0)
        if name and pro_id:
            roster_team_map[name] = PRO_TEAM_MAP.get(pro_id, "")
    starts_map, schedule = get_starts_for_players(all_player_names, week, team_map=roster_team_map)

    # ── Roster transaction lag fix ────────────────────────────────────────
    # Once any game today starts, ESPN locks the current scoring period's
    # roster. Transactions made after that won't appear until tomorrow's
    # scoring period. Detect this and re-fetch with scoringPeriodId + 1
    # so adds/drops made today are reflected immediately.
    if today_has_started(schedule):
        next_period = current_week + 1
        print(f"[espn.py] Games in progress — fetching roster at scoringPeriodId={next_period}")
        r2 = requests.get(
            base,
            params=[
                ("view", "mRoster"),
                ("view", "mTeam"),
                ("scoringPeriodId", next_period),
                ("_", int(datetime.now().timestamp())),
            ],
            cookies=cookies,
            headers=headers,
            timeout=15
        )
        if r2.status_code == 200:
            data2    = r2.json()
            teams2   = data2.get("teams", [])
            my_team2 = next((t for t in teams2 if t.get("id") == team_id), None)
            if my_team2:
                my_team        = my_team2
                roster_entries = my_team.get("roster", {}).get("entries", [])
                print(f"[espn.py] Roster re-fetched successfully at period {next_period}")
            else:
                print(f"[espn.py] Re-fetch succeeded but team {team_id} not found — keeping original")
        else:
            print(f"[espn.py] Re-fetch failed (HTTP {r2.status_code}) — keeping original roster")

    # ── Projection model inputs ─────────────────────────────────────────
    # Built AFTER transaction lag re-fetch so lineup slots are fresh.
    # Include ALL pitchers (including bench/IL) — they need projections
    # for locked past starts. The bench/IL zeroing only affects future
    # starts and happens later in the roster parsing step.
    days_in_period = 7
    if mp:
        start_d = datetime.strptime(mp["start"], "%Y-%m-%d").date()
        end_d   = datetime.strptime(mp["end"],   "%Y-%m-%d").date()
        days_in_period = (end_d - start_d).days + 1

    projection_inputs = []
    for entry in roster_entries:
        pool_entry     = entry.get("playerPoolEntry", {})
        player         = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        full_name      = player.get("fullName", "")
        if not full_name:
            continue
        if not (14 in eligible_slots or 13 in eligible_slots):
            continue
        is_rp = (14 not in eligible_slots and 13 in eligible_slots)
        pitcher_data = starts_map.get(full_name, {})
        pro_team_id  = player.get("proTeamId", 0)
        projection_inputs.append({
            "name":           full_name,
            "starts":         pitcher_data.get("starts", 0),
            "startDates":     pitcher_data.get("startDates", []),
            "is_rp":          is_rp,
            "days_in_period": days_in_period,
            "team":           PRO_TEAM_MAP.get(pro_team_id, ""),
        })

    proj_fpts_by_name, proj_blend_by_name, fpts_per_start_roster, proj_details_roster = get_projected_fpts(
        projection_inputs, team_woba_factors,
        season=year_int, period=week,
        today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        savant_current=savant_current,
        savant_previous=savant_previous,
        mlb_stats_current=mlb_stats_current,
        mlb_stats_previous=mlb_stats_previous,
        game_logs=game_logs_current,
    )

    # ── Parse roster ──────────────────────────────────────────────────────
    roster_sps  = []
    SP_ELIGIBLE = {14}
    RP_ELIGIBLE = {13}
    today_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for entry in roster_entries:
        pool_entry     = entry.get("playerPoolEntry", {})
        player         = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        player_id      = entry.get("playerId")

        if not (eligible_slots & SP_ELIGIBLE) and not (eligible_slots & RP_ELIGIBLE):
            continue

        injured      = player.get("injured", False)
        slot_label   = get_slot_label(eligible_slots, injured)
        status_label = get_status(injured)
        pro_team_id  = player.get("proTeamId", 0)
        team_abbrev  = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
        player_name  = player.get("fullName", "Unknown")

        # All pitchers treated identically — bench status is a daily lineup
        # decision and does not affect projections or start counting.
        # IL players (injured=True) get the same projection treatment but
        # are visually distinguished in the frontend with opacity + IL badge.
        pitcher_data     = starts_map.get(player_name, {"starts": 0, "startDates": []})
        scheduled_starts = pitcher_data["starts"]
        start_dates      = pitcher_data["startDates"]
        proj_fpts        = proj_fpts_by_name.get(
            player_name,
            proj_fpts_by_player.get(player_id, 0.0)
        )

        # Determine underlying position (SP or RP) independent of IL status
        if 14 in eligible_slots:
            position = "SP"
        elif 13 in eligible_slots:
            position = "RP"
        else:
            position = "P"

        roster_sps.append({
            "name":         player_name,
            "team":         team_abbrev,
            "slot":         slot_label,
            "position":     position,
            "injuryStatus": status_label,
            "starts":       scheduled_starts,
            "startDates":   start_dates,
            "projFpts":     proj_fpts,
            "projBlend":    proj_blend_by_name.get(player_name, 0.0),
            "percentOwned": round(pool_entry.get("percentOwned", 100), 1),
        })

    slot_order = {"SP": 0, "RP": 1, "IL": 2, "Bench": 3, "P": 1}
    roster_sps.sort(key=lambda x: (slot_order.get(x["slot"], 1), -x["starts"], -x["projFpts"]))

    # ── Fetch free agents ─────────────────────────────────────────────────
    xff_fa = json.dumps({
        "players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "filterSlotIds": {"value": [14]},
            "limit": 100,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "filterStatsForCurrentSeasonScoringPeriodId": {"value": [current_week]},
        }
    })
    fa_r = requests.get(
        base,
        params=[("view", "kona_player_info"), ("scoringPeriodId", current_week)],
        cookies=cookies,
        headers={**headers, "x-fantasy-filter": xff_fa},
        timeout=15
    )
    free_agents = []
    fa_fpts_per_start = {}
    fa_proj_details = {}
    if fa_r.status_code == 200:
        fa_names      = []
        fa_players_raw = []
        for p in fa_r.json().get("players", []):
            player = p.get("player", {})
            if not player.get("fullName"):
                continue
            eligible_slots = set(player.get("eligibleSlots", []))
            if 14 not in eligible_slots:
                continue
            fa_names.append(player["fullName"])
            fa_players_raw.append(p)

        fa_team_map = {}
        for p in fa_players_raw:
            player = p.get("player", {})
            name   = player.get("fullName", "")
            pro_id = player.get("proTeamId", 0)
            if name and pro_id:
                fa_team_map[name] = PRO_TEAM_MAP.get(pro_id, "")
        fa_starts_map, _ = get_starts_for_players(fa_names, week, team_map=fa_team_map)

        # Build projection inputs for free agents — same model as roster players
        fa_projection_inputs = []
        for p in fa_players_raw:
            player         = p.get("player", {})
            fa_name        = player.get("fullName", "")
            eligible_slots = set(player.get("eligibleSlots", []))
            is_rp          = (14 not in eligible_slots and 13 in eligible_slots)
            if not fa_name:
                continue
            fa_pitcher_data = fa_starts_map.get(fa_name, {})
            pro_team_id     = player.get("proTeamId", 0)
            fa_projection_inputs.append({
                "name":           fa_name,
                "starts":         fa_pitcher_data.get("starts", 0),
                "startDates":     fa_pitcher_data.get("startDates", []),
                "is_rp":          is_rp,
                "days_in_period": days_in_period,
                "team":           PRO_TEAM_MAP.get(pro_team_id, ""),
            })

        fa_proj_fpts, fa_proj_blend, fa_fpts_per_start, fa_proj_details = get_projected_fpts(
            fa_projection_inputs, team_woba_factors,
            season=year_int, period=week,
            today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            savant_current=savant_current,
            savant_previous=savant_previous,
            mlb_stats_current=mlb_stats_current,
            mlb_stats_previous=mlb_stats_previous,
            game_logs=game_logs_current,
        )

        inj_label_map = {
            "ACTIVE": "Active", "NORMAL": "Active",
            "FIFTEEN_DAY_DL": "IL15", "SIXTY_DAY_DL": "IL60",
            "DAY_TO_DAY": "DTD", "SUSPENSION": "SUSP",
        }
        for p in fa_players_raw:
            player       = p.get("player", {})
            fa_name      = player.get("fullName", "Unknown")
            pro_team_id  = player.get("proTeamId", 0)
            team_abbrev  = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
            raw_inj      = player.get("injuryStatus", "ACTIVE")
            pitcher_data = fa_starts_map.get(fa_name, {"starts": 0, "startDates": []})

            free_agents.append({
                "name":         fa_name,
                "team":         team_abbrev,
                "injuryStatus": inj_label_map.get(raw_inj, raw_inj),
                "percentOwned": round(player.get("ownership", {}).get("percentOwned", 0), 1),
                "projFpts":     fa_proj_fpts.get(fa_name, 0.0),
                "projBlend":    fa_proj_blend.get(fa_name, 0.0),
                "starts":       pitcher_data["starts"],
                "startDates":   pitcher_data["startDates"],
                "opps":         "",
                "checked":      player.get("ownership", {}).get("percentOwned", 0) >= 15,
            })

    # ── Fetch actual FPTS for past dates ──────────────────────────────────
    today     = datetime.now(timezone.utc).date()
    all_dates = []
    if mp:
        start = datetime.strptime(mp["start"], "%Y-%m-%d").date()
        end   = datetime.strptime(mp["end"], "%Y-%m-%d").date()
        d     = start
        while d < today and d <= end:
            all_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

    all_pitcher_names = set(p["name"] for p in roster_sps)
    fa_pitcher_names  = set(p["name"] for p in free_agents)
    actual_fpts  = {}
    actual_saves = {}
    bench_days   = {}
    my_team_pitchers_by_day = {}
    if all_dates:
        actual_fpts, actual_saves, bench_days, my_team_pitchers_by_day = get_actual_fpts(
            all_dates, all_pitcher_names | fa_pitcher_names, headers, cookies, team_id
        )

    # Split actual FPTS back into roster and FA subsets for the frontend
    fa_actual_fpts = {name: actual_fpts[name] for name in fa_pitcher_names if name in actual_fpts}
    roster_actual_fpts = {name: actual_fpts[name] for name in all_pitcher_names if name in actual_fpts}

    # ── Detect dropped players ────────────────────────────────────────────
    # Players who were on our team during this period but are no longer in
    # the current roster. They may have earned points that counted toward
    # the matchup score while they were active.
    dropped_players = []
    current_roster_names = set(p["name"] for p in roster_sps)
    all_past_names = set()
    for day_players in my_team_pitchers_by_day.values():
        all_past_names.update(day_players.keys())
    dropped_names = all_past_names - current_roster_names

    for name in sorted(dropped_names):
        # Find the days this player was on our team
        days_on_team = sorted([d for d, players in my_team_pitchers_by_day.items() if name in players])
        if not days_on_team:
            continue
        # Get their team/position from their first appearance
        first_day = days_on_team[0]
        player_info = my_team_pitchers_by_day[first_day][name]
        eligible = set(player_info.get("eligible", []))
        if 14 in eligible:
            position = "SP"
        elif 13 in eligible:
            position = "RP"
        else:
            position = "P"
        # Only include SP-type dropped players (RPs are less relevant for starts tracking)
        if position != "SP":
            continue
        team_abbrev = PRO_TEAM_MAP.get(player_info.get("team", 0), "")
        # Collect actual FPTS for this player across the period
        # They might be in fa_actual_fpts if they're now a free agent
        player_fpts = actual_fpts.get(name, fa_actual_fpts.get(name, {}))
        dropped_players.append({
            "name":       name,
            "team":       team_abbrev,
            "slot":       "EX",
            "position":   "SP",
            "injuryStatus": "Dropped",
            "starts":     0,
            "startDates": [],
            "projFpts":   0.0,
            "projBlend":  0.0,
            "percentOwned": 0.0,
            "daysOnTeam": days_on_team,
        })
        # Add their FPTS to roster actual so they show in the grid
        if name not in roster_actual_fpts and player_fpts:
            roster_actual_fpts[name] = player_fpts

    return {
        "ok":                True,
        "teamName":          team_name,
        "currentWeek":       current_week,
        "weekStart":         week_start,
        "weekEnd":           week_end,
        "rosterSPs":         roster_sps,
        "freeAgentSPs":      free_agents,
        "schedule":          schedule,
        "matchupDates":      [mp["start"], mp["end"]] if mp else [],
        "actualFpts":        roster_actual_fpts,
        "actualSaves":       actual_saves,
        "benchDays":         bench_days,
        "rosterFptsPerStart": fpts_per_start_roster,
        "faFptsPerStart":     fa_fpts_per_start,
        "faActualFpts":       fa_actual_fpts,
        "lockedProjections":  get_all_locked_projections(year_int, week),
        "droppedPlayers":     dropped_players,
        "projectionDetails":  proj_details_roster,
        "faProjectionDetails": fa_proj_details,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs      = parse_qs(urlparse(self.path).query)
        env_tid = os.environ.get("ESPN_TEAM_ID", "")
        team_id = int(env_tid) if env_tid else int(qs.get("teamId", ["1"])[0])
        week    = int(qs.get("week", ["1"])[0])

        try:
            payload = get_league_data(team_id, week)
            payload["teamId"]       = team_id
            payload["defaultLimit"] = int(os.environ.get("ESPN_STARTS_LIMIT", "12"))
        except Exception as e:
            payload = {"ok": False, "error": str(e)}

        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()