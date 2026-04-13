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

    pitchers = {}   # full_name_lower -> [dates]
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

                # ── Extract moneyline odds for win probability ─────────────
                # ESPN scoreboard includes DraftKings odds inline — zero extra API calls.
                # American odds → implied probability (normalized to remove vig):
                #   Negative (favorite): prob = |odds| / (|odds| + 100)
                #   Positive (underdog): prob = 100 / (odds + 100)
                home_win_prob = None
                away_win_prob = None
                odds_list = competition.get("odds", [])
                if odds_list:
                    odds_data = odds_list[0]  # DraftKings (primary provider)
                    ml = odds_data.get("moneyline", {})
                    home_ml_str = ml.get("home", {}).get("close", {}).get("odds", "")
                    away_ml_str = ml.get("away", {}).get("close", {}).get("odds", "")
                    try:
                        if home_ml_str:
                            home_ml = int(home_ml_str)
                            if home_ml < 0:
                                home_win_prob = abs(home_ml) / (abs(home_ml) + 100)
                            else:
                                home_win_prob = 100 / (home_ml + 100)
                        if away_ml_str:
                            away_ml = int(away_ml_str)
                            if away_ml < 0:
                                away_win_prob = abs(away_ml) / (abs(away_ml) + 100)
                            else:
                                away_win_prob = 100 / (away_ml + 100)
                        # Normalize so probabilities sum to 1.0 (remove vig/juice)
                        if home_win_prob and away_win_prob:
                            total = home_win_prob + away_win_prob
                            home_win_prob = round(home_win_prob / total, 3)
                            away_win_prob = round(away_win_prob / total, 3)
                    except (ValueError, ZeroDivisionError):
                        home_win_prob = None
                        away_win_prob = None

                # ── Record game in schedule dict ──────────────────────────
                if home_abbrev and away_abbrev:
                    schedule[iso_date][home_abbrev] = {
                        "opponent": away_abbrev,
                        "is_home":  True,
                        "status":   game_status,
                        "win_prob": home_win_prob,
                    }
                    schedule[iso_date][away_abbrev] = {
                        "opponent": home_abbrev,
                        "is_home":  False,
                        "status":   game_status,
                        "win_prob": away_win_prob,
                    }

                # ── Probable pitchers (same logic as before) ──────────────
                # Also track which pitcher is starting for each team so we can
                # look up the opponent starter's xERA for win probability adjustment.
                game_starters = {}  # "home"/"away" -> full_name_lower
                for comp in competitors:
                    side = comp.get("homeAway", "")
                    for probable in comp.get("probables", []):
                        if probable.get("name") != "probableStartingPitcher":
                            continue
                        athlete   = probable.get("athlete", {})
                        full_name = athlete.get("fullName", "")
                        if full_name:
                            key = full_name.strip().lower()
                            pitchers.setdefault(key, [])
                            if iso_date not in pitchers[key]:
                                pitchers[key].append(iso_date)
                            if side:
                                game_starters[side] = key

                # Add opponent starter to schedule entries
                if home_abbrev and away_abbrev:
                    home_entry = schedule[iso_date].get(home_abbrev, {})
                    away_entry = schedule[iso_date].get(away_abbrev, {})
                    # Home team's opponent starter is the away pitcher
                    if "away" in game_starters:
                        home_entry["opp_starter"] = game_starters["away"]
                    # Away team's opponent starter is the home pitcher
                    if "home" in game_starters:
                        away_entry["opp_starter"] = game_starters["home"]
                    if home_entry:
                        schedule[iso_date][home_abbrev] = home_entry
                    if away_entry:
                        schedule[iso_date][away_abbrev] = away_entry

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
                        key = full_name.strip().lower()
                        result.setdefault(key, [])
                        if game_date not in result[key]:
                            result[key].append(game_date)
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
        key = full_name.strip().lower()
        if key in pitcher_starts:
            entry = pitcher_starts[key]
            # Add opponent and is_home to each startDate using the schedule + team_map
            if team_map and full_name in team_map:
                team_abbrev = team_map[full_name]
                for sd in entry["startDates"]:
                    day = schedule.get(sd["date"], {})
                    game = day.get(team_abbrev, {})
                    sd["opponent"] = game.get("opponent", "")
                    sd["is_home"]  = game.get("is_home", True)
                    sd["win_prob"] = game.get("win_prob")  # Vegas implied win probability
                    sd["opp_starter"] = game.get("opp_starter")  # opponent pitcher name (lowercase)
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
# Team Win Probability Model — Pythagorean expectation + pitcher adjustment
#
# Pythagorean formula: W% = RS^1.83 / (RS^1.83 + RA^1.83)
# Log5 for head-to-head: P(A) = (pA × (1-pB)) / (pA × (1-pB) + pB × (1-pA))
# Pitcher adjustment: scale by pitcher xERA relative to team ERA
# ---------------------------------------------------------------------------

def get_team_win_data(season: int = 2026) -> dict:
    """
    Fetch team run data and compute Pythagorean expected win%.
    Also returns team ERA for pitcher-quality adjustments.

    Returns {
        "LAD": {"pyth_wpct": 0.620, "era": 3.25, "games": 15},
        "CWS": {"pyth_wpct": 0.380, "era": 5.10, "games": 15},
        ...
    }
    """
    from concurrent.futures import ThreadPoolExecutor
    try:
        def fetch_hitting():
            return requests.get(
                "https://statsapi.mlb.com/api/v1/teams/stats",
                params={"stats": "season", "group": "hitting", "gameType": "R",
                        "season": str(season), "sportId": 1},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
            )

        def fetch_pitching():
            return requests.get(
                "https://statsapi.mlb.com/api/v1/teams/stats",
                params={"stats": "season", "group": "pitching", "gameType": "R",
                        "season": str(season), "sportId": 1},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_hit = executor.submit(fetch_hitting)
            f_pit = executor.submit(fetch_pitching)
            hit_r = f_hit.result()
            pit_r = f_pit.result()

        if hit_r.status_code != 200 or pit_r.status_code != 200:
            print(f"[mlb.py] Team win data API error: hit={hit_r.status_code}, pit={pit_r.status_code}")
            return {}

        # Parse hitting (runs scored)
        hit_splits = hit_r.json().get("stats", [{}])[0].get("splits", [])
        team_rs = {}
        for split in hit_splits:
            team_id = split.get("team", {}).get("id")
            abbrev = MLB_TEAM_ID_TO_ABBREV.get(team_id)
            if not abbrev:
                continue
            s = split.get("stat", {})
            gp = s.get("gamesPlayed", 0)
            runs = s.get("runs", 0)
            if gp > 0:
                team_rs[abbrev] = {"runs": runs, "games": gp}

        # Parse pitching (runs allowed + ERA)
        pit_splits = pit_r.json().get("stats", [{}])[0].get("splits", [])
        team_ra = {}
        for split in pit_splits:
            team_id = split.get("team", {}).get("id")
            abbrev = MLB_TEAM_ID_TO_ABBREV.get(team_id)
            if not abbrev:
                continue
            s = split.get("stat", {})
            runs = s.get("runs", 0)
            era_str = s.get("era", "4.50")
            try:
                era = float(era_str)
            except (ValueError, TypeError):
                era = 4.50
            team_ra[abbrev] = {"runs": runs, "era": era}

        # Compute Pythagorean expected W%
        result = {}
        exp = 1.83
        for abbrev in team_rs:
            if abbrev not in team_ra:
                continue
            games = team_rs[abbrev]["games"]
            if games < 5:
                continue
            rs = team_rs[abbrev]["runs"]
            ra = team_ra[abbrev]["runs"]
            if ra == 0:
                pyth = 0.99
            else:
                rs_exp = rs ** exp
                ra_exp = ra ** exp
                pyth = rs_exp / (rs_exp + ra_exp)

            result[abbrev] = {
                "pyth_wpct": round(pyth, 3),
                "era":       team_ra[abbrev]["era"],
                "games":     games,
            }

        print(f"[mlb.py] Pythagorean W%: {len(result)} teams")
        for abbrev, d in sorted(result.items(), key=lambda x: -x[1]["pyth_wpct"])[:5]:
            print(f"[mlb.py]   {abbrev}: pyth={d['pyth_wpct']:.3f}, ERA={d['era']:.2f}")

        return result

    except Exception as e:
        print(f"[mlb.py] get_team_win_data failed: {e}")
        return {}


def compute_matchup_win_prob(team_abbrev, opp_abbrev, team_win_data,
                             pitcher_xera=None, opp_pitcher_xera=None):
    """
    Compute win probability using Pythagorean + Log5 + pitcher adjustments.

    Returns float between 0 and 1, or None if insufficient data.
    """
    team_data = team_win_data.get(team_abbrev)
    opp_data  = team_win_data.get(opp_abbrev)
    if not team_data or not opp_data:
        return None

    # Step 1: Log5 from Pythagorean W%
    pA = team_data["pyth_wpct"]
    pB = opp_data["pyth_wpct"]
    denom = pA * (1 - pB) + pB * (1 - pA)
    base_prob = (pA * (1 - pB)) / denom if denom else 0.5

    # Step 2: Adjust for our pitcher quality (xERA vs team ERA)
    pitcher_adj = 1.0
    if pitcher_xera and pitcher_xera > 0 and team_data["era"] > 0:
        raw = team_data["era"] / pitcher_xera
        pitcher_adj = max(0.7, min(1.4, raw))  # cap to prevent extremes

    # Step 3: Adjust for opponent pitcher quality (inverted — higher xERA = better for us)
    opp_pitcher_adj = 1.0
    if opp_pitcher_xera and opp_pitcher_xera > 0 and opp_data["era"] > 0:
        raw = opp_pitcher_xera / opp_data["era"]
        opp_pitcher_adj = max(0.7, min(1.4, raw))

    # Apply in odds space to keep probability bounded 0-1
    if base_prob <= 0 or base_prob >= 1:
        return round(base_prob, 3)
    base_odds = base_prob / (1 - base_prob)
    adj_odds = base_odds * pitcher_adj * opp_pitcher_adj
    return round(adj_odds / (1 + adj_odds), 3)


# ---------------------------------------------------------------------------
# Game Logs — per-start stats for recent form weighting (Layer 2).
#
# Fetches game-by-game pitching stats from MLB Stats API. Returns each
# pitcher's individual game lines so we can compute a weighted rolling
# average of their last N starts.
#
# The endpoint returns ALL pitchers' game logs in one call (no need to
# look up individual player IDs), making it efficient for our use case.
#
# Endpoint: /api/v1/stats?stats=gameLog&playerPool=all&group=pitching
#           &season=YYYY&gameType=R&limit=1000
# ---------------------------------------------------------------------------

import unicodedata as _unicodedata

def _strip_accents_mlb(s: str) -> str:
    """Normalize accented characters for name matching."""
    return ''.join(
        c for c in _unicodedata.normalize('NFD', s)
        if _unicodedata.category(c) != 'Mn'
    ).lower()


def fetch_game_logs(season: int) -> dict:
    """
    Fetch per-game pitching stats for all pitchers in a season.

    Returns: {
        "garrett crochet": [
            {"date": "2026-04-07", "ip": 6.0, "h": 4, "er": 1, "so": 8,
             "bb": 2, "hb": 0, "w": 1, "l": 0, "sv": 0, "gs": 1},
            ...
        ],
        ...
    }

    Games are sorted by date (most recent last) so we can easily
    grab the last N starts for recent form weighting.
    """
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/stats",
            params={
                "stats": "gameLog",
                "playerPool": "all",
                "group": "pitching",
                "season": str(season),
                "gameType": "R",
                "limit": 5000,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[mlb.py] Game logs returned HTTP {r.status_code}")
            return {}

        splits = r.json().get("stats", [{}])[0].get("splits", [])
        print(f"[mlb.py] Game logs: {len(splits)} total entries for {season}")

        result = {}
        for split in splits:
            player = split.get("player", {})
            full_name = player.get("fullName", "")
            if not full_name:
                continue

            stat = split.get("stat", {})
            game_date = split.get("date", "")
            if not game_date:
                continue

            name_key = _strip_accents_mlb(full_name)

            # Parse IP from string format (e.g., "6.2" = 6 innings + 2 outs)
            ip_str = str(stat.get("inningsPitched", "0.0"))
            try:
                parts = ip_str.split(".")
                ip = int(parts[0]) + (int(parts[1]) / 3 if len(parts) > 1 else 0)
            except Exception:
                ip = 0.0

            game_entry = {
                "date": game_date,
                "ip":   ip,
                "h":    int(stat.get("hits", 0)),
                "er":   int(stat.get("earnedRuns", 0)),
                "so":   int(stat.get("strikeOuts", 0)),
                "bb":   int(stat.get("baseOnBalls", 0)),
                "hb":   int(stat.get("hitBatsmen", 0)),
                "w":    int(stat.get("wins", 0)),
                "l":    int(stat.get("losses", 0)),
                "sv":   int(stat.get("saves", 0)),
                "gs":   int(stat.get("gamesStarted", 0)),
            }

            if name_key not in result:
                result[name_key] = []
            result[name_key].append(game_entry)

        # Sort each pitcher's games by date (oldest first, most recent last)
        for name_key in result:
            result[name_key].sort(key=lambda g: g["date"])

        print(f"[mlb.py] Game logs: {len(result)} unique pitchers")
        return result

    except Exception as e:
        print(f"[mlb.py] fetch_game_logs failed: {e}")
        return {}


def compute_recent_form_fpts(games: list, n_starts: int = 4) -> float:
    """
    Compute a weighted-average FPTS from a pitcher's last N starts.

    Weights: most recent = 40%, second = 30%, third = 20%, fourth = 10%
    This captures hot/cold streaks without overreacting to one bad outing.

    Only considers games where gs=1 (actual starts, not relief appearances).
    Returns None if the pitcher has fewer than n_starts starts.

    The FPTS formula matches our league scoring:
      IP×3 + K×1 + H×(-1) + BB×(-1) + ER×(-2) + HBP×(-1) + W×5 + L×(-5) + SV×5
    """
    # Filter to only starts (gs=1), not relief appearances
    starts = [g for g in games if g.get("gs", 0) >= 1]

    if len(starts) < n_starts:
        return None

    # Take the last n_starts
    recent = starts[-n_starts:]

    # Weights: most recent gets highest weight
    # recent[-1] = most recent, recent[-2] = second most recent, etc.
    weights = [0.10, 0.20, 0.30, 0.40]  # oldest to most recent

    weighted_fpts = 0.0
    for i, game in enumerate(recent):
        fpts = (
            game["ip"]  *  3 +
            game["so"]  *  1 +
            game["h"]   * -1 +
            game["bb"]  * -1 +
            game["er"]  * -2 +
            game["hb"]  * -1 +
            game["w"]   *  5 +
            game["l"]   * -5 +
            game["sv"]  *  5
        )
        weighted_fpts += fpts * weights[i]

    return round(weighted_fpts, 1)


# ---------------------------------------------------------------------------
# HTTP handler — /api/mlb?period=N
# Useful for testing the data independently of espn.py
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Park Factors — Statcast 3-year rolling Runs factor from Baseball Savant.
#
# Keyed by team abbreviation = the team whose HOME park is used.
# 100 = league average. >100 = hitter-friendly (bad for pitchers).
# <100 = pitcher-friendly (good for pitchers).
#
# Source: baseballsavant.mlb.com/leaderboard/statcast-park-factors
# These are stable year-over-year (driven by dimensions & elevation),
# so hardcoding is the standard approach (FanGraphs does the same).
#
# Last updated: April 2026 (3-year rolling: 2023-2025)
# ---------------------------------------------------------------------------

PARK_FACTORS = {
    "ARI":  104,  # Chase Field — retractable roof, hot + dry
    "ATL":  100,  # Truist Park — neutral
    "ATH":   96,  # Sutter Health Park — pitcher-friendly (Sacramento)
    "BAL":  103,  # Camden Yards — recent LF wall changes boosted offense
    "BOS":  107,  # Fenway Park — short Green Monster, lots of doubles
    "CHC":  104,  # Wrigley Field — wind blowing out = HR park
    "CIN":  108,  # Great American Ball Park — small, HR-friendly
    "CLE":   97,  # Progressive Field — pitcher-friendly
    "COL":  115,  # Coors Field — elevation makes this #1 hitter park
    "CWS":  101,  # Guaranteed Rate Field — slightly above average
    "DET":   98,  # Comerica Park — spacious outfield
    "HOU":  101,  # Daikin Park (formerly Minute Maid) — Crawford Boxes in LF
    "KC":   100,  # Kauffman Stadium — neutral
    "LAA":  100,  # Angel Stadium — neutral
    "LAD":   94,  # Dodger Stadium — pitcher-friendly, marine layer
    "MIA":   96,  # loanDepot Park — pitcher-friendly, roof closed
    "MIL":  104,  # American Family Field — retractable roof
    "MIN":  102,  # Target Field — slightly hitter-friendly
    "NYM":   97,  # Citi Field — pitcher-friendly
    "NYY":  107,  # Yankee Stadium — short RF porch, lots of HR
    "PHI":  104,  # Citizens Bank Park — hitter-friendly
    "PIT":   96,  # PNC Park — pitcher-friendly
    "SD":    95,  # Petco Park — pitcher-friendly, marine layer
    "SEA":   93,  # T-Mobile Park — most pitcher-friendly in AL
    "SF":    92,  # Oracle Park — marine layer, spacious
    "STL":   99,  # Busch Stadium — slightly pitcher-friendly
    "TB":    96,  # Tropicana Field — dome, pitcher-friendly
    "TEX":  101,  # Globe Life Field — retractable roof
    "TOR":  103,  # Rogers Centre — slightly hitter-friendly
    "WSH":  100,  # Nationals Park — neutral
}


def get_park_factor(team_abbrev: str) -> float:
    """
    Returns the park factor as a multiplier for a specific team's home park.
    100 in the table = 1.0 (neutral). 115 (Coors) = 1.15 (bad for pitchers).

    For fantasy pitching projections, a higher park factor means FEWER
    fantasy points (more runs, hits allowed), so we INVERT it:
      - Coors (115) → 1.15 → pitcher scores ~15% worse
      - Oracle Park (92) → 0.92 → pitcher scores ~8% better

    But wait — park factors measure RUNS, not fantasy points directly.
    Fantasy scoring has a mix of positive (IP, K) and negative (H, ER, BB) stats.
    Only the negative stats (H, ER) are park-dependent. K rate and IP are
    mostly park-independent.

    So we dampen the park factor effect by 50%:
      - Coors: 1.0 + (1.15 - 1.0) * 0.5 = 1.075 (7.5% worse, not 15%)
      - Oracle: 1.0 + (0.92 - 1.0) * 0.5 = 0.96 (4% better, not 8%)

    This reflects that roughly half of FPTS come from park-independent stats.
    """
    raw = PARK_FACTORS.get(team_abbrev, 100)
    raw_factor = raw / 100.0
    # Dampen toward 1.0 by 50% — only H/ER are park-dependent
    dampened = 1.0 + (raw_factor - 1.0) * 0.5
    return round(dampened, 4)


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
        self.end_headers()# cache bust Fri Apr 10 16:29:15 CDT 2026
