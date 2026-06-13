"""api/injuries.py — ESPN public MLB injuries feed → IL grade + est. return date.

Phase B. The fantasy `mRoster` feed returns an empty `injuryStatus` for rostered
players (KNOWLEDGE.md "Injury detection"), so roster IL pills could only show a
bare "IL" and projections flat-zeroed across the whole matchup window. This
public, no-auth feed (validated via /api/injury_probe) carries, for every IL'd
MLB player, the typed IL grade AND the estimated return date — so we can show a
real grade on every page (roster + FA) and resume projections on the return date
instead of zeroing the rest of the week.

Join key: ESPN's athlete id == ESPN's fantasy player id, so roster/FA players
join to this feed by their existing `id`. The id isn't a clean top-level field
on the feed's athlete object — it lives in the playercard link — so we parse it
out of there (with athlete.id as a fallback if ESPN ever adds it).

Fully degrade-safe: any fetch/parse failure returns {} so callers fall back to
today's bare-IL behavior and the page never breaks.
"""

import json
import re
import requests

from kv import cache_get, cache_set

INJURIES_FEED = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries"
_CACHE_KEY = "cache:injuries-feed:v1"
_TTL_SECONDS = 6 * 3600  # return dates move slowly; 6h keeps it fresh but cheap

# Feed `status` / `details.fantasyStatus.abbreviation` → the pill label the
# frontend's IlPill already renders (IL10/IL15/IL60/DTD/SUSP). Keys are
# lowercased with spaces→hyphens so "60-Day IL", "60-Day-IL" both match.
_GRADE_MAP = {
    "10-day-il": "IL10", "15-day-il": "IL15", "60-day-il": "IL60",
    "day-to-day": "DTD", "suspension": "SUSP", "suspended": "SUSP",
}
_ID_RE = re.compile(r"/id/(\d+)")


def _grade(status, fantasy_abbrev):
    """Map the feed's status strings to a pill label. Falls back to a generic
    "IL" for any unrecognized IL variant, or None for non-injury statuses."""
    for s in (fantasy_abbrev, status):
        if not s:
            continue
        key = str(s).strip().lower().replace(" ", "-")
        if key in _GRADE_MAP:
            return _GRADE_MAP[key]
    if status and "il" in str(status).lower():
        return "IL"
    return None


def _athlete_id(athlete):
    """ESPN athlete id for a feed entry — athlete.id if present, else parsed out
    of the playercard link href (/mlb/player/_/id/<NNN>)."""
    if not isinstance(athlete, dict):
        return None
    aid = athlete.get("id")
    if aid:
        try:
            return int(aid)
        except (TypeError, ValueError):
            pass
    for link in athlete.get("links", []) or []:
        href = link.get("href", "") if isinstance(link, dict) else ""
        m = _ID_RE.search(href or "")
        if m:
            return int(m.group(1))
    return None


def _parse(data) -> dict:
    """{ espn_id(int): {grade, returnDate, detail, name} } from the raw feed.
    Shape: { injuries: [ { injuries: [ {athlete, status, details...} ] } ] }."""
    out = {}
    teams = data.get("injuries", []) if isinstance(data, dict) else []
    for team in teams:
        entries = (team.get("injuries", []) or []) if isinstance(team, dict) else []
        for e in entries:
            if not isinstance(e, dict):
                continue
            aid = _athlete_id(e.get("athlete") or {})
            if not aid:
                continue
            details = e.get("details")
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}
            if not isinstance(details, dict):
                details = {}
            fantasy = details.get("fantasyStatus") or {}
            grade = _grade(e.get("status"), fantasy.get("abbreviation"))
            ret = details.get("returnDate") or None
            if isinstance(ret, str) and len(ret) >= 10:
                ret = ret[:10]  # normalize "2026-07-01T..." → "2026-07-01"
            else:
                ret = None
            # Human-readable injury descriptor for the IL tooltip, e.g.
            # "Left Elbow (Surgery)". Pieces are optional and joined defensively.
            base = " ".join(p for p in (details.get("side"), details.get("type")) if p).strip()
            sub = details.get("detail")
            descr = f"{base} ({sub})" if base and sub else (base or sub or None)
            athlete = e.get("athlete") or {}
            out[aid] = {
                "grade": grade,
                "returnDate": ret,
                "detail": descr,
                "name": athlete.get("displayName") or athlete.get("fullName"),
            }
    return out


def get_injuries() -> dict:
    """All IL'd MLB players keyed by ESPN athlete/fantasy id (int):
    { id: {grade, returnDate, detail, name} }. Cached 6h. Returns {} on any
    failure so callers degrade gracefully to bare-IL behavior."""
    try:
        cached = cache_get(_CACHE_KEY)
        if cached:
            # JSON object keys come back as strings — coerce to int.
            return {int(k): v for k, v in cached.items()}
    except Exception:
        pass

    try:
        r = requests.get(INJURIES_FEED, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"[injuries.py] feed HTTP {r.status_code}")
            return {}
        result = _parse(r.json())
    except Exception as e:
        print(f"[injuries.py] fetch/parse failed: {e}")
        return {}

    print(f"[injuries.py] {len(result)} IL'd players from feed")
    try:
        cache_set(_CACHE_KEY, {str(k): v for k, v in result.items()}, ttl_seconds=_TTL_SECONDS)
    except Exception:
        pass
    return result
