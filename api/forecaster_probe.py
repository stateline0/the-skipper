"""
/api/forecaster_probe.py — Diagnostic endpoint for ESPN Forecaster article scraping.

The Fantasy API spike (api/espn_proj.py) confirmed that ESPN's Fantasy API only
exposes full-season projections, never per-day. Per-day FPTS projections only
live on the public Forecaster article:
  https://www.espn.com/fantasy/baseball/story/_/id/31165100/

Before committing to a full scraper, we need to know:
  1. Can we fetch the page from Vercel's Python runtime? (no ESPN auth needed)
  2. Is the projection table server-rendered in HTML or hydrated via JavaScript?
  3. If server-rendered — what's the structure? Count of tables, sample rows,
     column headers.
  4. Is there a JSON hydration blob (__NEXT_DATA__, __INITIAL_STATE__, etc.) we
     can extract instead of parsing DOM tables?

This endpoint fetches the article and returns structural summaries plus raw
HTML samples so we can make an informed decision about the scraping approach.

Usage:
  GET /api/forecaster_probe
"""

import json
import re
import requests
from http.server import BaseHTTPRequestHandler


FORECASTER_URL = (
    "https://www.espn.com/fantasy/baseball/story/_/id/31165100/"
    "fantasy-baseball-forecaster-probable-starting-pitcher-projections-"
    "matchups-daily-weekly-leagues"
)

# Realistic browser-ish UA so ESPN doesn't 403 us for looking like a bot.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def probe() -> dict:
    """Fetch the Forecaster page and report what's in it."""
    try:
        r = requests.get(FORECASTER_URL, headers=HEADERS, timeout=15)
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}: {e}"}

    html = r.text or ""

    # ---- Structural summaries ----------------------------------------------
    # Count tag occurrences (rough; case-insensitive).
    table_count = len(re.findall(r"<table\b", html, re.IGNORECASE))
    tbody_count = len(re.findall(r"<tbody\b", html, re.IGNORECASE))
    thead_count = len(re.findall(r"<thead\b", html, re.IGNORECASE))
    tr_count    = len(re.findall(r"<tr\b",    html, re.IGNORECASE))
    script_count = len(re.findall(r"<script\b", html, re.IGNORECASE))

    # Common hydration-blob markers — if any of these are present, the data
    # might be easier to extract from JSON than from DOM tables.
    has_next_data   = "__NEXT_DATA__"      in html
    has_initial     = "__INITIAL_STATE__"  in html
    has_apollo      = "__APOLLO_STATE__"   in html
    has_espn_hydra  = "espn.fitt"          in html  # ESPN's front-end framework

    # "loading" indicators that suggest JS-hydrated content.
    loading_hits = re.findall(
        r'(loading\.\.\.|"loading"|class="[^"]*loading[^"]*")',
        html,
        re.IGNORECASE,
    )[:5]

    # ---- Pitcher-name heuristic --------------------------------------------
    # If the page has projection tables, our own rostered pitchers should
    # appear. Pick a few names we know are on the roster and see if they're
    # present anywhere in the HTML.
    sample_names = [
        "Joe Ryan",
        "Garrett Crochet",
        "Dylan Cease",
        "Merrill Kelly",
        "Gavin Williams",
    ]
    name_presence = {n: (n in html) for n in sample_names}

    # ---- Extract samples around the first <table> --------------------------
    first_table_sample = None
    m = re.search(r"<table\b", html, re.IGNORECASE)
    if m:
        start = m.start()
        # Take ~3KB of HTML starting at the first <table> so we can eyeball
        # the column headers and a few rows.
        first_table_sample = html[start:start + 3000]

    # ---- Extract any __NEXT_DATA__ JSON blob keys --------------------------
    next_data_keys = None
    if has_next_data:
        nd = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if nd:
            try:
                parsed = json.loads(nd.group(1))
                # Just return top-level keys to keep response size sane.
                next_data_keys = sorted(list(parsed.keys()))
                if "props" in parsed:
                    next_data_keys.append(
                        f"props.{sorted(list(parsed['props'].keys()))}"
                    )
            except Exception as e:
                next_data_keys = [f"parse failed: {type(e).__name__}"]

    # ---- Find any <script type="application/json"> blobs -------------------
    inline_json_blobs = re.findall(
        r'<script[^>]*type="application/json"[^>]*>',
        html,
        re.IGNORECASE,
    )

    # ---- Scan for likely date headers --------------------------------------
    # Forecaster uses headers like "Saturday, April 18" or "Apr 18 - Apr 24".
    date_header_hits = re.findall(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
        r"(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d+",
        html,
    )[:10]

    return {
        "http_status":          r.status_code,
        "final_url":             r.url,
        "content_type":          r.headers.get("Content-Type", ""),
        "content_length_bytes":  len(html),
        "tag_counts": {
            "table":  table_count,
            "thead":  thead_count,
            "tbody":  tbody_count,
            "tr":     tr_count,
            "script": script_count,
        },
        "hydration_markers": {
            "has_next_data":     has_next_data,
            "has_initial_state": has_initial,
            "has_apollo_state":  has_apollo,
            "has_espn_hydration": has_espn_hydra,
        },
        "loading_indicators":   loading_hits,
        "pitcher_name_presence": name_presence,
        "next_data_top_level_keys": next_data_keys,
        "inline_json_script_tags_found": len(inline_json_blobs),
        "date_header_hits": date_header_hits,
        "first_table_sample_3kb": first_table_sample,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = probe()
        ok = "error" not in result
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, **result}).encode())

    def log_message(self, *args):
        pass
