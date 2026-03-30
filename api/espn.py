"""
/api/espn.py  — Vercel Python serverless function
Fetches roster + free agents from ESPN Fantasy Baseball API.
Probable pitcher data and game schedule come from mlb.py.
"""
import json
import os
import sys
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

# Import our own mlb.py module which lives in the same /api directory.
# We add /var/task/api to the path so Python can find it on Vercel.
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mlb import get_starts_for_players, MATCHUP_PERIODS


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


def get_slot_label(lineup_slot_id: int, eligible_slots: set) -> str:
    if lineup_slot_id in (16, 17):
        return "IL"
    if 14 in eligible_slots:
        return "SP"
    if 13 in eligible_slots and 14 not in eligible_slots:
        return "RP"
    return "P"


def get_status(lineup_slot_id: int, inj_status: str) -> str:
    if lineup_slot_id in (16, 17):
        return "IL"
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


from concurrent.futures import ThreadPoolExecutor, as_completed

SEASON_START = datetime(2026, 3, 25)  # Scoring period 1 = March 25

def date_to_scoring_period(date_str: str) -> int:
    """Convert a YYYY-MM-DD date string to ESPN's daily scoring period ID."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - SEASON_START).days + 1

def get_actual_fpts(past_dates: list, player_names: set, headers: dict, cookies: dict) -> dict:
    """
    Fetch actual fantasy points earned per pitcher per day for all past dates.
    Fires one ESPN API request per date, in parallel.
    Returns: { "Garrett Crochet": { "2026-03-26": 26.0, ... }, ... }
    """
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    base      = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    # Result dict: player_name -> { date_str -> fpts }
    result = {name: {} for name in player_names}

    def fetch_one_day(date_str: str):
        """Fetch stats for a single scoring period. Returns (date_str, data)."""
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

    # Fire all requests in parallel — much faster than sequential
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_one_day, d): d for d in past_dates}
        for future in as_completed(futures):
            date_str, data = future.result()
            if not data:
                continue
            scoring_period = date_to_scoring_period(date_str)

            # Walk every team's roster looking for our players
            for team in data.get("teams", []):
                for entry in team.get("roster", {}).get("entries", []):
                    player = entry.get("playerPoolEntry", {}).get("player", {})
                    name   = player.get("fullName", "")
                    if name not in player_names:
                        continue
                    # Find the per-game stat entry for this scoring period
                    for stat in player.get("stats", []):
                        if (stat.get("statSplitTypeId") == 5 and
                                stat.get("scoringPeriodId") == scoring_period):
                            fpts = stat.get("appliedTotal", 0.0)
                            result[name][date_str] = round(float(fpts), 1)
                            break

    return result


def get_league_data(team_id: int, week: int) -> dict:
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP     = get_pro_team_map(headers, cookies)
    base = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    # ── Matchup period metadata ──────────────────────────────────────────
    mp         = MATCHUP_PERIODS.get(week, {})
    week_start = ""
    week_end   = ""
    matchup_limit = int(os.environ.get("ESPN_STARTS_LIMIT", "12"))

    if mp:
        def fmt(d):
            return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")
        week_start    = fmt(mp["start"])
        week_end      = fmt(mp["end"])
        matchup_limit = mp["limit"]

    # ── Fetch roster (no scoringPeriodId — ESPN defaults to today's roster) ──
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

    # ── Fetch per-player projected stats ────────────────────────────────
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

    # ── Fetch probable pitchers + full game schedule from mlb.py ────────
    roster_entries = my_team.get("roster", {}).get("entries", [])
    all_player_names = [
        e.get("playerPoolEntry", {}).get("player", {}).get("fullName", "")
        for e in roster_entries
        if e.get("playerPoolEntry", {}).get("player", {}).get("fullName")
    ]
    # get_starts_for_players returns (starts_map, schedule)
    # starts_map: { "Garrett Crochet": {"starts": 2, "startDates": [...]} }
    # schedule:   { "2026-03-26": { "BOS": {opponent, is_home, status} } }
    starts_map, schedule = get_starts_for_players(all_player_names, week)

    # ── Parse roster ────────────────────────────────────────────────────
    roster_sps = []
    SP_ELIGIBLE = {14}
    RP_ELIGIBLE = {13}
    IL_SLOTS    = {16, 17}

    for entry in roster_entries:
        pool_entry     = entry.get("playerPoolEntry", {})
        player         = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        player_id      = entry.get("playerId")

        if not (eligible_slots & SP_ELIGIBLE) and not (eligible_slots & RP_ELIGIBLE):
            continue

        lineup_slot  = entry.get("lineupSlotId", 0)
        inj_status   = pool_entry.get("injuryStatus", "")
        slot_label   = get_slot_label(lineup_slot, eligible_slots)
        status_label = get_status(lineup_slot, inj_status)
        pro_team_id  = player.get("proTeamId", 0)
        team_abbrev  = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
        player_name  = player.get("fullName", "Unknown")

        if lineup_slot in IL_SLOTS:
            scheduled_starts = 0
            proj_fpts        = 0.0
            start_dates      = []
        else:
            pitcher_data     = starts_map.get(player_name, {"starts": 0, "startDates": []})
            scheduled_starts = pitcher_data["starts"]
            start_dates      = pitcher_data["startDates"]
            proj_fpts        = proj_fpts_by_player.get(player_id, 0.0)

        roster_sps.append({
            "name":          player_name,
            "team":          team_abbrev,
            "slot":          slot_label,
            "injuryStatus":  status_label,
            "starts":        scheduled_starts,
            "startDates":    start_dates,   # [{date, confirmed}, ...]
            "projFpts":      proj_fpts,
            "percentOwned":  round(pool_entry.get("percentOwned", 100), 1),
        })

    slot_order = {"SP": 0, "RP": 1, "IL": 2, "P": 1}
    roster_sps.sort(key=lambda x: (slot_order.get(x["slot"], 1), -x["starts"], -x["projFpts"]))

    # ── Fetch free agents ────────────────────────────────────────────────
    xff_fa = json.dumps({
        "players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
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
        fa_names = []
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

        # Get starts + schedule for free agents (schedule already fetched above,
        # but get_starts_for_players is cheap to call again for FA names)
        fa_starts_map, _ = get_starts_for_players(fa_names, week)

        inj_label_map = {
            "ACTIVE": "Active", "NORMAL": "Active",
            "FIFTEEN_DAY_DL": "IL15", "SIXTY_DAY_DL": "IL60",
            "DAY_TO_DAY": "DTD", "SUSPENSION": "SUSP",
        }
        for p in fa_players_raw:
            player         = p.get("player", {})
            fa_name        = player.get("fullName", "Unknown")
            pro_team_id    = player.get("proTeamId", 0)
            team_abbrev    = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
            raw_inj        = player.get("injuryStatus", "ACTIVE")
            pitcher_data   = fa_starts_map.get(fa_name, {"starts": 0, "startDates": []})

            free_agents.append({
                "name":         fa_name,
                "team":         team_abbrev,
                "injuryStatus": inj_label_map.get(raw_inj, raw_inj),
                "percentOwned": round(player.get("ownership", {}).get("percentOwned", 0), 1),
                "projFpts":     0.0,
                "starts":       pitcher_data["starts"],
                "startDates":   pitcher_data["startDates"],
                "opps":         "",
                "checked":      player.get("ownership", {}).get("percentOwned", 0) >= 15,
            })

    # ── Fetch actual FPTS for past starts ───────────────────────────────
    today     = datetime.now(timezone.utc).date()
    all_dates = []
    if mp:
        from datetime import timedelta
        start = datetime.strptime(mp["start"], "%Y-%m-%d").date()
        end   = datetime.strptime(mp["end"], "%Y-%m-%d").date()
        d     = start
        while d < today and d <= end:
            all_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

    all_pitcher_names = set(
        p["name"] for p in roster_sps
    )
    actual_fpts = {}
    if all_dates:
        actual_fpts = get_actual_fpts(all_dates, all_pitcher_names, headers, cookies)

    return {
        "ok":           True,
        "teamName":     team_name,
        "currentWeek":  current_week,
        "weekStart":    week_start,
        "weekEnd":      week_end,
        "rosterSPs":    roster_sps,
        "freeAgentSPs": free_agents,
        "schedule":     schedule,
        "matchupDates": [mp["start"], mp["end"]] if mp else [],
        "actualFpts":   actual_fpts,
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