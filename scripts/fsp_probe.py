#!/usr/bin/env python3
"""
scripts/fsp_probe.py — one-off reachability + structure probe for FantasySP.

NOT a committed feature. Run it from an unrestricted network (your laptop) to
answer the only questions that gate a daily FSP-value ingest:

  1. Is the page reachable, or is it behind Cloudflare / a bot challenge?
  2. Is the data in an HTML <table>, a plain list, or embedded JSON?
  3. Is it public, or behind a login / paywall?
  4. Can we actually extract (player name, numeric value) pairs?

Usage:
    pip install requests beautifulsoup4      # already in requirements.txt
    python scripts/fsp_probe.py              # probes the default chart pages
    python scripts/fsp_probe.py <url> ...    # probe specific URLs

It prints a compact report and dumps the raw HTML of each page to
/tmp/fsp_<slug>.html so you can eyeball the markup. Paste the report back and
I'll turn it into the real fetcher.
"""
import sys
import re
import json
import requests
from bs4 import BeautifulSoup

DEFAULT_URLS = [
    "https://www.fantasysp.com/trade-value-chart/mlb",
    "https://www.fantasysp.com/trade-value-chart/mlb/SP",
    "https://www.fantasysp.com/trade-value-chart/mlb/RP",
    "https://www.fantasysp.com/mlb_trade_analyzer/",
    "https://www.fantasysp.com/robots.txt",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Signals that the page is a bot-wall / login-wall rather than real content.
WALL_SIGNALS = [
    "just a moment", "cloudflare", "cf-chl", "captcha", "enable javascript",
    "attention required", "access denied", "sign in", "log in to view",
    "create a free account", "subscribe to view",
]


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:60]


def probe(url: str) -> None:
    print(f"\n{'='*70}\n{url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
    except Exception as e:
        print(f"  REQUEST FAILED: {e}")
        return

    body = r.text or ""
    low = body.lower()
    print(f"  HTTP {r.status_code} | {len(body):,} bytes | "
          f"{r.headers.get('content-type','?')} | "
          f"server={r.headers.get('server','?')}")

    out = f"/tmp/fsp_{slug(url)}.html"
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"  raw saved -> {out}")
    except Exception as e:
        print(f"  (could not save raw: {e})")

    walls = [s for s in WALL_SIGNALS if s in low]
    if walls:
        print(f"  ⚠ wall/login signals present: {walls}")

    if "robots.txt" in url:
        print("  --- robots.txt (first 25 lines) ---")
        for line in body.splitlines()[:25]:
            print(f"    {line}")
        return

    soup = BeautifulSoup(body, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else "(none)"
    print(f"  <title>: {title}")

    # Embedded JSON? (Next/Nuxt/inline state blobs)
    json_blobs = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                            body, re.DOTALL)
    print(f"  embedded JSON <script> blocks: {len(json_blobs)}")
    for blob in json_blobs[:3]:
        try:
            data = json.loads(blob)
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"    JSON keys/type: {keys}")
        except Exception:
            pass

    # Tables?
    tables = soup.find_all("table")
    print(f"  <table> elements: {len(tables)}")
    for i, t in enumerate(tables[:3]):
        rows = t.find_all("tr")
        head = [th.get_text(strip=True) for th in t.find_all("th")][:8]
        print(f"    table[{i}]: {len(rows)} rows | headers={head}")
        # show first few data rows
        for tr in rows[1:4]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c][:6]
            if cells:
                print(f"      row: {cells}")

    # Heuristic: any "Name ..... number" pairs anywhere (covers non-table layouts)
    pairs = re.findall(r"([A-Z][a-zA-Z.'\-]+ [A-Z][a-zA-Z.'\-]+)\D{0,40}?(\d{1,4}\.?\d?)",
                       soup.get_text(" ", strip=True))
    if pairs:
        print(f"  name~number candidates (first 5): {pairs[:5]}")


def main() -> None:
    urls = sys.argv[1:] or DEFAULT_URLS
    print("FantasySP probe — reachability + structure")
    for u in urls:
        probe(u)
    print(f"\n{'='*70}\nDone. Paste this output (and peek at the /tmp/fsp_*.html dumps).")


if __name__ == "__main__":
    main()
