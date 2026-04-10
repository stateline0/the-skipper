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
from mlb import get_starts_for_players, get_team_woba, MATCHUP_PERIODS
from kv import get_locked_projection, set_locked_projection, get_all_locked_projections


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


def get_slot_label(lineup_slot_id: int, eligible_slots: set, inj_status: str) -> str:
    # Slot 17 = true IL (injured players)
    # Slot 16 = bench (healthy players parked there)
    if lineup_slot_id == 17:
        return "IL"
    if lineup_slot_id == 16:
        # Bench — classify by position eligibility
        if 14 in eligible_slots:
            return "SP"
        if 13 in eligible_slots:
            return "RP"
    if 14 in eligible_slots:
        return "SP"
    if 13 in eligible_slots and 14 not in eligible_slots:
        return "RP"
    return "P"


def get_status(lineup_slot_id: int, inj_status: str) -> str:
    if lineup_slot_id == 17:
        return "IL"
    if lineup_slot_id == 16:
        return "Bench"
    if inj_status and inj_status not in ("ACTIVE", "NORMAL", ""):
        return inj_status
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


def get_projected_fpts(player_starts: list, team_woba_factors: dict = None,
                       season: int = 2026, period: int = 1,
                       today_str: str = "") -> tuple:
    """
    Project fantasy points per pitcher by blending 2025 and 2026 season stats,
    adjusted for opponent quality using team wOBA factors.

    Blend weight shifts from 100% last year to 100% this year as the pitcher
    accumulates innings in 2026. Threshold for full trust = 50 IP for SPs, 20 IP for RPs.

    player_starts: [{"name": "Garrett Crochet", "starts": 2, "is_rp": False,
                     "startDates": [{"date": "...", "opponent": "COL", ...}]}, ...]
    team_woba_factors: { "LAD": 1.08, "CWS": 0.91, ... } — relative to league avg

    Returns tuple:
      proj_fpts:     { "Garrett Crochet": 34.2, ... }
      proj_blend:    { "Garrett Crochet": 0.3, ... }
      fpts_per_start: { "Garrett Crochet": 17.1, ... }  ← baseline, pre-matchup

    League scoring settings (Good Season Imanagas):
      IP:  +3    H:  -1    ER: -2    BB: -1
      HB:  -1    K:  +1    W:  +5    L:  -5    SV: +5
    """
    team_woba_factors = team_woba_factors or {}
    if not player_starts:
        return {}, {}

    starts_by_name = {strip_accents(p["name"]): p for p in player_starts}

    def fetch_season_stats(season: int) -> dict:
        """Fetch season pitching stats. Returns { fullname_lower: stat_dict }"""
        try:
            r = requests.get(
                "https://statsapi.mlb.com/api/v1/stats",
                params={
                    "stats":      "season",
                    "playerPool": "all",
                    "group":      "pitching",
                    "season":     str(season),
                    "gameType":   "R",
                    "limit":      1000,
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"[espn.py] MLB Stats API {season} returned {r.status_code}")
                return {}
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            result = {}
            for split in splits:
                name = split.get("player", {}).get("fullName", "")
                if name:
                    result[strip_accents(name)] = split.get("stat", {})
            return result
        except Exception as e:
            print(f"[espn.py] Failed to fetch {season} MLB stats: {e}")
            return {}

    def parse_ip(ip_str) -> float:
        """Convert IP string like '34.2' to actual innings (34.667)."""
        try:
            parts = str(ip_str).split(".")
            full  = int(parts[0])
            outs  = int(parts[1]) if len(parts) > 1 else 0
            return full + outs / 3
        except Exception:
            return 0.0

    def per_game_avgs(stat: dict, games: int, is_rp: bool = False) -> dict:
        """Calculate per-game averages from season totals. Works for both SP and RP.
        Requires minimum sample size to avoid wild projections from tiny samples:
        SPs need at least 3 starts, RPs need at least 5 appearances."""
        min_games = 5 if is_rp else 3
        if games < min_games:
            return None
        return {
            "ip": parse_ip(stat.get("inningsPitched", "0.0")) / games,
            "so": int(stat.get("strikeOuts",        0)) / games,
            "h":  int(stat.get("hits",              0)) / games,
            "bb": int(stat.get("baseOnBalls",       0)) / games,
            "er": int(stat.get("earnedRuns",        0)) / games,
            "hb": int(stat.get("hitBatsmen",        0)) / games,
            "w":  int(stat.get("wins",              0)) / games,
            "l":  int(stat.get("losses",            0)) / games,
            "sv": int(stat.get("saves",             0)) / games,
        }

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

    # Fetch both seasons in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        f2026 = executor.submit(fetch_season_stats, 2026)
        f2025 = executor.submit(fetch_season_stats, 2025)
        stats_2026 = f2026.result()
        stats_2025 = f2025.result()

    proj_fpts      = {}
    proj_blend     = {}
    fpts_per_start = {}

    for name_lower, player_info in starts_by_name.items():
        full_name        = player_info["name"]
        projected_starts = player_info["starts"]
        is_rp            = player_info.get("is_rp", False)

        stat_26 = stats_2026.get(name_lower, {})
        stat_25 = stats_2025.get(name_lower, {})

        # For SPs use gamesStarted; for RPs use gamesPlayed (appearances)
        if is_rp:
            gs_26 = int(stat_26.get("gamesPlayed", 0))
            gs_25 = int(stat_25.get("gamesPlayed", 0))
        else:
            gs_26 = int(stat_26.get("gamesStarted", 0))
            gs_25 = int(stat_25.get("gamesStarted", 0))

        ip_26 = parse_ip(stat_26.get("inningsPitched", "0.0"))

        # Blend weight: ramp from 0% to 100% this year as IP crosses threshold.
        # SPs reach full trust at 50 IP (~9 starts, ~6 weeks).
        # RPs reach full trust at 20 IP (~20 appearances, ~6 weeks).
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
            blended          = avgs_25
            this_year_weight = 0.0
            last_year_weight = 1.0
        elif avgs_25 is None:
            blended          = avgs_26
            this_year_weight = 1.0
            last_year_weight = 0.0
        else:
            blended = {
                s: avgs_26[s] * this_year_weight + avgs_25[s] * last_year_weight
                for s in avgs_26
            }

        fpts_per_game = apply_formula(blended)

        # Apply opponent quality adjustment per start using team wOBA factors.
        # For each projected start, look up the opponent and scale fpts_per_game.
        # Missing opponent or factor → use 1.0 (no adjustment).
        start_dates = player_info.get("startDates", [])
        if not is_rp and start_dates and team_woba_factors:
            adjusted_total = 0.0
            for sd in start_dates:
                opp    = sd.get("opponent", "")
                factor = team_woba_factors.get(opp, 1.0)
                adjusted_total += fpts_per_game * factor
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

        # ── Per-start locking ─────────────────────────────────────────────
        # For starts that are today or past, lock fpts_per_game into KV
        # so the projection is frozen at game time. Future starts stay live.
        if today_str and start_dates and not is_rp:
            for sd in start_dates:
                date = sd.get("date", "")
                if date and date <= today_str:
                    existing = get_locked_projection(season, period, full_name, date)
                    if existing is None:
                        set_locked_projection(season, period, full_name, date,
                                              round(fpts_per_game, 1))

        print(f"[espn.py] {full_name}: {round(this_year_weight*100)}% '26 / "
              f"{round(last_year_weight*100)}% '25 | "
              f"{fpts_per_game:.1f} pts/game × factor {avg_factor:.3f} = {projected}")

    return proj_fpts, proj_blend, fpts_per_start


def get_actual_fpts(past_dates: list, player_names: set, headers: dict, cookies: dict) -> dict:
    """
    Fetch actual fantasy points, saves, and bench status per pitcher per day.
    Fires one ESPN API request per date, in parallel.
    Returns:
      actualFpts:  { "Garrett Crochet": { "2026-03-26": 26.0, ... }, ... }
      actualSaves: { "Edwin Diaz":       { "2026-03-27": 1,   ... }, ... }
      benchDays:   { "Edwin Diaz":       ["2026-03-27", ...],       ... }
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

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_one_day, d): d for d in past_dates}
        for future in as_completed(futures):
            date_str, data = future.result()
            if not data:
                continue
            scoring_period = date_to_scoring_period(date_str)
            for team in data.get("teams", []):
                for entry in team.get("roster", {}).get("entries", []):
                    pool_entry = entry.get("playerPoolEntry", {})
                    player     = pool_entry.get("player", {})
                    name       = player.get("fullName", "")
                    if name not in player_names:
                        continue

                    # Track bench status for this specific day
                    lineup_slot = entry.get("lineupSlotId", 0)
                    if lineup_slot == 16:
                        bench_result[name].append(date_str)

                    # Pull per-game stats for this scoring period
                    for stat in player.get("stats", []):
                        if (stat.get("statSplitTypeId") == 5 and
                                stat.get("scoringPeriodId") == scoring_period):
                            fpts = stat.get("appliedTotal", 0.0)
                            fpts_result[name][date_str] = round(float(fpts), 1)

                            # Stat ID 57 = saves
                            raw_stats = stat.get("stats", {})
                            saves = raw_stats.get("57", 0)
                            if saves:
                                saves_result[name][date_str] = int(saves)
                            break

    return fpts_result, saves_result, bench_result


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

    # Option B inputs — filled with starts after starts_map is available below
    option_b_inputs = []
    for entry in my_team.get("roster", {}).get("entries", []):
        pool_entry     = entry.get("playerPoolEntry", {})
        player         = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        lineup_slot    = entry.get("lineupSlotId", 0)
        full_name      = player.get("fullName", "")
        if not full_name:
            continue
        if not (14 in eligible_slots or 13 in eligible_slots):
            continue
        if lineup_slot in (16, 17):
            continue
        is_rp = (14 not in eligible_slots and 13 in eligible_slots)
        option_b_inputs.append({
            "name":   full_name,
            "starts": 0,
            "is_rp":  is_rp,
        })

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

    # Fill in projected starts and period length for Option B
    days_in_period = 7
    if mp:
        start_d = datetime.strptime(mp["start"], "%Y-%m-%d").date()
        end_d   = datetime.strptime(mp["end"],   "%Y-%m-%d").date()
        days_in_period = (end_d - start_d).days + 1

    for entry in option_b_inputs:
        pitcher_data            = starts_map.get(entry["name"], {})
        entry["starts"]         = pitcher_data.get("starts", 0)
        entry["startDates"]     = pitcher_data.get("startDates", [])
        entry["days_in_period"] = days_in_period

    proj_fpts_by_name, proj_blend_by_name, fpts_per_start_roster = get_projected_fpts(
        option_b_inputs, team_woba_factors,
        season=year_int, period=week,
        today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

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

        lineup_slot  = entry.get("lineupSlotId", 0)
        inj_status   = pool_entry.get("injuryStatus", "")
        slot_label   = get_slot_label(lineup_slot, eligible_slots, inj_status)
        status_label = get_status(lineup_slot, inj_status)
        pro_team_id  = player.get("proTeamId", 0)
        team_abbrev  = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
        player_name  = player.get("fullName", "Unknown")

        if lineup_slot in (16, 17):
            # IL or Bench — zero out future projections but keep past start history
            pitcher_data     = starts_map.get(player_name, {"starts": 0, "startDates": []})
            past_start_dates = [s for s in pitcher_data["startDates"] if s["date"] < today_str]
            scheduled_starts = 0
            proj_fpts        = 0.0
            start_dates      = past_start_dates
        else:
            pitcher_data     = starts_map.get(player_name, {"starts": 0, "startDates": []})
            scheduled_starts = pitcher_data["starts"]
            start_dates      = pitcher_data["startDates"]
            proj_fpts        = proj_fpts_by_name.get(
                player_name,
                proj_fpts_by_player.get(player_id, 0.0)
            )

        roster_sps.append({
            "name":         player_name,
            "team":         team_abbrev,
            "slot":         slot_label,
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

        # Build Option B inputs for free agents — same model as roster players
        fa_option_b_inputs = []
        for p in fa_players_raw:
            player         = p.get("player", {})
            fa_name        = player.get("fullName", "")
            eligible_slots = set(player.get("eligibleSlots", []))
            is_rp          = (14 not in eligible_slots and 13 in eligible_slots)
            if not fa_name:
                continue
            fa_pitcher_data = fa_starts_map.get(fa_name, {})
            fa_option_b_inputs.append({
                "name":           fa_name,
                "starts":         fa_pitcher_data.get("starts", 0),
                "startDates":     fa_pitcher_data.get("startDates", []),
                "is_rp":          is_rp,
                "days_in_period": days_in_period,
            })

        fa_proj_fpts, fa_proj_blend, fa_fpts_per_start = get_projected_fpts(
            fa_option_b_inputs, team_woba_factors,
            season=year_int, period=week,
            today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
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
    if all_dates:
        actual_fpts, actual_saves, bench_days = get_actual_fpts(
            all_dates, all_pitcher_names | fa_pitcher_names, headers, cookies
        )

    # Split actual FPTS back into roster and FA subsets for the frontend
    fa_actual_fpts = {name: actual_fpts[name] for name in fa_pitcher_names if name in actual_fpts}
    roster_actual_fpts = {name: actual_fpts[name] for name in all_pitcher_names if name in actual_fpts}

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
        "_debug_shane_baz": starts_map.get("Shane Baz", "NOT FOUND"),
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