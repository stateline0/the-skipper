"""
/api/config.py — Returns default config values from env vars
so the frontend can pre-populate fields on page load.
Also exposes the full 2026 matchup period table so the frontend
can render a period selector dropdown.
"""
import json
import os
from http.server import BaseHTTPRequestHandler

# All 22 ESPN regular-season matchup periods for 2026.
# This is the single source of truth — mlb.py also has this table
# but duplicating it here avoids a cross-file import in serverless context.
MATCHUP_PERIODS = [
    {"period": 1,  "label": "Period 1",  "start": "Mar 25", "end": "Apr 5",  "limit": 21},
    {"period": 2,  "label": "Period 2",  "start": "Apr 6",  "end": "Apr 12", "limit": 12},
    {"period": 3,  "label": "Period 3",  "start": "Apr 13", "end": "Apr 19", "limit": 12},
    {"period": 4,  "label": "Period 4",  "start": "Apr 20", "end": "Apr 26", "limit": 12},
    {"period": 5,  "label": "Period 5",  "start": "Apr 27", "end": "May 3",  "limit": 12},
    {"period": 6,  "label": "Period 6",  "start": "May 4",  "end": "May 10", "limit": 12},
    {"period": 7,  "label": "Period 7",  "start": "May 11", "end": "May 17", "limit": 12},
    {"period": 8,  "label": "Period 8",  "start": "May 18", "end": "May 24", "limit": 12},
    {"period": 9,  "label": "Period 9",  "start": "May 25", "end": "May 31", "limit": 12},
    {"period": 10, "label": "Period 10", "start": "Jun 1",  "end": "Jun 7",  "limit": 12},
    {"period": 11, "label": "Period 11", "start": "Jun 8",  "end": "Jun 14", "limit": 12},
    {"period": 12, "label": "Period 12", "start": "Jun 15", "end": "Jun 21", "limit": 12},
    {"period": 13, "label": "Period 13", "start": "Jun 22", "end": "Jun 28", "limit": 12},
    {"period": 14, "label": "Period 14", "start": "Jun 29", "end": "Jul 5",  "limit": 12},
    {"period": 15, "label": "Period 15", "start": "Jul 6",  "end": "Jul 19", "limit": 19},
    {"period": 16, "label": "Period 16", "start": "Jul 20", "end": "Jul 26", "limit": 12},
    {"period": 17, "label": "Period 17", "start": "Jul 27", "end": "Aug 2",  "limit": 12},
    {"period": 18, "label": "Period 18", "start": "Aug 3",  "end": "Aug 9",  "limit": 12},
    {"period": 19, "label": "Period 19", "start": "Aug 10", "end": "Aug 16", "limit": 12},
    {"period": 20, "label": "Period 20", "start": "Aug 17", "end": "Aug 23", "limit": 12},
    {"period": 21, "label": "Period 21", "start": "Aug 24", "end": "Aug 30", "limit": 12},
    {"period": 22, "label": "Period 22", "start": "Aug 31", "end": "Sep 6",  "limit": 12},
]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {
            "teamId": os.environ.get("ESPN_TEAM_ID", "1"),
            "defaultLimit": int(os.environ.get("ESPN_STARTS_LIMIT", "12")),
            "matchupPeriods": MATCHUP_PERIODS,
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