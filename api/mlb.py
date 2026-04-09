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
    Fetch probable pitchers AND full game schedule from ESPN scoreboard API
    for each day in the range.

    Returns a tuple:
      - pitchers: { "crochet": ["2026-03-27", ...], ... }
      - schedule: {
          "2026-03-27": {
            "BOS": {"opponent": "CIN", "is_home": False, "status": "scheduled"},
            "CIN": {"opponent": "BOS", "is_home": True,  "status": "scheduled"},
          },
          ...
        }

    schedule status values:
      "scheduled" — game hasn't started yet
      "in_progress" — game is live right now
      "final" — game is finished
    """
    start_dt = datetime.strptime(period_start, "%Y-%m-%d")
    end_dt   = datetime.strptime(period_end,   "%Y-%m-%d")

    pitchers = {}   # last_name -> [dates]
    schedule = {}   # date -> { team_abbrev -> {opponent, is_home, status} }

    current = start_dt

    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")   # ESPN wants YYYYMMDD
        iso_date = current.strftime("%Y-%m-%d") # We store YYYY-MM-DD

        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
            f"?dates={date_str}&limit=50"
        )
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = r.json()

            schedule[iso_date] = {}

            for event in data.get("events", []):
                # ── Game status ──────────────────────────────────────────
                status_obj  = event.get("status", {}).get("type", {})
                status_name = status_obj.get("name", "STATUS_SCHEDULED")
                if status_name == "STATUS_FINAL":
                    game_status = "final"
                elif status_name in ("STATUS_IN_PROGRESS", "STATUS_MIDDLE_INNING",
                                     "STATUS_END_INNING"):
                    game_status = "in_progress"
                else:
                    game_status = "scheduled"

                competition = event.get("competitions", [{}])[0]
                competitors = competition.get("competitors", [])

                # ── Team abbreviations for both sides ─────────────────────
                # ESPN competitor homeAway: "home" or "away"
                teams_in_game = {}  # "home"/"away" -> abbrev
                for comp in competitors:
                    side   = comp.get("homeAway", "")        # "home" or "away"
                    abbrev = comp.get("team", {}).get("abbreviation", "")
                    if side and abbrev:
                        teams_in_game[side] = abbrev

                home_abbrev = teams_in_game.get("home", "")
                away_abbrev = teams_in_game.get("away", "")

                # Normalize ESPN Scoreboard abbreviations to match our PRO_TEAM_MAP
                ABBREV_MAP = {
                    "CHW": "CWS",  # Chicago White Sox
                    "KCR": "KC",   # Kansas City Royals
                    "TBR": "TB",   # Tampa Bay Rays
                    "SDP": "SD",   # San Diego Padres
                    "SFG": "SF",   # San Francisco Giants
                    "WSN": "WSH",  # Washington Nationals
                    "NYM": "NYM",  # already correct
                }
                home_abbrev = ABBREV_MAP.get(home_abbrev, home_abbrev)
                away_abbrev = ABBREV_MAP.get(away_abbrev, away_abbrev)

                # ── Record game in schedule dict ──────────────────────────
                if home_abbrev and away_abbrev:
                    schedule[iso_date][home_abbrev] = {
                        "opponent": away_abbrev,
                        "is_home":  True,
                        "status":   game_status,
                    }
                    schedule[iso_date][away_abbrev] = {
                        "opponent": home_abbrev,
                        "is_home":  False,
                        "status":   game_status,
                    }

                # ── Probable pitchers (same logic as before) ──────────────
                for comp in competitors:
                    for probable in comp.get("probables", []):
                        if probable.get("name") != "probableStartingPitcher":
                            continue
                        athlete  = probable.get("athlete", {})
                        full_name = athlete.get("fullName", "")
                        if full_name:
                            last_name = full_name.split()[-1].lower()
                            if last_name in ("jr.", "sr.", "ii", "iii", "iv"):
                                parts     = full_name.split()
                                last_name = parts[-2].lower() if len(parts) >= 2 else last_name
                            pitchers.setdefault(last_name, [])
                            if iso_date not in pitchers[last_name]:
                                pitchers[last_name].append(iso_date)

        except Exception as e:
            print(f"[mlb.py] ESPN scoreboard fetch failed for {date_str}: {e}")

        current += timedelta(days=1)

    print(f"[mlb.py] ESPN scoreboard: {len(pitchers)} pitchers, "
          f"{sum(len(v) for v in schedule.values())} team-days across "
          f"{len(schedule)} days")
    return pitchers, schedule


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

        # Build startDates — we need to know which team this pitcher is on
        # to look up their opponent. We find their team by scanning the schedule
        # for a day they start and matching their last name via the probables data.
        start_list = []
        for d in period_dates:
            # opponent is filled in later by get_starts_for_players()
            # which has the full player name → team mapping
            start_list.append({
                "date":      d,
                "confirmed": d in mlb_dates,
                "opponent":  "",
            })

        result[name] = {
            "starts":     len(start_list),
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

def get_starts_for_players(player_names, matchup_period, team_map=None):
    """
    Given a list of full player names and a matchup period number,
    returns a tuple:
      - starts_map:  { "Garrett Crochet": {"starts": 2, "startDates": [...]} }
      - schedule:    { "2026-03-26": { "BOS": {opponent, is_home, status}, ... } }

    team_map: optional { "Garrett Crochet": "BOS" } — used to add opponent
    info to each startDate entry so the projection model can apply matchup factors.
    """
    if matchup_period not in MATCHUP_PERIODS:
        return {}, {}

    mp       = MATCHUP_PERIODS[matchup_period]
    mlb_data = fetch_mlb_probables(mp["start"], mp["end"])

    fp_data, schedule = fetch_espn_probables(mp["start"], mp["end"])

    pitcher_starts = build_pitcher_starts(mlb_data, fp_data, mp["start"], mp["end"])

    result = {}
    for full_name in player_names:
        last_name = full_name.split()[-1].lower()
        if last_name in ("jr.", "sr.", "ii", "iii", "iv"):
            parts     = full_name.split()
            last_name = parts[-2].lower() if len(parts) >= 2 else last_name
        if last_name in pitcher_starts:
            entry = pitcher_starts[last_name]
            # Add opponent to each startDate using the schedule + team_map
            if team_map and full_name in team_map:
                team_abbrev = team_map[full_name]
                for sd in entry["startDates"]:
                    day = schedule.get(sd["date"], {})
                    game = day.get(team_abbrev, {})
                    sd["opponent"] = game.get("opponent", "")
            result[full_name] = entry
        else:
            result[full_name] = {"starts": 0, "startDates": []}

    return result, schedule


# ---------------------------------------------------------------------------
# Team wOBA — used for opponent quality adjustment in projections.
#
# Fetches team-level hitting stats from MLB Stats API and computes wOBA
# for each team. Returns factors relative to league average (1.0 = average).
# Teams with fewer than 10 games are returned as 1.0 (not enough data).
#
# wOBA formula:
#   (0.69×uBB + 0.72×HBP + 0.89×1B + 1.27×2B + 1.62×3B + 2.10×HR) / PA
# where uBB = BB - IBB, 1B = H - 2B - 3B - HR
# ---------------------------------------------------------------------------

# MLB Stats API team ID → abbreviation (verified 2026)
MLB_TEAM_ID_TO_ABBREV = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC",  119: "LAD", 120: "WSH", 121: "NYM", 133: "ATH",
    134: "PIT", 135: "SD",  136: "SEA", 137: "SF",  138: "STL",
    139: "TB",  140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}

def get_team_woba(season: int = 2026) -> dict:
    """
    Returns { "LAD": 1.08, "CWS": 0.91, ... } — wOBA relative to league avg.
    Falls back to empty dict on any error (caller treats missing teams as 1.0).
    """
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/teams/stats",
            params={
                "stats":    "season",
                "group":    "hitting",
                "gameType": "R",
                "season":   str(season),
                "sportId":  1,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[mlb.py] Team stats API returned {r.status_code}")
            return {}

        splits = r.json().get("stats", [{}])[0].get("splits", [])

        # Compute raw wOBA per team
        raw_wobas = {}
        for split in splits:
            team_id = split.get("team", {}).get("id")
            abbrev  = MLB_TEAM_ID_TO_ABBREV.get(team_id)
            if not abbrev:
                continue

            s  = split.get("stat", {})
            gp = s.get("gamesPlayed", 0)
            if gp < 10:
                # Too early in season — not enough data to trust
                raw_wobas[abbrev] = None
                continue

            pa  = s.get("plateAppearances", 0)
            if pa == 0:
                continue

            bb  = s.get("baseOnBalls", 0)
            ibb = s.get("intentionalWalks", 0)
            hbp = s.get("hitByPitch", 0)
            h   = s.get("hits", 0)
            d   = s.get("doubles", 0)
            t   = s.get("triples", 0)
            hr  = s.get("homeRuns", 0)

            ubb = bb - ibb
            single = h - d - t - hr

            woba = (
                0.69 * ubb +
                0.72 * hbp +
                0.89 * single +
                1.27 * d +
                1.62 * t +
                2.10 * hr
            ) / pa

            raw_wobas[abbrev] = woba

        # Compute league average from teams with enough data
        valid = [w for w in raw_wobas.values() if w is not None]
        if not valid:
            return {}

        lg_avg = sum(valid) / len(valid)
        print(f"[mlb.py] League avg wOBA: {lg_avg:.3f} across {len(valid)} teams")

        # Return factors relative to league average
        # Teams without enough data get 1.0 (league average)
        factors = {}
        for abbrev, woba in raw_wobas.items():
            if woba is None:
                factors[abbrev] = 1.0
            else:
                factors[abbrev] = round(woba / lg_avg, 4)
                print(f"[mlb.py] {abbrev}: wOBA {woba:.3f} → factor {factors[abbrev]:.3f}")

        return factors

    except Exception as e:
        print(f"[mlb.py] get_team_woba failed: {e}")
        return {}


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
        fp_data, schedule = fetch_espn_probables(mp["start"], mp["end"])
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
        "schedule": schedule,
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