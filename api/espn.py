"""
/api/espn.py  — Vercel Python serverless function
Fetches roster + free agents from ESPN Fantasy Baseball API.
Credentials come from Vercel env vars (set once, never in the browser).
"""
import json
import os
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def get_league_data(team_id: int, week: int) -> dict:
    """Fetch league data directly via requests, bypassing espn_api package issues."""
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year = os.environ.get("ESPN_SEASON", "2026")
    espn_s2 = os.environ.get("ESPN_S2", "").strip()
    swid = os.environ.get("ESPN_SWID", "").strip()

    base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}/segments/0/leagues/{league_id}"
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid

    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    # Fetch roster for our team
    r = requests.get(
        base,
        params={"view": ["mRoster", "mTeam", "mSettings"], "forTeamId": team_id},
        cookies=cookies,
        headers=headers,
        timeout=15
    )
    if r.status_code != 200:
        raise Exception(f"ESPN returned an HTTP {r.status_code}")

    data = r.json()

    # Get team name
    teams = data.get("teams", [])
    my_team = next((t for t in teams if t.get("id") == team_id), teams[0] if teams else {})
    team_name = my_team.get("location", "") + " " + my_team.get("nickname", "")
    current_week = data.get("scoringPeriodId", week)

    # Parse roster entries
    roster_entries = my_team.get("roster", {}).get("entries", [])
    roster_sps = []
    SP_SLOT_IDS = {14, 15}  # 14=SP, 15=P in ESPN baseball
    for entry in roster_entries:
        player = entry.get("playerPoolEntry", {}).get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        if not (eligible_slots & SP_SLOT_IDS):
            continue
        lineup_slot = entry.get("lineupSlotId", 0)
        roster_sps.append({
            "name": player.get("fullName", "Unknown"),
            "team": player.get("proTeamId", "?"),
            "slot": "SP" if lineup_slot == 14 else "P",
            "injuryStatus": entry.get("playerPoolEntry", {}).get("injuryStatus", ""),
            "starts": 2,
            "projFpts": round(entry.get("playerPoolEntry", {}).get("appliedStatTotal", 0), 1),
            "percentOwned": round(entry.get("playerPoolEntry", {}).get("percentOwned", 100), 1),
        })

    # Fetch free agents
    xff = json.dumps({
        "players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "filterSlotIds": {"value": [14, 15]},
            "limit": 30,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False}
        }
    })
    fa_r = requests.get(
        base,
        params={"view": "kona_player_info"},
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
            free_agents.append({
                "name": player.get("fullName", "Unknown"),
                "team": str(player.get("proTeamId", "?")),
                "injuryStatus": entry.get("injuryStatus", ""),
                "percentOwned": round(entry.get("percentOwned", 0), 1),
                "projFpts": round(entry.get("appliedStatTotal", 0), 1),
                "starts": 2,
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

        # Team ID: prefer env var, fall back to query param
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
