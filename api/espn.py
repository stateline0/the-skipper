"""
/api/espn.py  — Vercel Python serverless function
Fetches roster + free agents from ESPN Fantasy Baseball API.
Counts probable starts (PP) per pitcher using ESPN's per-day projected stats.
"""
import json
import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


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


def count_projected_starts(player_stats: list, scoring_period: int) -> int:
    """
    Count probable starts for a pitcher this scoring period.

    ESPN stat entries have:
    - statSourceId: 0=actual, 1=projection
    - statSplitTypeId: 0=season, 1=scoring period (week)
    - scoringPeriodId: the period number

    ESPN baseball stat ID 36 = Games Started (GS).
    We find the projected weekly stat entry for this scoring period
    and read the GS value directly.
    """
    for stat_entry in player_stats:
        stat_source = stat_entry.get("statSourceId", -1)
        period = stat_entry.get("scoringPeriodId", -1)

        # Projected (1) stats for this specific scoring period
        if stat_source == 1 and period == scoring_period:
            stats = stat_entry.get("stats", {})
            # Stat 36 = Games Started in ESPN baseball
            gs = stats.get("36", stats.get(36, 0))
            if gs:
                return int(round(float(gs)))

    return 0


def get_league_data(team_id: int, week: int) -> dict:
    """Fetch league data directly via requests."""
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year = os.environ.get("ESPN_SEASON", "2026")
    headers, cookies = get_headers_and_cookies()

    base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}/segments/0/leagues/{league_id}"

    # Fetch roster with player stats for current scoring period
    r = requests.get(
        base,
        params={
            "view": ["mRoster", "mTeam"],
            "scoringPeriodId": week,
        },
        cookies=cookies,
        headers=headers,
        timeout=15
    )
    if r.status_code != 200:
        raise Exception(f"ESPN returned an HTTP {r.status_code}")

    data = r.json()
    teams = data.get("teams", [])
    my_team = next((t for t in teams if t.get("id") == team_id), teams[0] if teams else {})
    team_name = my_team.get("location", "") + " " + my_team.get("nickname", "")
    current_week = data.get("scoringPeriodId", week)

    # Parse roster entries
    roster_entries = my_team.get("roster", {}).get("entries", [])
    roster_sps = []
    SP_SLOT_IDS = {14, 15}
    IL_SLOT_IDS = {16, 17}

    for entry in roster_entries:
        pool_entry = entry.get("playerPoolEntry", {})
        player = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))

        if not (eligible_slots & SP_SLOT_IDS):
            continue

        lineup_slot = entry.get("lineupSlotId", 0)
        inj_status = pool_entry.get("injuryStatus", "")

        if lineup_slot in IL_SLOT_IDS or inj_status in ("IL", "IL10", "IL15", "IL60", "SUSP"):
            scheduled_starts = 0
        else:
            player_stats = player.get("stats", [])
            scheduled_starts = count_projected_starts(player_stats, current_week)
            # Fallback for confirmed SPs with no projection data yet
            if scheduled_starts == 0 and 14 in eligible_slots:
                scheduled_starts = 2

        roster_sps.append({
            "name": player.get("fullName", "Unknown"),
            "team": player.get("proTeamId", "?"),
            "slot": "SP" if lineup_slot == 14 else ("IL" if lineup_slot in IL_SLOT_IDS else "P"),
            "injuryStatus": inj_status,
            "starts": scheduled_starts,
            "projFpts": round(pool_entry.get("appliedStatTotal", 0), 1),
            "percentOwned": round(pool_entry.get("percentOwned", 100), 1),
        })

    # Fetch free agents with projected stats
    xff = json.dumps({
        "players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "filterSlotIds": {"value": [14, 15]},
            "limit": 30,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "filterStatsForTopScoringPeriodIDs": {
                "value": 1,
                "additionalValue": [f"11{current_week}", f"00{year}"]
            }
        }
    })
    fa_r = requests.get(
        base,
        params={"view": "kona_player_info", "scoringPeriodId": current_week},
        cookies=cookies,
        headers={**headers, "x-fantasy-filter": xff},
        timeout=15
    )
    free_agents = []
    if fa_r.status_code == 200:
        fa_data = fa_r.json()
        for p in fa_data.get("players", []):
            entry = p.get("playerPoolEntry", {})
            player = entry.get("player", {})
            eligible_slots = set(player.get("eligibleSlots", []))
            player_stats = player.get("stats", [])
            starts = count_projected_starts(player_stats, current_week)
            if starts == 0 and 14 in eligible_slots:
                starts = 2
            free_agents.append({
                "name": player.get("fullName", "Unknown"),
                "team": str(player.get("proTeamId", "?")),
                "injuryStatus": entry.get("injuryStatus", ""),
                "percentOwned": round(entry.get("percentOwned", 0), 1),
                "projFpts": round(entry.get("appliedStatTotal", 0), 1),
                "starts": starts,
                "opps": "",
                "checked": entry.get("percentOwned", 0) >= 15,
            })

    return {
        "ok": True,
        "teamName": team_name.strip(),
        "currentWeek": current_week,
        "rosterSPs": roster_sps,
        "freeAgentSPs": sorted(free_agents, key=lambda x: x["percentOwned"], reverse=True),
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
