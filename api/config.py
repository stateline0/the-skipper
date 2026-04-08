"""
/api/config.py — Returns default config values from env vars
so the frontend can pre-populate fields on page load.
Also exposes the full 2026 matchup period table so the frontend
can render a period selector dropdown.
"""
import json
import os
from datetime import date
from http.server import BaseHTTPRequestHandler

# All 22 ESPN regular-season matchup periods for 2026.
# Dates are full ISO format (YYYY-MM-DD) — single source of truth.
# mlb.py has its own copy to avoid cross-file imports in serverless context.
MATCHUP_PERIODS = [
    {"period": 1,  "label": "Period 1",  "start": "2026-03-25", "end": "2026-04-05",  "limit": 21},
    {"period": 2,  "label": "Period 2",  "start": "2026-04-06", "end": "2026-04-12",  "limit": 12},
    {"period": 3,  "label": "Period 3",  "start": "2026-04-13", "end": "2026-04-19",  "limit": 12},
    {"period": 4,  "label": "Period 4",  "start": "2026-04-20", "end": "2026-04-26",  "limit": 12},
    {"period": 5,  "label": "Period 5",  "start": "2026-04-27", "end": "2026-05-03",  "limit": 12},
    {"period": 6,  "label": "Period 6",  "start": "2026-05-04", "end": "2026-05-10",  "limit": 12},
    {"period": 7,  "label": "Period 7",  "start": "2026-05-11", "end": "2026-05-17",  "limit": 12},
    {"period": 8,  "label": "Period 8",  "start": "2026-05-18", "end": "2026-05-24",  "limit": 12},
    {"period": 9,  "label": "Period 9",  "start": "2026-05-25", "end": "2026-05-31",  "limit": 12},
    {"period": 10, "label": "Period 10", "start": "2026-06-01", "end": "2026-06-07",  "limit": 12},
    {"period": 11, "label": "Period 11", "start": "2026-06-08", "end": "2026-06-14",  "limit": 12},
    {"period": 12, "label": "Period 12", "start": "2026-06-15", "end": "2026-06-21",  "limit": 12},
    {"period": 13, "label": "Period 13", "start": "2026-06-22", "end": "2026-06-28",  "limit": 12},
    {"period": 14, "label": "Period 14", "start": "2026-06-29", "end": "2026-07-05",  "limit": 12},
    {"period": 15, "label": "Period 15", "start": "2026-07-06", "end": "2026-07-19",  "limit": 19},
    {"period": 16, "label": "Period 16", "start": "2026-07-20", "end": "2026-07-26",  "limit": 12},
    {"period": 17, "label": "Period 17", "start": "2026-07-27", "end": "2026-08-02",  "limit": 12},
    {"period": 18, "label": "Period 18", "start": "2026-08-03", "end": "2026-08-09",  "limit": 12},
    {"period": 19, "label": "Period 19", "start": "2026-08-10", "end": "2026-08-16",  "limit": 12},
    {"period": 20, "label": "Period 20", "start": "2026-08-17", "end": "2026-08-23",  "limit": 12},
    {"period": 21, "label": "Period 21", "start": "2026-08-24", "end": "2026-08-30",  "limit": 12},
    {"period": 22, "label": "Period 22", "start": "2026-08-31", "end": "2026-09-06",  "limit": 12},
]


def get_current_period() -> int:
    """Return the matchup period number that contains today's date."""
    today = date.today().isoformat()  # "2026-04-07"
    for mp in MATCHUP_PERIODS:
        if mp["start"] <= today <= mp["end"]:
            return mp["period"]
    # Fallback: if today is before the season, return 1.
    # If after the season, return the last period.
    if today < MATCHUP_PERIODS[0]["start"]:
        return 1
    return MATCHUP_PERIODS[-1]["period"]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {
            "teamId":         os.environ.get("ESPN_TEAM_ID", "1"),
            "defaultLimit":   int(os.environ.get("ESPN_STARTS_LIMIT", "12")),
            "matchupPeriods": MATCHUP_PERIODS,
            "currentPeriod":  get_current_period(),
        }
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