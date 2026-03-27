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

# ESPN pro team ID to abbreviation mapping
PRO_TEAM_MAP = {
    1: "ATL", 2: "BOS", 3: "CHC", 4: "CIN", 5: "CLE",
    6: "COL", 7: "DET", 8: "HOU", 9: "KC", 10: "LAA",
    11: "LAD", 12: "MIA", 13: "MIL", 14: "MIN", 15: "NYM",
    16: "NYY", 17: "OAK", 18: "PHI", 19: "PIT", 20: "SD",
    21: "SEA", 22: "SF", 23: "STL", 24: "TB", 25: "TEX",
    26: "TOR", 27: "WSH", 28: "ARI", 29: "ATH", 30: "BAL",
    31: "CWS", 32: "FA"
}


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


def get_league_data(team_id: int, week: int) -> dict:
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year = os.environ.get("ESPN_SEASON", "2026")
    headers, cookies = get_headers_and_cookies()
    base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}/segments/0/leagues/{league_id}"

    # Fetch roster, team info, settings, and per-period stats in one call
    r = requests.get(
        base,
        params=[
            ("view", "mRoster"),
            ("view", "mTeam"),
            ("view", "mSettings"),
            ("view", "mMatchupScore"),
            ("scoringPeriodId", week),
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

    # Get matchup period dates
    schedule_settings = data.get("settings", {}).get("scheduleSettings", {})
    matchup_dates = schedule_settings.get("matchupPeriodDates", {})
    period_dates = matchup_dates.get(str(current_week), [])
    week_start = ""
    week_end = ""
    if len(period_dates) >= 2:
        def fmt_ts(ts):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%b %-d")
        week_start = fmt_ts(period_dates[0])
        week_end = fmt_ts(period_dates[-1])

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

        if lineup_slot in IL_SLOTS or inj_status in ("IL", "IL10", "IL15", "IL60", "SUSP"):
            scheduled_starts = 0
            proj_fpts = 0.0
        else:
            scheduled_starts = starts_by_player.get(player_id, 0)
            proj_fpts = proj_fpts_by_player.get(player_id, round(float(pool_entry.get("appliedStatTotal", 0)), 1))
            # Fallback for SP-eligible only (not RPs)
            if scheduled_starts == 0 and 14 in eligible_slots:
                scheduled_starts = 2

        roster_sps.append({
            "name": player.get("fullName", "Unknown"),
            "team": team_abbrev,
            "slot": slot_label,
            "injuryStatus": status_label,
            "starts": scheduled_starts,
            "projFpts": proj_fpts,
            "percentOwned": round(pool_entry.get("percentOwned", 100), 1),
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
