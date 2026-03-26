"""
/api/espn.py  — Vercel Python serverless function
Fetches roster + free agents from ESPN Fantasy Baseball API.
Credentials come from Vercel env vars (set once, never in the browser).
"""
import json
import os
from http.server import BaseHTTPRequestHandler

from espn_api.baseball import League


def get_league() -> League:
    league_id = int(os.environ["ESPN_LEAGUE_ID"])
    year = int(os.environ.get("ESPN_SEASON", "2026"))
    espn_s2 = os.environ.get("ESPN_S2", "")
    swid = os.environ.get("ESPN_SWID", "")

    if espn_s2 and swid:
        return League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    return League(league_id=league_id, year=year)


def get_my_team(league: League, team_id: int):
    for team in league.teams:
        if team.team_id == team_id:
            return team
    return league.teams[0]  # fallback


def extract_sp_roster(team) -> list[dict]:
    """Return SP/P-eligible players from the roster with starts projection."""
    pitchers = []
    for player in team.roster:
        eligible = [s.lower() for s in (player.eligibleSlots or [])]
        if "sp" not in eligible and "p" not in eligible:
            continue
        # skip closers/relievers who aren't SP-eligible
        if player.lineupSlot in ("RP",):
            continue
        pitchers.append({
            "name": player.name,
            "team": player.proTeam,
            "slot": player.lineupSlot,
            "injuryStatus": player.injuryStatus or "",
            "projectedStartsThisWeek": getattr(player, "projected_total_points", 0),
            "percentOwned": round(getattr(player, "percent_owned", 100), 1),
        })
    return pitchers


def extract_free_agents(league: League, week: int) -> list[dict]:
    """Top 30 SP free agents by ownership %."""
    fas = league.free_agents(week=week, size=30, position="SP")
    result = []
    for p in fas:
        result.append({
            "name": p.name,
            "team": p.proTeam,
            "injuryStatus": p.injuryStatus or "",
            "percentOwned": round(getattr(p, "percent_owned", 0), 1),
            "projPoints": round(getattr(p, "projected_total_points", 0), 1),
        })
    return sorted(result, key=lambda x: x["percentOwned"], reverse=True)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        team_id = int(qs.get("teamId", ["1"])[0])
        week = int(qs.get("week", ["1"])[0])

        try:
            league = get_league()
            team = get_my_team(league, team_id)
            roster = extract_sp_roster(team)
            free_agents = extract_free_agents(league, week)

            payload = {
                "ok": True,
                "teamName": team.team_name,
                "currentWeek": league.current_week,
                "rosterSPs": roster,
                "freeAgentSPs": free_agents,
            }
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
