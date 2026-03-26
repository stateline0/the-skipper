"""
/api/config.py — Returns default config values from env vars
so the frontend can pre-populate fields on page load.
"""
import json
import os
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {
            "teamId": os.environ.get("ESPN_TEAM_ID", "1"),
            "defaultLimit": int(os.environ.get("ESPN_STARTS_LIMIT", "12")),
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
