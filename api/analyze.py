"""
/api/analyze.py  — Vercel Python serverless function
Calls Anthropic API with roster + FA data and returns structured recommendations.
ANTHROPIC_API_KEY lives in Vercel env vars, never exposed to the browser.
"""
import json
import os
from http.server import BaseHTTPRequestHandler

import anthropic


def build_prompt(data: dict) -> str:
    limit = data["limit"]
    scheduled = data["scheduledStarts"]
    needed = max(0, limit - scheduled)
    week_label = data.get("weekLabel", "this week")
    today_name = data.get("todayName", "Sunday")

    roster_lines = "\n".join(
        f"  • {p['name']} ({p['team']}) — {p.get('starts', '?')} starts, "
        f"proj {p.get('projFpts', '?')} FPTS"
        f"{' [' + p['injuryStatus'] + ']' if p.get('injuryStatus') else ''}"
        for p in data["rosterSPs"]
    )
    fa_lines = "\n".join(
        f"  • {p['name']} ({p['team']}) — {p.get('starts', '?')} starts, "
        f"proj {p.get('projFpts', '?')} FPTS, {p.get('percentOwned', '?')}% owned"
        f"{', opp: ' + p['opps'] if p.get('opps') else ''}"
        for p in data["freeAgentSPs"]
    )

    return f"""You are a fantasy baseball starts optimizer. Today is {today_name}, {week_label}.

LEAGUE SETTINGS:
- Weekly starts limit: {limit}
- Starts already locked in from current roster: {scheduled}
- Starts still needed to hit the limit exactly: {needed}

MY ROSTERED STARTING PITCHERS:
{roster_lines}

AVAILABLE FREE AGENTS / STREAMERS (checked by user):
{fa_lines}

TASK:
Generate a complete, actionable recommendation plan. Structure your response with exactly these four markdown sections:

## Adds
For each pitcher to add: name, team, how many starts they have this week, projected FPTS, the opponent(s), and exactly who to drop to make room (if needed). Be explicit: "Add X, drop Y."

## Drops
Any rostered pitchers to drop or stream away from — bad matchup, injury, low projected FPTS. Include timing (e.g. "drop after Tuesday start").

## Day-by-day plan
A Mon–Sun schedule showing every add, drop, and start to target. Goal: hit exactly {limit} starts while maximizing projected FPTS.
Format each line as: **Day**: action (or "No moves needed")

## Watch list
2–3 backup options to monitor in case a planned add gets sniped on waivers or a start gets skipped (rain, injury). One sentence each.

Keep it concrete and reference the FPTS numbers throughout."""


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)
        data = json.loads(body_bytes)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self._respond({"ok": False, "error": "ANTHROPIC_API_KEY not set in environment."})
            return

        try:
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system="You are a sharp, data-driven fantasy baseball analyst. Be specific, reference numbers, and keep recommendations actionable.",
                messages=[{"role": "user", "content": build_prompt(data)}],
            )
            text = "".join(b.text for b in message.content if hasattr(b, "text"))
            self._respond({"ok": True, "analysis": text})
        except Exception as e:
            self._respond({"ok": False, "error": str(e)})

    def _respond(self, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
