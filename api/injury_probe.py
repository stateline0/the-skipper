"""
/api/injury_probe.py — Diagnostic endpoint for IL "Est Return" date sourcing.

Phase A shipped IL-awareness (typed pill + zero-while-IL). Phase B wants the
ESPN "Est Return" date the fantasy app shows, so projections can resume at the
right time instead of staying flat-zero across the whole window. That date is
NOT in any feed The Skipper currently parses — this endpoint probes the three
candidate sources (ranked cheapest-first in BACKLOG) and reports which, if any,
actually carries a return date, plus the raw field path so the wiring is exact.

Candidates:
  1. kona `player` object — the FA call we already make. Cheapest if present.
  2. ESPN public MLB injuries feed — site.api.espn.com/.../mlb/injuries (no auth).
  3. ESPN athlete overview — site.web.api.espn.com/.../athletes/{id}/overview.
     ESPN fantasy player id == ESPN athlete id, so the join is free.

The dev container can't reach the site.* hosts (egress allowlist), so run this
in production. It surfaces only structural/injury fields — never auth cookies.

Usage:
  GET /api/injury_probe                 → run all three candidates
  GET /api/injury_probe?source=kona     → just the kona dump
  GET /api/injury_probe?athleteId=123   → force candidate 3 against one id
"""

import json
import os
import re
import traceback
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from fetcher import get_headers_and_cookies

# Field names that would plausibly carry a return date / injury detail. Used to
# pull the interesting keys out of otherwise-large objects so the response is
# readable rather than a full dump.
RETURN_KEY_RE = re.compile(r"return|estimat|inj|date|status|detail|timeline|out|dl",
                           re.IGNORECASE)
# A value that looks like an ISO date or a "Jun 20" style string — a positive
# signal that a field actually holds a return date.
DATE_VALUE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}\b",
    re.IGNORECASE,
)

INJURIES_FEED = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"
ATHLETE_OVERVIEW = (
    "https://site.web.api.espn.com/apis/common/v3/sports/baseball/mlb/"
    "athletes/{id}/overview"
)


def _trunc(v, n=240):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + "…"


def _interesting_fields(obj) -> dict:
    """Top-level keys of `obj` whose NAME looks injury/return-related, with
    truncated values, plus any key whose VALUE looks like a date string.
    Returns {} for any non-dict input (ESPN shapes vary) so callers can't
    crash on an unexpected list/scalar."""
    if not isinstance(obj, dict):
        return {}
    out = {}
    for k, v in obj.items():
        if isinstance(v, (dict, list)):
            blob = json.dumps(v, default=str)
            if RETURN_KEY_RE.search(k) or DATE_VALUE_RE.search(blob):
                out[k] = _trunc(v)
        else:
            if RETURN_KEY_RE.search(k) or (isinstance(v, str) and DATE_VALUE_RE.search(v)):
                out[k] = _trunc(v)
    return out


def _has_date(fields: dict) -> bool:
    return any(DATE_VALUE_RE.search(str(v)) for v in fields.values())


def probe_kona() -> dict:
    """Re-run the FA kona call (same auth + filter as espn.py) and, for each
    IL'd free agent, dump the injury-relevant slice of its raw `player` dict."""
    league_id = os.environ.get("ESPN_LEAGUE_ID")
    if not league_id:
        return {"source": "kona", "error": "ESPN_LEAGUE_ID not set"}
    year = os.environ.get("ESPN_SEASON", "2026")
    try:
        headers, cookies = get_headers_and_cookies()
        base = (
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
            f"/seasons/{year}/segments/0/leagues/{league_id}"
        )
        # Pull a broad FA slate (all slots) so we catch IL'd hitters and pitchers.
        xff = json.dumps({"players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "limit": 300,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }})
        r = requests.get(
            base,
            params=[("view", "kona_player_info"), ("scoringPeriodId", 1)],
            cookies=cookies, headers={**headers, "x-fantasy-filter": xff},
            timeout=15,
        )
        if r.status_code != 200:
            return {"source": "kona", "error": f"HTTP {r.status_code}"}

        players = r.json().get("players", [])
        il_players = []
        sample_keys = None
        for p in players:
            player = p.get("player", {}) if isinstance(p, dict) else {}
            status = player.get("injuryStatus", "")
            if status in ("", "ACTIVE", "NORMAL"):
                continue
            if sample_keys is None:
                sample_keys = sorted(player.keys())
            il_players.append({
                "id": player.get("id"),
                "fullName": player.get("fullName"),
                "injuryStatus": status,
                "interesting_fields": _interesting_fields(player),
                # ESPN sometimes nests a per-player injuries array with detail text.
                "injuries": _trunc(player.get("injuries")) if player.get("injuries") else None,
            })
            if len(il_players) >= 8:
                break

        has_date = any(_has_date(p["interesting_fields"]) for p in il_players)
        return {
            "source": "kona",
            "total_fa_returned": len(players),
            "il_count_shown": len(il_players),
            "player_top_level_keys": sample_keys,
            "carries_return_date": has_date,
            "il_players": il_players,
        }
    except Exception as e:
        return {"source": "kona", "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-1500:]}


def probe_injuries_feed() -> dict:
    """ESPN's public MLB injuries feed (no auth). The NFL variant nests a
    `details.returnDate`; this checks whether MLB's does too."""
    try:
        r = requests.get(INJURIES_FEED, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return {"source": "injuries_feed", "error": f"HTTP {r.status_code}",
                    "body_head": (r.text or "")[:400]}
        try:
            data = r.json()
        except Exception as e:
            return {"source": "injuries_feed", "error": f"non-JSON: {e}",
                    "body_head": (r.text or "")[:400]}

        # Shape: { injuries: [ { team..., injuries: [ {athlete, status, details...} ] } ] }
        teams = data.get("injuries", []) if isinstance(data, dict) else []
        sample = []
        found_date = False
        for team in teams:
            entries = (team.get("injuries", []) or []) if isinstance(team, dict) else []
            for entry in entries:
                fields = _interesting_fields(entry)
                athlete = (entry.get("athlete") or {}) if isinstance(entry, dict) else {}
                sample.append({
                    "athlete": athlete.get("displayName") or athlete.get("fullName"),
                    "athleteId": athlete.get("id"),
                    "status": entry.get("status") if isinstance(entry, dict) else None,
                    "entry_keys": sorted(entry.keys()) if isinstance(entry, dict) else None,
                    "interesting_fields": fields,
                })
                if _has_date(fields):
                    found_date = True
                if len(sample) >= 8:
                    break
            if len(sample) >= 8:
                break

        return {
            "source": "injuries_feed",
            "url": INJURIES_FEED,
            "team_blocks": len(teams),
            "carries_return_date": found_date,
            "sample_entries": sample,
        }
    except Exception as e:
        return {"source": "injuries_feed", "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-1500:]}


def probe_athlete_overview(athlete_id: str) -> dict:
    """ESPN athlete overview/card for a single id — last-resort source. Dumps
    any injury/return block it carries."""
    url = ATHLETE_OVERVIEW.format(id=athlete_id)
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return {"source": "athlete_overview", "athleteId": athlete_id,
                    "error": f"HTTP {r.status_code}"}
        try:
            data = r.json()
        except Exception as e:
            return {"source": "athlete_overview", "athleteId": athlete_id,
                    "error": f"non-JSON: {e}"}
        # The overview is a big nested doc; surface only the injury-ish slices.
        fields = _interesting_fields(data)
        return {
            "source": "athlete_overview",
            "athleteId": athlete_id,
            "url": url,
            "top_level_keys": sorted(data.keys()) if isinstance(data, dict) else None,
            "carries_return_date": _has_date(fields),
            "interesting_fields": fields,
        }
    except Exception as e:
        return {"source": "athlete_overview", "athleteId": athlete_id,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-1500:]}


def probe(source: str | None, athlete_id: str | None) -> dict:
    if source == "kona":
        return {"results": [probe_kona()]}
    if source == "injuries_feed":
        return {"results": [probe_injuries_feed()]}
    if source == "athlete_overview" or athlete_id:
        if not athlete_id:
            return {"error": "athlete_overview needs ?athleteId=N"}
        return {"results": [probe_athlete_overview(athlete_id)]}

    # Default: run all three. Candidate 3 auto-targets the first IL'd FA the
    # kona dump surfaced, so a single call exercises the full chain.
    kona = probe_kona()
    feed = probe_injuries_feed()
    results = [kona, feed]
    auto_id = None
    for p in kona.get("il_players", []) or []:
        if p.get("id"):
            auto_id = str(p["id"])
            break
    if auto_id:
        results.append(probe_athlete_overview(auto_id))

    winners = [r["source"] for r in results if r.get("carries_return_date")]
    return {
        "carries_return_date_sources": winners,
        "summary": {
            r["source"]: ("ERROR: " + r["error"]) if "error" in r
            else ("HAS_RETURN_DATE" if r.get("carries_return_date") else "no_date_field")
            for r in results
        },
        "results": results,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs = parse_qs(urlparse(self.path).query)
            source = (qs.get("source") or [None])[0]
            athlete_id = (qs.get("athleteId") or [None])[0]
            result = probe(source, athlete_id)
        except Exception as e:
            # A diagnostic endpoint must never hand back an opaque platform 500 —
            # surface the failure as JSON so it's actually diagnosable.
            result = {"error": f"{type(e).__name__}: {e}",
                      "traceback": traceback.format_exc()[-2000:]}
        ok = "error" not in result
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, **result}).encode())

    def log_message(self, *args):
        pass
