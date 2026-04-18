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
        #
        # Minimal filter — the first spike confirmed this shape returns HTTP 200.
        # Aggressive filter additions (filterStatsForSourceIds / SplitTypeIds /
        # TopScoringPeriodIds / CurrentSeason) produced HTTP 400, so we back off
        # and parse player.stats[] directly. raw_stats_sample will dump whatever
        # ESPN returns so we can see the real shape without asking ESPN to filter.
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
        raw_stats_sample = None  # dump first pitcher's full stats[] for inspection
        raw_player_keys = None   # dump first pitcher's top-level response keys for inspection
        for p in r2.json().get("players", []):
            pid = p.get("id")
            player = p.get("player", {})
            name = player.get("fullName", "") or id_to_name.get(pid, "")
            pool = p.get("playerPoolEntry", {})
            pool_player = pool.get("player", {})

            # Only include pitchers — skip hitters on the roster.
            # Use eligibleSlots: 13 = P (active pitcher), 14 = SP, 15 = RP.
            eligible = set(player.get("eligibleSlots", []) or pool_player.get("eligibleSlots", []))
            if not (13 in eligible or 14 in eligible or 15 in eligible):
                continue

            # Projections live in player.stats[] — each entry has:
            #   statSourceId: 0 = actuals, 1 = ESPN projections
            #   statSplitTypeId: 0 = season, 1 = last 7, 3 = projections cumulative, 5 = per-game
            #   scoringPeriodId: specific day this entry is for
            #   appliedTotal: FPTS under the league's scoring settings
            #
            # We want the entry with statSourceId=1 matching our target scoring period.
            stats_arr = player.get("stats", []) or pool_player.get("stats", [])
            projected_applied_total = None
            projected_entries = []
            for s in stats_arr:
                entry_summary = {
                    "statSourceId":     s.get("statSourceId"),
                    "statSplitTypeId":  s.get("statSplitTypeId"),
                    "scoringPeriodId":  s.get("scoringPeriodId"),
                    "seasonId":         s.get("seasonId"),
                    "appliedTotal":     s.get("appliedTotal"),
                    "externalId":       s.get("externalId"),
                }
                # Gather all projection-sourced entries for this player
                if s.get("statSourceId") == 1:
                    projected_entries.append(entry_summary)
                # Primary candidate: projection for exactly this scoring period
                if (
                    s.get("statSourceId") == 1
                    and s.get("scoringPeriodId") == scoring_period_id
                    and projected_applied_total is None
                ):
                    projected_applied_total = s.get("appliedTotal")

            # Dump the first pitcher's full stats[] so we can see the exact shape
            if raw_stats_sample is None and stats_arr:
                raw_stats_sample = {
                    "player": name,
                    "player_id": pid,
                    "stats_array_length": len(stats_arr),
                    "all_stat_entries": [
                        {
                            "statSourceId":    s.get("statSourceId"),
                            "statSplitTypeId": s.get("statSplitTypeId"),
                            "scoringPeriodId": s.get("scoringPeriodId"),
                            "seasonId":        s.get("seasonId"),
                            "appliedTotal":    s.get("appliedTotal"),
                            "externalId":      s.get("externalId"),
                        }
                        for s in stats_arr
                    ],
                }
            # Also dump the first pitcher's top-level response keys so we can see
            # what ESPN returns overall (sometimes stats live under different parent keys)
            if raw_player_keys is None:
                raw_player_keys = {
                    "player": name,
                    "top_level_keys":           sorted(list(p.keys())),
                    "player_object_keys":       sorted(list(player.keys())),
                    "playerPoolEntry_keys":     sorted(list(pool.keys())),
                    "pool_player_keys":         sorted(list(pool_player.keys())),
                    "player_stats_is_array":    isinstance(player.get("stats"), list),
                    "pool_player_stats_is_arr": isinstance(pool_player.get("stats"), list),
                }

            results.append({
                "player_id": pid,
                "name": name,
                "pool_applied_stat_total": pool.get("appliedStatTotal"),
                "projected_applied_total": projected_applied_total,
                "projection_entries_found": len(projected_entries),
                "projection_entry_samples": projected_entries[:5],
            })

        # Sort by projected applied total desc
        results.sort(
            key=lambda x: (x["projected_applied_total"] or 0),
            reverse=True,
        )
        return {
            "players": results,
            "scoring_period_id": scoring_period_id,
            "roster_size": len(player_ids),
            "raw_stats_sample": raw_stats_sample,
            "raw_player_keys": raw_player_keys,
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
