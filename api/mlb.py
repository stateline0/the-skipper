"""
/api/mlb.py — Vercel Python serverless function

Returns probable pitchers for a given ESPN matchup period.
Merges two sources:
  1. MLB Stats API — official confirmed probables (1-2 days out)
  2. FantasyPros probables grid — projected starters (up to 12 days out)

MLB Stats API takes priority. FantasyPros fills in the gaps.
Each start carries a `confirmed` boolean so the frontend can show
a checkmark (confirmed) or clock (projected) indicator.
"""

import json
import re
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError
from datetime import datetime, timedelta
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Matchup period table
# All 22 ESPN regular-season matchup periods. Hardcoded because ESPN doesn't
# expose this cleanly via API. fp_daterange is the ?daterange= param for
# FantasyPros — it matches the matchup period number directly.
# ---------------------------------------------------------------------------
MATCHUP_PERIODS = {
    1:  {"start": "2026-03-25", "end": "2026-04-05", "limit": 21},
    2:  {"start": "2026-04-06", "end": "2026-04-12", "limit": 12},
    3:  {"start": "2026-04-13", "end": "2026-04-19", "limit": 12},
    4:  {"start": "2026-04-20", "end": "2026-04-26", "limit": 12},
    5:  {"start": "2026-04-27", "end": "2026-05-03", "limit": 12},
    6:  {"start": "2026-05-04", "end": "2026-05-10", "limit": 12},
    7:  {"start": "2026-05-11", "end": "2026-05-17", "limit": 12},
    8:  {"start": "2026-05-18", "end": "2026-05-24", "limit": 12},
    9:  {"start": "2026-05-25", "end": "2026-05-31", "limit": 12},
    10: {"start": "2026-06-01", "end": "2026-06-07", "limit": 12},
    11: {"start": "2026-06-08", "end": "2026-06-14", "limit": 12},
    12: {"start": "2026-06-15", "end": "2026-06-21", "limit": 12},
    13: {"start": "2026-06-22", "end": "2026-06-28", "limit": 12},
    14: {"start": "2026-06-29", "end": "2026-07-05", "limit": 12},
    15: {"start": "2026-07-06", "end": "2026-07-19", "limit": 19},
    16: {"start": "2026-07-20", "end": "2026-07-26", "limit": 12},
    17: {"start": "2026-07-27", "end": "2026-08-02", "limit": 12},
    18: {"start": "2026-08-03", "end": "2026-08-09", "limit": 12},
    19: {"start": "2026-08-10", "end": "2026-08-16", "limit": 12},
    20: {"start": "2026-08-17", "end": "2026-08-23", "limit": 12},
    21: {"start": "2026-08-24", "end": "2026-08-30", "limit": 12},
    22: {"start": "2026-08-31", "end": "2026-09-06", "limit": 12},
}

# ---------------------------------------------------------------------------
# ESPN Scoreboard API
#
# ESPN's public scoreboard API returns probable starters per game per day,
# up to ~7 days out. No auth required. One request per day in the period.
#
# Endpoint: site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard
# Param: dates=YYYYMMDD
#
# Returns { "crochet": ["2026-03-27", "2026-04-01"], ... }
# Keys are lowercased last names for matching against ESPN fantasy names.
# ---------------------------------------------------------------------------

def fetch_espn_probables(period_start, period_end):
    """
    Fetch probable pitchers from ESPN scoreboard API for each day in the range.
    Returns { "crochet": ["2026-03-27", ...], ... }
    """
    start_dt = datetime.strptime(period_start, "%Y-%m-%d")
    end_dt = datetime.strptime(period_end, "%Y-%m-%d")

    result = {}
    current = start_dt

    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")       # ESPN wants YYYYMMDD format
        iso_date = current.strftime("%Y-%m-%d")     # We store dates as YYYY-MM-DD

        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
            f"?dates={date_str}&limit=50"
        )
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = r.json()

            for event in data.get("events", []):
                for competitor in event.get("competitions", [{}])[0].get("competitors", []):
                    for probable in competitor.get("probables", []):
                        if probable.get("name") != "probableStartingPitcher":
                            continue
                        athlete = probable.get("athlete", {})
                        full_name = athlete.get("fullName", "")
                        if full_name:
                            last_name = full_name.split()[-1].lower()
                            if last_name in ("jr.", "sr.", "ii", "iii", "iv"):
                                parts = full_name.split()
                                last_name = parts[-2].lower() if len(parts) >= 2 else last_name
                            result.setdefault(last_name, [])
                            if iso_date not in result[last_name]:
                                result[last_name].append(iso_date)
        except Exception as e:
            print(f"[mlb.py] ESPN scoreboard fetch failed for {date_str}: {e}")

        current += timedelta(days=1)

    print(f"[mlb.py] ESPN scoreboard: {len(result)} pitchers across {(end_dt - start_dt).days + 1} days")
    return result


# ---------------------------------------------------------------------------
# MLB Stats API
# Official source — only populates 1-2 days out, but those are confirmed.
# Returns { "severino": ["2026-03-27"], ... }
# ---------------------------------------------------------------------------

def fetch_mlb_probables(start_date, end_date):
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={
                "sportId": 1,
                "startDate": start_date,
                "endDate": end_date,
                "hydrate": "probablePitcher",
                "gameType": "R",
            },
            timeout=15
        )
        data = r.json()
    except Exception as e:
        print(f"[mlb.py] MLB Stats API fetch failed: {e}")
        return {}

    result = {}
    for date_entry in data.get("dates", []):
        game_date = date_entry.get("date", "")
        for game in date_entry.get("games", []):
            for side in ("away", "home"):
                pitcher = game.get("teams", {}).get(side, {}).get("probablePitcher")
                if pitcher:
                    full_name = pitcher.get("fullName", "")
                    if full_name:
                        last_name = full_name.split()[-1].lower()
                        if full_name:
                        print(f"[mlb.py] MLB pitcher: {full_name}")
                        if last_name in ("jr.", "sr.", "ii", "iii", "iv"):
                            parts = full_name.split()
                            last_name = parts[-2].lower() if len(parts) >= 2 else last_name
                        result.setdefault(last_name, [])
                        if game_date not in result[last_name]:
                            result[last_name].append(game_date)
    return result


# ---------------------------------------------------------------------------
# Merge both sources into a unified pitcher starts dict.
#
# Output per pitcher last name:
# {
#   "starts": 2,
#   "startDates": [
#     {"date": "2026-03-27", "confirmed": True},
#     {"date": "2026-04-01", "confirmed": False},
#   ]
# }
# confirmed=True  → MLB Stats API (official)
# confirmed=False → FantasyPros projection only
# ---------------------------------------------------------------------------

def build_pitcher_starts(mlb_data, fp_data, period_start, period_end):
    start_dt = datetime.strptime(period_start, "%Y-%m-%d")
    end_dt = datetime.strptime(period_end, "%Y-%m-%d")

    all_names = set(mlb_data.keys()) | set(fp_data.keys())
    result = {}

    for name in all_names:
        mlb_dates = set(mlb_data.get(name, []))
        fp_dates = set(fp_data.get(name, []))
        all_dates = mlb_dates | fp_dates

        # Only include dates within this matchup period
        period_dates = [
            d for d in sorted(all_dates)
            if start_dt <= datetime.strptime(d, "%Y-%m-%d") <= end_dt
        ]

        if not period_dates:
            continue

        start_list = [
            {"date": d, "confirmed": d in mlb_dates}
            for d in period_dates
        ]

        result[name] = {
            "starts": len(start_list),
            "startDates": start_list,
        }

    return result


# ---------------------------------------------------------------------------
# Public helper — called by espn.py to look up starts for a list of players.
#
# Given a matchup period and a list of full player names ("Luis Severino"),
# returns { "Luis Severino": { "starts": 2, "startDates": [...] }, ... }
# Matching is by last name (lowercase). First match wins on collision.
# ---------------------------------------------------------------------------

def get_starts_for_players(player_names, matchup_period):
    if matchup_period not in MATCHUP_PERIODS:
        return {}

    mp = MATCHUP_PERIODS[matchup_period]
    mlb_data = fetch_mlb_probables(mp["start"], mp["end"])
    fp_data = fetch_espn_probables(mp["start"], mp["end"])
    pitcher_starts = build_pitcher_starts(mlb_data, fp_data, mp["start"], mp["end"])

    result = {}
    for full_name in player_names:
        last_name = full_name.split()[-1].lower()
        if last_name in pitcher_starts:
            result[full_name] = pitcher_starts[last_name]
        else:
            result[full_name] = {"starts": 0, "startDates": []}
    return result


# ---------------------------------------------------------------------------
# HTTP handler — /api/mlb?period=N
# Useful for testing the data independently of espn.py
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        period = int(qs.get("period", ["1"])[0])

        if period not in MATCHUP_PERIODS:
            self._respond(400, {"ok": False, "error": f"Invalid period: {period}"})
            return

        mp = MATCHUP_PERIODS[period]
        mlb_data = fetch_mlb_probables(mp["start"], mp["end"])
        fp_data = fetch_espn_probables(mp["start"], mp["end"])
        pitcher_starts = build_pitcher_starts(mlb_data, fp_data, mp["start"], mp["end"])

        start_dt = datetime.strptime(mp["start"], "%Y-%m-%d")
        end_dt = datetime.strptime(mp["end"], "%Y-%m-%d")

        self._respond(200, {
            "ok": True,
            "matchupPeriod": period,
            "weekStart": start_dt.strftime("%b %-d"),
            "weekEnd": end_dt.strftime("%b %-d"),
            "startsLimit": mp["limit"],
            "probablePitchers": pitcher_starts,
            "totalPitchers": len(pitcher_starts),
            "sources": {
                "mlbConfirmedPitchers": len(mlb_data),
                "fpProjectedPitchers": len(fp_data),
            },
        })

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()