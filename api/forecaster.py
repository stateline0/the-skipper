"""
/api/forecaster.py — Scrape ESPN's Fantasy Forecaster probable-pitcher projections.

Background
----------
ESPN publishes daily per-pitcher FPTS projections on a public article:
  https://www.espn.com/fantasy/baseball/story/_/id/31165100/

The article contains ONE HTML table with:
  - One <tr> per MLB team (30 teams, interleaved with empty spacer rows)
  - Each cell holds 10 <br>-separated values, one per date in a rolling 10-day
    window starting "today" (ESPN time).
  - Columns: team-logo, date, opp, pitcher, throws-hand, FPTS

Example row (ARI, 2026-04-18 fetch):
    DATE:    Sat 4/18  Sun 4/19  Mon 4/20  Tue 4/21  Wed 4/22  ...
    OPP:     TOR       TOR       OFF       CWS       CWS       ...
    PITCHER: Gallen    Nelson    —         Merrill Kelly  E. Rodriguez ...
    THROWS:  R         R         —         R         L         ...
    FPTS:    8.4       8.3       —         9.7       7.3       ...

Each pitcher <a> tag links to espn.go.com/mlb/player/_/id/{player_id}/{slug},
so we can recover the numeric player ID for matching against our roster IDs.

Diagnostic endpoint
-------------------
GET /api/forecaster
  → {
      "ok": true,
      "fetched_at": "2026-04-18T…Z",
      "date_range": ["2026-04-18", "2026-04-27"],
      "entries": [
          {
              "date": "2026-04-18",
              "team": "ARI",
              "opp": "TOR",
              "opp_is_home": true,
              "player_id": 39910,
              "pitcher": "Zac Gallen",
              "throws": "R",
              "fpts": 8.4,
              "is_placeholder": false
          },
          …
      ],
      "entry_count": 123
    }

The fetched_at timestamp is included so downstream consumers can decide whether
to trust the snapshot or re-fetch. No KV writes happen in this endpoint — that
comes in a later PR (daily cron for locking).
"""

import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta, timezone
from http.server import BaseHTTPRequestHandler


FORECASTER_URL = (
    "https://www.espn.com/fantasy/baseball/story/_/id/31165100/"
    "fantasy-baseball-forecaster-probable-starting-pitcher-projections-"
    "matchups-daily-weekly-leagues"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ESPN appears to use exactly 1.0 as a placeholder for far-future starts they
# haven't firmed up yet (observed on dates ~7+ days out). We flag these with
# is_placeholder=True so downstream can exclude them from accuracy comparisons.
#
# MUST be an exact-value check, not a threshold: Coors Field pitchers often
# legitimately project as negative (e.g. a rough matchup might come in at
# -3.2 FPTS). A `<= 1.0` comparison would wrongly flag those as placeholders.
PLACEHOLDER_FPTS_VALUE = 1.0

# Maps ESPN team-logo filenames (e.g. "ari.png") to their team abbreviation.
# ESPN uses a few non-standard slugs we have to override.
LOGO_TO_TEAM_OVERRIDES = {
    "ath": "OAK",   # Athletics — logo file uses "ath"
    "was": "WSH",   # Nationals — logo file is "was.png" but everywhere else in
                    # ESPN (opp column, scoreboard) uses "WSH". Normalize here
                    # so team/opp join keys stay consistent downstream.
    "wsh": "WSH",
    "sf":  "SF",
    "sd":  "SD",
    "tb":  "TB",
    "cws": "CWS",
    "chw": "CWS",
    "az":  "ARI",
    "kc":  "KC",
}


def _team_from_logo(img_src: str) -> str:
    """Extract team abbreviation from logo URL like '/mlb/500/ari.png'."""
    if not img_src:
        return ""
    m = re.search(r"/mlb/\d+/([a-z]+)\.png", img_src, re.IGNORECASE)
    if not m:
        return ""
    slug = m.group(1).lower()
    return LOGO_TO_TEAM_OVERRIDES.get(slug, slug.upper())


def _split_br(cell) -> list:
    """Split a <td>'s children into a list of per-date strings, using <br> as
    delimiter. Empty slots (for OFF days) become empty strings so the list
    aligns by index with the date column."""
    if cell is None:
        return []
    # Walk the cell's descendants; <br> resets the current bucket.
    # Using get_text with a special separator is unreliable because some
    # cells have nested <div> wrappers — we'd rather iterate descendants
    # of whichever container holds the <br> tags.
    #
    # Strategy: find the deepest container that has <br> tags as direct
    # children, and split on those.
    container = cell
    # If the cell has exactly one child element and that child holds the <br>s,
    # dive into it. This handles <td><div>…<br>…</div></td> wrappers.
    only_child = None
    for child in cell.children:
        if getattr(child, "name", None):
            if only_child is None:
                only_child = child
            else:
                only_child = None
                break
    if only_child is not None and only_child.find("br") is not None:
        container = only_child

    # Now walk container's DIRECT children, accumulating text until each <br>.
    buckets = [""]
    for node in container.children:
        name = getattr(node, "name", None)
        if name == "br":
            buckets.append("")
        else:
            # If it's a tag, take its text. If it's a NavigableString, use str.
            if name is None:
                buckets[-1] += str(node)
            else:
                buckets[-1] += node.get_text(strip=False)
    return [b.strip() for b in buckets]


def _extract_player_id(cell_tag) -> int | None:
    """Pull the numeric ESPN player ID out of an <a> inside the pitcher cell."""
    if cell_tag is None:
        return None
    a = cell_tag.find("a", href=True)
    if not a:
        return None
    m = re.search(r"/player/_/id/(\d+)/", a["href"])
    return int(m.group(1)) if m else None


def _split_pitcher_cell(cell) -> list:
    """For the pitcher column, split into a list of (name, player_id) tuples
    per date. Pitchers are wrapped in <a> tags; OFF days have no <a> in that
    <br>-delimited slot."""
    if cell is None:
        return []
    container = cell
    only_child = None
    for child in cell.children:
        if getattr(child, "name", None):
            if only_child is None:
                only_child = child
            else:
                only_child = None
                break
    if only_child is not None and only_child.find("br") is not None:
        container = only_child

    buckets: list[tuple[str, int | None]] = [("", None)]
    for node in container.children:
        name = getattr(node, "name", None)
        if name == "br":
            buckets.append(("", None))
        elif name == "a":
            text = node.get_text(strip=True)
            href = node.get("href", "") or ""
            m = re.search(r"/player/_/id/(\d+)/", href)
            pid = int(m.group(1)) if m else None
            # Merge into current bucket (append text, overwrite pid)
            cur_text, cur_pid = buckets[-1]
            buckets[-1] = ((cur_text + text).strip(), pid or cur_pid)
        else:
            # Non-<a> content in a pitcher slot — usually whitespace; ignore.
            pass
    return buckets


def _parse_date_token(token: str, year: int) -> str | None:
    """Turn 'Sat, 4/18' → '2026-04-18' (ISO date)."""
    m = re.search(r"(\d{1,2})/(\d{1,2})", token)
    if not m:
        return None
    mo, dy = int(m.group(1)), int(m.group(2))
    try:
        return date(year, mo, dy).isoformat()
    except ValueError:
        return None


def parse_forecaster_html(html: str, year: int | None = None) -> dict:
    """
    Pure parsing function — takes HTML string, returns list of entries.

    Output entry shape:
      {
        "date": "2026-04-18",
        "team": "ARI",
        "opp":  "TOR",
        "opp_is_home": True,     # False if opp was prefixed with "@"
        "player_id": 39910,
        "pitcher": "Zac Gallen",
        "throws": "R",
        "fpts": 8.4,
        "is_placeholder": False
      }
    """
    if year is None:
        # Use current UTC year as default; callers can override for tests.
        year = datetime.now(timezone.utc).year

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="inline-table")
    if table is None:
        return {"entries": [], "date_range": None}

    entries: list[dict] = []
    all_dates_seen: set[str] = set()

    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue

        logo_td, date_td, opp_td, pitcher_td, throws_td, fpts_td = tds[:6]

        img = logo_td.find("img")
        team = _team_from_logo(img.get("src", "")) if img else ""
        if not team:
            continue  # spacer row

        date_tokens    = _split_br(date_td)
        opp_tokens     = _split_br(opp_td)
        pitcher_tokens = _split_pitcher_cell(pitcher_td)
        throws_tokens  = _split_br(throws_td)
        fpts_tokens    = _split_br(fpts_td)

        # Align all columns by index. If cells have different counts (ESPN
        # sometimes omits trailing blanks), iterate up to max length and
        # treat missing as empty.
        n = max(
            len(date_tokens),
            len(opp_tokens),
            len(pitcher_tokens),
            len(throws_tokens),
            len(fpts_tokens),
        )

        def _get(seq, i, default=""):
            return seq[i] if i < len(seq) else default

        for i in range(n):
            date_tok    = _get(date_tokens, i)
            opp_tok     = _get(opp_tokens, i)
            pitcher_tok = _get(pitcher_tokens, i, ("", None))
            throws_tok  = _get(throws_tokens, i)
            fpts_tok    = _get(fpts_tokens, i)

            iso_date = _parse_date_token(date_tok, year)
            if iso_date is None:
                continue

            all_dates_seen.add(iso_date)

            pitcher_name, player_id = pitcher_tok
            if not pitcher_name or opp_tok.upper() == "OFF":
                # OFF day or no pitcher listed — skip; we only want real starts
                continue

            # Home/away detection — "@XXX" means away.
            opp_is_home = not opp_tok.startswith("@")
            opp_clean   = opp_tok.lstrip("@").strip()

            # FPTS numeric conversion
            try:
                fpts = float(fpts_tok)
            except (TypeError, ValueError):
                continue  # no FPTS → skip silently

            entries.append({
                "date":           iso_date,
                "team":           team,
                "opp":            opp_clean,
                "opp_is_home":    opp_is_home,
                "player_id":      player_id,
                "pitcher":        pitcher_name,
                "throws":         throws_tok or None,
                "fpts":           fpts,
                "is_placeholder": fpts == PLACEHOLDER_FPTS_VALUE,
            })

    date_range = None
    if all_dates_seen:
        date_range = [min(all_dates_seen), max(all_dates_seen)]

    return {"entries": entries, "date_range": date_range}


def fetch_forecaster() -> dict:
    """Fetch the Forecaster page and return parsed entries plus metadata."""
    try:
        r = requests.get(FORECASTER_URL, headers=HEADERS, timeout=15)
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}"}

    parsed = parse_forecaster_html(r.text)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "fetched_at":  fetched_at,
        "date_range":  parsed["date_range"],
        "entries":     parsed["entries"],
        "entry_count": len(parsed["entries"]),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = fetch_forecaster()
        ok = "error" not in result
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, **result}).encode())

    def log_message(self, *args):
        pass
