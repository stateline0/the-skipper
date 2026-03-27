"""
/api/mlb.py — Vercel Python serverless function
Fetches probable pitchers from MLB Stats API for a given matchup period.
Public API, no auth required.
"""
import json
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 2026 matchup period date ranges
# Format: (start_date, end_date, starts_limit)
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


def get_probable_pitchers(matchup_period: int) -> dict:
    """
    Fetch probable pitchers from MLB Stats API for a given matchup period.
    Returns a dict with pitcher names as keys and list of start dates as values.
    Also returns week start/end dates and starts limit.
    """
    if matchup_period not in MATCHUP_PERIODS:
        raise Exception(f"Unknown matchup period: {matchup_period}")

    start_date, end_date, starts_limit = MATCHUP_PERIODS[matchup_period]

    # Format dates for display (e.g. "Mar 25")
    from datetime import datetime
    def fmt_date(d):
        return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")

    week_start = fmt_date(start_date)
    week_end = fmt_date(end_date)

    # Fetch schedule with probable pitchers from MLB Stats API
    url = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "startDate": start_date,
        "endDate": end_date,
        "hydrate": "probablePitcher",
        "gameType": "R",  # Regular season only
    }

    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise Exception(f"MLB API returned {r.status_code}")

    data = r.json()

    # Build a map of pitcher name -> list of dates they're starting
    # e.g. {"Garrett Crochet": ["Mar 26", "Apr 1"], ...}
    pitcher_starts = {}

    for date_obj in data.get("dates", []):
        date_str = date_obj.get("date", "")
        display_date = fmt_date(date_str) if date_str else ""

        for game in date_obj.get("games", []):
            for side in ("away", "home"):
                team = game.get("teams", {}).get(side, {})
                pitcher = team.get("probablePitcher", {})
                name = pitcher.get("fullName", "")
                if name:
                    if name not in pitcher_starts:
                        pitcher_starts[name] = []
                    pitcher_starts[name].append(display_date)

    return {
        "ok": True,
        "matchupPeriod": matchup_period,
        "weekStart": week_start,
        "weekEnd": week_end,
        "startsLimit": starts_limit,
        "probablePitchers": pitcher_starts,
        "totalPitchers": len(pitcher_starts),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        matchup_period = int(qs.get("period", ["1"])[0])

        try:
            payload = get_probable_pitchers(matchup_period)
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