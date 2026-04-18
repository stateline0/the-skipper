"""
/api/espn_proj.py — Diagnostic endpoint for ESPN's own projection data.

Verifies whether `kona_player_info.appliedStatTotal` returns real per-day FPTS
projections for rostered pitchers at arbitrary future scoringPeriodIds.

KNOWLEDGE.md has a note from March 2026 warning that this field "returns empty/zero
early in season — do not rely on it." Now that we're ~4 weeks in, we need to confirm
whether ESPN has started populating real projections before we build comparison
tracking on top of it.

Usage:
  GET /api/espn_proj                  → projections for today's scoringPeriodId
  GET /api/espn_proj?date=2026-04-22  → projections for that specific date

Returns:
  {
    "ok": true,
    "date": "2026-04-22",
    "scoring_period_id": 29,
    "players": [
      {"player_id": 42903, "name": "Garrett Crochet", "applied_stat_total": 14.2},
      ...
    ]
  }

If appliedStatTotal values are all 0.0, ESPN's API isn't populating projections and
we need to pivot to scraping the Forecaster article or a paste-in flow. If they're
populated with real numbers that roughly match the Forecaster page, we wire straight
through to the accuracy dashboard comparison.
"""

import json
import os
import sys
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from fetcher import get_headers_and_cookies


# 2026 season opening day — scoringPeriodId starts at 1 here.
# Kept local to this module; this matches the formula in KNOWLEDGE.md.
SEASON_OPENING_DAY = date(2026, 3, 25)


def date_to_scoring_period(d: date) -> int:
    """Calendar date → ESPN scoringPeriodId. 2026-03-25 = 1."""
    return (d - SEASON_OPENING_DAY).days + 1


def fetch_roster_projections(scoring_period_id: int) -> dict:
    """
    Two-step fetch:
      1. mRoster → list of rostered player IDs and names for our team
      2. kona_player_info filtered to those IDs with filterStatsForCurrentSeasonScoringPeriodId
         → appliedStatTotal per pitcher for that specific day

    Returns {"players": [...], "scoring_period_id": N} on success,
            {"error": "..."} on any failure.
    """
    try:
        league_id = os.environ["ESPN_LEAGUE_ID"]
        year      = os.environ.get("ESPN_SEASON", "2026")
        team_id   = int(os.environ.get("ESPN_TEAM_ID", "6"))
        headers, cookies = get_headers_and_cookies()
        base = (
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
            f"/seasons/{year}/segments/0/leagues/{league_id}"
        )

        # Step 1 — pull roster to get the player IDs + names for our team.
        r = requests.get(
            base,
            params=[
                ("view", "mRoster"),
                ("view", "mTeam"),
                ("scoringPeriodId", scoring_period_id),
            ],
            cookies=cookies,
            headers=headers,
            timeout=15,
        )
        if r.status_code != 200:
            return {"error": f"mRoster fetch returned HTTP {r.status_code}"}

        data = r.json()
        my_team = next(
            (t for t in data.get("teams", []) if t.get("id") == team_id),
            {},
        )
        roster_entries = my_team.get("roster", {}).get("entries", [])
        id_to_name = {}
        player_ids = []
        for e in roster_entries:
            pid = e.get("playerId")
            name = (
                e.get("playerPoolEntry", {})
                .get("player", {})
                .get("fullName", "")
            )
            if pid:
                player_ids.append(pid)
                id_to_name[pid] = name

        if not player_ids:
            return {"error": "No roster players found"}

        # Step 2 — pull kona_player_info for those IDs at target scoring period.
        xff = json.dumps({
            "players": {
                "filterIds": {"value": player_ids},
                "filterStatsForCurrentSeasonScoringPeriodId": {
                    "value": [scoring_period_id]
                },
            }
        })
        r2 = requests.get(
            base,
            params=[
                ("view", "kona_player_info"),
                ("scoringPeriodId", scoring_period_id),
            ],
            cookies=cookies,
            headers={**headers, "x-fantasy-filter": xff},
            timeout=15,
        )
        if r2.status_code != 200:
            return {"error": f"kona_player_info fetch returned HTTP {r2.status_code}"}

        results = []
        for p in r2.json().get("players", []):
            pid = p.get("id")
            name = (
                p.get("player", {}).get("fullName", "")
                or id_to_name.get(pid, "")
            )
            pool = p.get("playerPoolEntry", {})
            applied = pool.get("appliedStatTotal")

            # Only include pitchers — skip hitters on the roster.
            # Use eligibleSlots check: 13 = P (active pitcher), 14 = SP, 15 = RP.
            eligible = set(p.get("player", {}).get("eligibleSlots", []))
            if not (13 in eligible or 14 in eligible or 15 in eligible):
                continue

            results.append({
                "player_id": pid,
                "name": name,
                "applied_stat_total": applied,
            })

        # Sort by applied_stat_total descending — highest projected first.
        results.sort(
            key=lambda x: (x["applied_stat_total"] or 0),
            reverse=True,
        )
        return {
            "players": results,
            "scoring_period_id": scoring_period_id,
            "roster_size": len(player_ids),
        }

    except Exception as e:
        return {"error": f"Exception: {type(e).__name__}: {e}"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        date_str = qs.get("date", [""])[0]

        if date_str:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                self._respond(400, {
                    "ok": False,
                    "error": "Invalid date format; use YYYY-MM-DD",
                })
                return
        else:
            d = date.today()

        spid = date_to_scoring_period(d)
        result = fetch_roster_projections(spid)
        ok = "error" not in result
        body = {"ok": ok, "date": d.isoformat(), **result}
        self._respond(200 if ok else 500, body)

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass
