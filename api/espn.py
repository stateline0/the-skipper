"""
/api/espn.py  — Vercel Python serverless function
Fetches roster + free agents from ESPN Fantasy Baseball API.
"""
import json
import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone


def get_headers_and_cookies():
    espn_s2 = os.environ.get("ESPN_S2", "").strip()
    swid = os.environ.get("ESPN_SWID", "").strip()
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
    Fetch current MLB team ID -> abbreviation mapping directly from ESPN's
    fantasy baseball API using the mSettings view which includes proTeams.
    """
    try:
        league_id = os.environ["ESPN_LEAGUE_ID"]
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
                abbrev = team.get("abbrev", "")
                if team_id and abbrev:
                    team_map[team_id] = abbrev
            if team_map:
                return team_map
    except Exception as e:
        print(f"[espn.py] Failed to fetch pro team map: {e}")

    # Best-effort hardcoded map based on verified 2026 player data
    # Confirmed via ESPN API proTeamId lookups on actual roster players
    return {
        1:  "BAL", 2:  "BOS", 3:  "LAA", 4:  "CWS", 5:  "CLE",
        6:  "DET", 7:  "KC",  8:  "MIL", 9:  "MIN", 10: "NYY",
        11: "ATH", 12: "SEA", 13: "TEX", 14: "TOR", 15: "ATL",
        16: "CHC", 17: "CIN", 18: "HOU", 19: "LAD", 20: "WSH",
        21: "NYM", 22: "PHI", 23: "PIT", 24: "STL", 25: "SD",
        26: "SF",  27: "COL", 28: "MIA", 29: "ARI", 30: "TB",
        31: "FA",  32: "FA",
    }


def get_league_data(team_id: int, week: int) -> dict:
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year = os.environ.get("ESPN_SEASON", "2026")
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP = get_pro_team_map(headers, cookies)
    base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}/segments/0/leagues/{league_id}"

# ── Fetch probable pitchers from MLB Stats API ──────────────────────────
    MATCHUP_PERIODS = {
        1:  ("2026-03-25", "2026-04-05",  21),
        2:  ("2026-04-06", "2026-04-12",  12),
        3:  ("2026-04-13", "2026-04-19",  12),
        4:  ("2026-04-20", "2026-04-26",  12),
        5:  ("2026-04-27", "2026-05-03",  12),
        6:  ("2026-05-04", "2026-05-10",  12),
        7:  ("2026-05-11", "2026-05-17",  12),
        8:  ("2026-05-18", "2026-05-24",  12),
        9:  ("2026-05-25", "2026-05-31",  12),
        10: ("2026-06-01", "2026-06-07",  12),
        11: ("2026-06-08", "2026-06-14",  12),
        12: ("2026-06-15", "2026-06-21",  12),
        13: ("2026-06-22", "2026-06-28",  12),
        14: ("2026-06-29", "2026-07-05",  12),
        15: ("2026-07-06", "2026-07-19",  19),
        16: ("2026-07-20", "2026-07-26",  12),
        17: ("2026-07-27", "2026-08-02",  12),
        18: ("2026-08-03", "2026-08-09",  12),
        19: ("2026-08-10", "2026-08-16",  12),
        20: ("2026-08-17", "2026-08-23",  12),
        21: ("2026-08-24", "2026-08-30",  12),
        22: ("2026-08-31", "2026-09-06",  12),
    }

    probable_pitchers = {}
    week_start = ""
    week_end = ""
    matchup_limit = int(os.environ.get("ESPN_STARTS_LIMIT", "12"))

    if week in MATCHUP_PERIODS:
        mlb_start, mlb_end, matchup_limit = MATCHUP_PERIODS[week]

        def fmt_date(d):
            from datetime import datetime
            return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")

        week_start = fmt_date(mlb_start)
        week_end = fmt_date(mlb_end)

        try:
            mlb_r = requests.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={
                    "sportId": 1,
                    "startDate": mlb_start,
                    "endDate": mlb_end,
                    "hydrate": "probablePitcher",
                    "gameType": "R",
                },
                timeout=15
            )
            if mlb_r.status_code == 200:
                mlb_data = mlb_r.json()
                for date_obj in mlb_data.get("dates", []):
                    date_str = date_obj.get("date", "")
                    display_date = fmt_date(date_str) if date_str else ""
                    for game in date_obj.get("games", []):
                        for side in ("away", "home"):
                            team_data = game.get("teams", {}).get(side, {})
                            pitcher = team_data.get("probablePitcher", {})
                            name = pitcher.get("fullName", "")
                            if name:
                                if name not in probable_pitchers:
                                    probable_pitchers[name] = []
                                probable_pitchers[name].append(display_date)
        except Exception:
            pass  # If MLB API fails, fall back to ESPN data

    # Fetch roster, team info, settings, and per-period stats in one call
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
        raise Exception(f"ESPN returned an HTTP {r.status_code}")

    data = r.json()
    teams = data.get("teams", [])
    my_team = next((t for t in teams if t.get("id") == team_id), teams[0] if teams else {})
    team_name = my_team.get("name", "").strip()
    current_week = data.get("scoringPeriodId", week)

    # Fetch per-player projected stats for this scoring period separately
    # using kona_player_info which returns richer stat data
    xff_roster = json.dumps({
        "players": {
            "filterIds": {"value": [
                e.get("playerId") for e in my_team.get("roster", {}).get("entries", [])
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
    # Build lookup of playerId -> projected starts this week
    starts_by_player = {}
    proj_fpts_by_player = {}
    if stats_r.status_code == 200:
        stats_data = stats_r.json()
        for p in stats_data.get("players", []):
            pid = p.get("id")
            player_obj = p.get("playerPoolEntry", {}).get("player", {})
            for stat_entry in player_obj.get("stats", []):
                src = stat_entry.get("statSourceId")
                period = stat_entry.get("scoringPeriodId")
                split = stat_entry.get("statSplitTypeId")
                if src == 1 and period == current_week:
                    stats = stat_entry.get("stats", {})
                    # Stat 36 = GS, stat 48 = projected points in some schemas
                    gs = float(stats.get("36", stats.get(36, 0)) or 0)
                    if gs > 0:
                        starts_by_player[pid] = int(round(gs))
                    # Total projected points for the period
                    proj = p.get("playerPoolEntry", {}).get("appliedStatTotal", 0)
                    proj_fpts_by_player[pid] = round(float(proj or 0), 1)

    # Parse roster
    roster_entries = my_team.get("roster", {}).get("entries", [])
    roster_sps = []
    SP_ELIGIBLE = {14}
    RP_ELIGIBLE = {13}
    IL_SLOTS = {16, 17}

    for entry in roster_entries:
        pool_entry = entry.get("playerPoolEntry", {})
        player = pool_entry.get("player", {})
        print(f"[DEBUG] {player.get('fullName')} lineup_slot={entry.get('lineupSlotId')} inj={pool_entry.get('injuryStatus')} eligible={set(player.get('eligibleSlots', []))}")
        eligible_slots = set(player.get("eligibleSlots", []))
        player_id = entry.get("playerId")

        # Include SP-eligible and RP-eligible pitchers
        if not (eligible_slots & SP_ELIGIBLE) and not (eligible_slots & RP_ELIGIBLE):
            continue

        lineup_slot = entry.get("lineupSlotId", 0)
        inj_status = pool_entry.get("injuryStatus", "")
        slot_label = get_slot_label(lineup_slot, eligible_slots)
        status_label = get_status(lineup_slot, inj_status)
        pro_team_id = player.get("proTeamId", 0)
        team_abbrev = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))

        player_name = player.get("fullName", "Unknown")
        print(f"[DEBUG] {player_name} | lineupSlot={lineup_slot} | inj={inj_status} | eligible={eligible_slots}")

        if lineup_slot in IL_SLOTS:
            scheduled_starts = 0
            proj_fpts = 0.0
        else:
            # Use MLB Stats API probable pitcher data if available
            if player_name in probable_pitchers:
                scheduled_starts = len(probable_pitchers[player_name])
            else:
                scheduled_starts = starts_by_player.get(player_id, 0)
                # Fallback for SP-eligible only (not RPs)
                if scheduled_starts == 0 and 14 in eligible_slots:
                    scheduled_starts = 1  # Conservative fallback — not yet announced
            proj_fpts = proj_fpts_by_player.get(player_id, round(float(pool_entry.get("appliedStatTotal", 0)), 1))

        roster_sps.append({
            "name": player.get("fullName", "Unknown"),
            "team": team_abbrev,
            "slot": slot_label,
            "injuryStatus": status_label,
            "starts": scheduled_starts,
            "projFpts": proj_fpts,
            "percentOwned": round(pool_entry.get("percentOwned", 100), 1),
            "lineupSlotRaw": lineup_slot,   # temporary debug field
        })

    # Sort: SP first, then RP, then IL; then starts desc, then fpts desc
    slot_order = {"SP": 0, "RP": 1, "IL": 2, "P": 1}
    roster_sps.sort(key=lambda x: (slot_order.get(x["slot"], 1), -x["starts"], -x["projFpts"]))

    # Fetch free agents
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
        fa_data = fa_r.json()
        for p in fa_data.get("players", []):
            entry = p
            player = p.get("player", {})
            if not player.get("fullName"):
                continue
            eligible_slots = set(player.get("eligibleSlots", []))

            # Only include SP-eligible pitchers for free agent analysis
            if 14 not in eligible_slots:
                continue

            pro_team_id = player.get("proTeamId", 0)
            team_abbrev = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
            pid = p.get("id")
            fa_name = player.get("fullName", "")
            if fa_name in probable_pitchers:
                starts = len(probable_pitchers[fa_name])
            else:
                starts = 1 if 14 in eligible_slots else 0
            free_agents.append({
                "name": player.get("fullName", "Unknown"),
                "team": team_abbrev,
                "injuryStatus": {
                    "ACTIVE": "Active",
                    "NORMAL": "Active",
                    "FIFTEEN_DAY_DL": "IL15",
                    "SIXTY_DAY_DL": "IL60",
                    "DAY_TO_DAY": "DTD",
                    "SUSPENSION": "SUSP",
                }.get(player.get("injuryStatus", "ACTIVE"), player.get("injuryStatus", "Active")),
                "percentOwned": round(player.get("ownership", {}).get("percentOwned", 0), 1),
                "projFpts": 0.0,
                "starts": starts,
                "opps": "",
                "checked": entry.get("percentOwned", 0) >= 15,
            })

    return {
        "ok": True,
        "teamName": team_name,
        "currentWeek": current_week,
        "weekStart": week_start,
        "weekEnd": week_end,
        "rosterSPs": roster_sps,
        "freeAgentSPs": free_agents,
    }

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        env_team_id = os.environ.get("ESPN_TEAM_ID", "")
        team_id = int(env_team_id) if env_team_id else int(qs.get("teamId", ["1"])[0])
        week = int(qs.get("week", ["1"])[0])

        try:
            payload = get_league_data(team_id, week)
            payload["teamId"] = team_id
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
