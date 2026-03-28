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
from datetime import datetime
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Matchup period table
# All 22 ESPN regular-season matchup periods. Hardcoded because ESPN doesn't
# expose this cleanly via API. fp_daterange is the ?daterange= param for
# FantasyPros — it matches the matchup period number directly.
# ---------------------------------------------------------------------------
MATCHUP_PERIODS = {
    1:  {"start": "2026-03-25", "end": "2026-04-05", "limit": 21, "fp_daterange": 1},
    2:  {"start": "2026-04-06", "end": "2026-04-12", "limit": 12, "fp_daterange": 2},
    3:  {"start": "2026-04-13", "end": "2026-04-19", "limit": 12, "fp_daterange": 3},
    4:  {"start": "2026-04-20", "end": "2026-04-26", "limit": 12, "fp_daterange": 4},
    5:  {"start": "2026-04-27", "end": "2026-05-03", "limit": 12, "fp_daterange": 5},
    6:  {"start": "2026-05-04", "end": "2026-05-10", "limit": 12, "fp_daterange": 6},
    7:  {"start": "2026-05-11", "end": "2026-05-17", "limit": 12, "fp_daterange": 7},
    8:  {"start": "2026-05-18", "end": "2026-05-24", "limit": 12, "fp_daterange": 8},
    9:  {"start": "2026-05-25", "end": "2026-05-31", "limit": 12, "fp_daterange": 9},
    10: {"start": "2026-06-01", "end": "2026-06-07", "limit": 12, "fp_daterange": 10},
    11: {"start": "2026-06-08", "end": "2026-06-14", "limit": 12, "fp_daterange": 11},
    12: {"start": "2026-06-15", "end": "2026-06-21", "limit": 12, "fp_daterange": 12},
    13: {"start": "2026-06-22", "end": "2026-06-28", "limit": 12, "fp_daterange": 13},
    14: {"start": "2026-06-29", "end": "2026-07-05", "limit": 12, "fp_daterange": 14},
    15: {"start": "2026-07-06", "end": "2026-07-19", "limit": 19, "fp_daterange": 15},
    16: {"start": "2026-07-20", "end": "2026-07-26", "limit": 12, "fp_daterange": 16},
    17: {"start": "2026-07-27", "end": "2026-08-02", "limit": 12, "fp_daterange": 17},
    18: {"start": "2026-08-03", "end": "2026-08-09", "limit": 12, "fp_daterange": 18},
    19: {"start": "2026-08-10", "end": "2026-08-16", "limit": 12, "fp_daterange": 19},
    20: {"start": "2026-08-17", "end": "2026-08-23", "limit": 12, "fp_daterange": 20},
    21: {"start": "2026-08-24", "end": "2026-08-30", "limit": 12, "fp_daterange": 21},
    22: {"start": "2026-08-31", "end": "2026-09-06", "limit": 12, "fp_daterange": 22},
}

# ---------------------------------------------------------------------------
# FantasyPros HTML parser
#
# FantasyPros renders a table where each row = one MLB team, each column =
# one game date, and each cell contains the projected starter (e.g. "L. Severino").
# We use Python's built-in HTMLParser — no extra dependencies needed.
#
# Output: { "severino": ["2026-03-27", "2026-04-01"], "gallen": [...], ... }
# Keys are lowercased last names for matching against ESPN full names.
# ---------------------------------------------------------------------------

class ProbablesTableParser(HTMLParser):
    def __init__(self, col_dates):
        super().__init__()
        self.col_dates = col_dates
        self.in_table = False
        self.in_tbody = False
        self.in_td = False
        self.in_link = False
        self.current_row_cells = []
        self.current_cell_text = ""
        self.current_link_text = ""
        self.result = {}

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
        if not self.in_table:
            return
        if tag == "tbody":
            self.in_tbody = True
        if tag == "tr":
            self.current_row_cells = []
        if tag in ("td", "th"):
            self.in_td = True
            self.current_cell_text = ""
        if tag == "a":
            self.in_link = True
            self.current_link_text = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
            self.in_tbody = False
        if tag == "tbody":
            self.in_tbody = False
        if tag == "a":
            self.in_link = False
            if self.in_td and self.current_link_text.strip():
                self.current_cell_text = self.current_link_text.strip()
        if tag in ("td", "th"):
            self.in_td = False
            self.current_row_cells.append(self.current_cell_text.strip())
        if tag == "tr" and self.in_tbody:
            # Row complete. cells[0] = team name, cells[1:] = one per game day
            cells = self.current_row_cells
            if len(cells) > 1:
                for i, cell in enumerate(cells[1:]):
                    if cell and i < len(self.col_dates):
                        # Cell text is like "L. Severino" — grab the last name
                        parts = cell.split()
                        if len(parts) >= 2:
                            last_name = parts[-1].lower()
                            # Skip suffix-only keys like "jr." or "sr."
                            if last_name in ("jr.", "sr.", "ii", "iii"):
                                last_name = parts[-2].lower()
                            date = self.col_dates[i]
                            self.result.setdefault(last_name, [])
                            if date not in self.result[last_name]:
                                self.result[last_name].append(date)

    def handle_data(self, data):
        if self.in_link:
            self.current_link_text += data
        elif self.in_td:
            self.current_cell_text += data


def parse_fp_date_headers(html_text):
    """
    Pull the column date headers out of the FantasyPros HTML.
    They look like: <th ...>Thu Mar 26</th>
    Returns a list of YYYY-MM-DD strings, one per data column.
    """
    pattern = r'<th[^>]*>\s*(?:\w{3}\s+)?(\w{3}\s+\d{1,2})\s*</th>'
    matches = re.findall(pattern, html_text)
    dates = []
    now = datetime.now()
    for m in matches:
        try:
            dt = datetime.strptime(f"{m} {now.year}", "%b %d %Y")
            # Handle year rollover (e.g. Dec projections viewed in Nov)
            if dt.month < now.month - 3:
                dt = dt.replace(year=now.year + 1)
            dates.append(dt.strftime("%Y-%m-%d"))
        except ValueError:
            pass
    return dates


def fetch_fantasypros(fp_daterange):
    """
    Fetch the FantasyPros probables grid for the given week index.
    Returns { "severino": ["2026-03-27", ...], ... } or {} on failure.
    """
    url = f"https://www.fantasypros.com/mlb/probable-pitchers.php?daterange={fp_daterange}"
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.fantasypros.com/mlb/",
        }, timeout=10)
        print(f"[mlb.py] FantasyPros status: {resp.status_code}, len: {len(resp.text)}")
        html = resp.text
    except Exception as e:
        print(f"[mlb.py] FantasyPros fetch failed: {e}")
        return {}

    col_dates = parse_fp_date_headers(html)
    print(f"[mlb.py] FantasyPros col_dates found: {col_dates}")

    if not col_dates:
        print("[mlb.py] FantasyPros: could not parse date headers")
        return {}

    parser = ProbablesTableParser(col_dates)
    parser.feed(html)
    print(f"[mlb.py] FantasyPros parsed {len(parser.result)} pitchers")
    return parser.result


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
    fp_data = fetch_fantasypros(mp["fp_daterange"])
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
        fp_data = fetch_fantasypros(mp["fp_daterange"])
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