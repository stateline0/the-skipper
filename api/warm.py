"""
api/warm.py — periodic warm-cache job (Vercel cron).

Precomputes the per-team league-data payload into KV so /api/espn can serve it
instantly even on a cold first load. Scheduled frequently (see vercel.json) so
the cached blob (30-min TTL in espn.py) never expires between runs.

Secured with CRON_SECRET — Vercel sends it automatically as a Bearer header,
same pattern as api/cron.py.
"""
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mlb import MATCHUP_PERIODS
from espn import build_and_cache_league_data


def _current_period() -> int:
    """Matchup period number for today's date (mirrors cron.get_current_period
    without pulling in the heavy cron module)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for num, mp in MATCHUP_PERIODS.items():
        if mp["start"] <= today <= mp["end"]:
            return num
    return 1


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # ── Verify CRON_SECRET ────────────────────────────────────────
        cron_secret = os.environ.get("CRON_SECRET", "")
        if cron_secret and self.headers.get("Authorization", "") != f"Bearer {cron_secret}":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "Unauthorized"}).encode())
            return

        team_id = int(os.environ.get("ESPN_TEAM_ID", "1"))
        week    = _current_period()
        try:
            payload = build_and_cache_league_data(team_id, week)
            result = {
                "ok":         True,
                "teamId":     team_id,
                "week":       week,
                "rosterSPs":  len(payload.get("rosterSPs", [])),
                "freeAgents": len(payload.get("freeAgentSPs", [])),
                "computedAt": payload.get("computedAt"),
            }
            print(f"[warm.py] Warmed league data — team {team_id}, week {week}, "
                  f"{result['rosterSPs']} SPs / {result['freeAgents']} FAs")
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            print(f"[warm.py] Warm failed: {e}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
