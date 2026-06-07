"""
/api/forecaster_probe.py — Diagnostic endpoint for ESPN Forecaster article scraping.

Per-day FPTS projections only live on the public Forecaster article:
  https://www.espn.com/fantasy/baseball/story/_/id/31165100/

Background: the scraper broke as an *external* change sometime after mid-May
2026 — no code changed in that window. A structural probe (the original
single-fetch version of this file) showed the break is NOT a 403 and NOT a
JS-hydration switch: the server returns **HTTP 202 with a ~2KB script-only
body and no projection table** — the signature of an Akamai-style bot-challenge
interstitial served in place of the article.

The serverless runtime has no headless browser (requests + bs4 only), so we
can't execute a JS challenge. The remaining levers are all header/cookie based:
a complete & consistent browser fingerprint, a cookie warm-up session, or a UA
ESPN whitelists (Googlebot is often served full HTML for SEO).

Rather than guess one strategy per deploy, this endpoint runs the whole matrix
server-side — where ESPN is actually reachable — and reports, per strategy,
whether it got the real table back. The winning strategy then gets locked into
api/forecaster.py.

Usage:
  GET /api/forecaster_probe            → run all strategies
  GET /api/forecaster_probe?strategy=warmup_session   → run just one
"""

import json
import re
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


FORECASTER_URL = (
    "https://www.espn.com/fantasy/baseball/story/_/id/31165100/"
    "fantasy-baseball-forecaster-probable-starting-pitcher-projections-"
    "matchups-daily-weekly-leagues"
)

ESPN_HOME = "https://www.espn.com/"

# Pitchers we expect to appear if we got the real article back. Used as a
# content-level "did we actually get the page" check, independent of HTTP
# status (the bot wall returns 202, so status alone is misleading).
SAMPLE_NAMES = [
    "Skubal", "Crochet", "Wheeler", "Skenes", "Gallen",
    "Ryan", "Cease", "Kelly", "Williams", "Gilbert",
]

# A modern, fully-consistent Chrome-on-Windows fingerprint. The sec-ch-ua
# brand/version, platform, and UA string all agree — bot managers cross-check
# these against each other.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_CHROME_FULL_HEADERS = {
    "User-Agent": _CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # Request only encodings `requests` can decode without extra deps (no br).
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# What the legacy (broken) scraper sent — kept as the baseline control.
_LEGACY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_GOOGLEBOT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

_SAFARI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def _summarize_response(r: requests.Response) -> dict:
    """Boil a fetched response down to the few signals that tell us whether we
    got the real article or a bot-wall stub."""
    html = r.text or ""
    table_count = len(re.findall(r"<table\b", html, re.IGNORECASE))
    has_inline_table = "inline-table" in html
    names_present = [n for n in SAMPLE_NAMES if n in html]
    # The real article got through iff there's a table AND known pitchers.
    looks_real = table_count > 0 and len(names_present) >= 2
    return {
        "http_status": r.status_code,
        "final_url": r.url,
        "redirected": r.url != FORECASTER_URL,
        "content_type": r.headers.get("Content-Type", ""),
        "content_length_bytes": len(html),
        "server": r.headers.get("Server", ""),
        # Akamai/Incapsula leave fingerprints in these headers/cookies.
        "set_cookie_names": sorted({
            c.split("=", 1)[0].strip()
            for c in r.headers.get("Set-Cookie", "").split(",")
            if "=" in c
        }),
        "table_count": table_count,
        "has_inline_table_class": has_inline_table,
        "sample_names_found": names_present,
        "looks_like_real_article": looks_real,
        # First chunk of body so we can eyeball the interstitial markup when a
        # strategy fails (Akamai "Reference #", _abck/ak_bmsc, <noscript>, etc.).
        "body_head": html[:900],
    }


def _strat_simple(name: str, headers: dict) -> dict:
    """One-shot GET with a fixed header set."""
    try:
        r = requests.get(FORECASTER_URL, headers=headers, timeout=20)
    except Exception as e:
        return {"strategy": name, "error": f"{type(e).__name__}: {e}"}
    return {"strategy": name, **_summarize_response(r)}


def _strat_warmup_session() -> dict:
    """Warm a session on espn.com (to collect any bot-clearance cookies like
    _abck / ak_bmsc / bm_sv) then request the article with a same-site Referer.
    Some Akamai deployments hand a clearance cookie on the first benign GET."""
    name = "warmup_session"
    try:
        s = requests.Session()
        s.headers.update(_CHROME_FULL_HEADERS)
        home = s.get(ESPN_HOME, timeout=20)
        cookies_after_home = sorted(s.cookies.keys())
        # Now the article, posing as a same-site navigation from the homepage.
        article_headers = {
            "Referer": ESPN_HOME,
            "Sec-Fetch-Site": "same-origin",
        }
        r = s.get(FORECASTER_URL, headers=article_headers, timeout=20)
        out = {"strategy": name, **_summarize_response(r)}
        out["home_status"] = home.status_code
        out["cookies_after_home"] = cookies_after_home
        out["cookies_after_article"] = sorted(s.cookies.keys())
        return out
    except Exception as e:
        return {"strategy": name, "error": f"{type(e).__name__}: {e}"}


STRATEGIES = {
    "legacy_baseline":   lambda: _strat_simple("legacy_baseline", _LEGACY_HEADERS),
    "chrome_full":       lambda: _strat_simple("chrome_full", _CHROME_FULL_HEADERS),
    "safari":            lambda: _strat_simple("safari", _SAFARI_HEADERS),
    "googlebot":         lambda: _strat_simple("googlebot", _GOOGLEBOT_HEADERS),
    "warmup_session":    _strat_warmup_session,
}


def probe(only: str | None = None) -> dict:
    """Run the strategy matrix (or a single named strategy) and report which
    ones got the real article back."""
    if only:
        fn = STRATEGIES.get(only)
        if fn is None:
            return {"error": f"unknown strategy '{only}'; "
                             f"valid: {sorted(STRATEGIES)}"}
        results = [fn()]
    else:
        results = [STRATEGIES[k]() for k in STRATEGIES]

    winners = [r["strategy"] for r in results if r.get("looks_like_real_article")]
    return {
        "url": FORECASTER_URL,
        "winning_strategies": winners,
        "summary": {
            r["strategy"]: (
                "ERROR" if "error" in r
                else ("REAL_ARTICLE" if r.get("looks_like_real_article")
                      else f"STUB(status={r.get('http_status')},"
                           f"bytes={r.get('content_length_bytes')},"
                           f"tables={r.get('table_count')})")
            )
            for r in results
        },
        "results": results,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        only = (qs.get("strategy") or [None])[0]
        result = probe(only)
        ok = "error" not in result
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, **result}).encode())

    def log_message(self, *args):
        pass
