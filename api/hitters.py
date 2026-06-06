"""
/api/hitters.py — Vercel Python serverless function

Hitter roster + baseline (Phase 0–1) projections. Companion to api/espn.py,
which does the same for pitchers.

Flow:
  1. Pull the roster from ESPN (mRoster + mTeam + mSettings) — one fetch.
  2. parse_hitter_scoring() reads the league's hitter scoring from mSettings.
  3. The shared schedule (from mlb.get_starts_for_players) gives each hitter's
     game days for the matchup period — hitters play ~daily, so gameDates are
     just the days their team plays.
  4. load_hitter_stats() supplies season hitting stats (group=hitting).
  5. projection_hitter.get_projected_hitter_fpts() runs the baseline model.

The matchup / park / weather / volume layers (Phases 2–10) are NOT applied
yet, so every game day uses the same season-rate per-game projection. The
payload mirrors the fields the Hitters page consumes.
"""
import json
import os
import sys
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mlb import get_starts_for_players, MATCHUP_PERIODS
from fetcher import get_headers_and_cookies, get_pro_team_map, load_hitter_stats
from kv import cache_get, cache_set
from projection_hitter import (
    parse_hitter_scoring, get_projected_hitter_fpts, strip_accents,
)

# ESPN baseball lineup/eligible slot IDs. Hitters occupy 0–12; pitchers 13–15.
HITTER_SLOTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}


def hitter_slot_label(eligible: set, injured: bool) -> str:
    """Primary position label from eligibleSlots (most-specific first)."""
    if injured:
        return "IL"
    for sid, label in ((0, "C"), (1, "1B"), (2, "2B"), (3, "3B"), (4, "SS")):
        if sid in eligible:
            return label
    if eligible & {5, 8, 9, 10}:   # OF / LF / CF / RF
        return "OF"
    if 11 in eligible:             # DH
        return "DH"
    return "UTIL"


def _date_range(start: str, end: str) -> list:
    out = []
    cur = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    while cur <= last:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _season_line(stat: dict) -> dict | None:
    """Compact season slash + counting line for the Stats tab. None when the
    hitter has no games played (avoids empty rows / divide-by-zero)."""
    if not stat:
        return None

    def f(key):
        try:
            return float(stat.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    games = int(f("gamesPlayed"))
    if games < 1:
        return None
    ab = f("atBats")
    placeholders = (None, "", "-.--", ".---")
    avg = f("avg") if stat.get("avg") not in placeholders else (round(f("hits") / ab, 3) if ab else 0.0)
    obp = f("obp") if stat.get("obp") not in placeholders else 0.0
    slg = f("slg") if stat.get("slg") not in placeholders else 0.0
    return {
        "avg":   round(avg, 3),
        "obp":   round(obp, 3),
        "slg":   round(slg, 3),
        "hr":    int(f("homeRuns")),
        "r":     int(f("runs")),
        "rbi":   int(f("rbi")),
        "sb":    int(f("stolenBases")),
        "games": games,
    }


def get_hitter_data(team_id: int, week: int) -> dict:
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    year_int  = int(year)
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP     = get_pro_team_map(headers, cookies)
    base = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    mp = MATCHUP_PERIODS.get(week, {})
    if not mp:
        return {"ok": True, "rosterHitters": [], "matchupDates": [],
                "message": f"No matchup period {week}"}

    def fmt(d):
        return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")
    week_start = fmt(mp["start"])
    week_end   = fmt(mp["end"])
    period_dates = _date_range(mp["start"], mp["end"])

    # ── Fetch roster (+ settings for scoring) ─────────────────────────
    r = requests.get(
        base,
        params=[
            ("view", "mRoster"), ("view", "mTeam"), ("view", "mSettings"),
            ("_", int(datetime.now().timestamp())),
        ],
        cookies=cookies, headers=headers, timeout=15,
    )
    if r.status_code != 200:
        raise Exception(f"ESPN returned HTTP {r.status_code}")

    data         = r.json()
    teams        = data.get("teams", [])
    my_team      = next((t for t in teams if t.get("id") == team_id), teams[0] if teams else {})
    team_name    = my_team.get("name", "").strip()
    scoring      = parse_hitter_scoring(data)
    roster_entries = my_team.get("roster", {}).get("entries", [])

    # ── Identify hitters on the roster ────────────────────────────────
    hitters_meta = []   # {name, team, pos, bats, eligible}
    team_map = {}
    for entry in roster_entries:
        player = entry.get("playerPoolEntry", {}).get("player", {})
        name   = player.get("fullName", "")
        if not name:
            continue
        eligible = set(player.get("eligibleSlots", []))
        if not (eligible & HITTER_SLOTS):
            continue   # pitcher (or unknown) — skip
        injured = player.get("injured", False)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        bats = (player.get("batSide") or {}).get("code", "") if isinstance(player.get("batSide"), dict) else ""
        hitters_meta.append({
            "name": name, "team": team_abbrev,
            "pos": hitter_slot_label(eligible, injured), "bats": bats,
        })
        if team_abbrev:
            team_map[name] = team_abbrev

    # ── Shared schedule (we only need the schedule, not pitcher starts) ─
    _, schedule = get_starts_for_players(
        [h["name"] for h in hitters_meta], week, team_map=team_map
    )

    # ── Season hitting stats (cached) ─────────────────────────────────
    hit = load_hitter_stats(year_int)
    hitting_current  = hit["hitting_current"]
    hitting_previous = hit["hitting_previous"]

    # ── Game days per hitter (days their team plays in the period) ────
    for h in hitters_meta:
        team = h["team"]
        h["gameDates"] = [d for d in period_dates if team and team in schedule.get(d, {})]

    # ── Baseline projection ───────────────────────────────────────────
    proj, _details = get_projected_hitter_fpts(
        [{"name": h["name"], "team": h["team"], "gameDates": h["gameDates"]} for h in hitters_meta],
        scoring=scoring,
        stat_current=hitting_current,
        stat_previous=hitting_previous,
        season=year_int, period=week,
    )

    # ── Assemble output ───────────────────────────────────────────────
    roster_hitters = []
    for h in hitters_meta:
        name = h["name"]
        p = proj.get(name, {})
        per_game = p.get("projPerGame", 0.0)
        # Per-day cells. Phase 1 is flat (per_game every game); the opponent/
        # home come from the shared schedule so the grid shows real matchups.
        days = []
        for d in h["gameDates"]:
            game = schedule.get(d, {}).get(h["team"], {})
            days.append({
                "date": d,
                "opp":  game.get("opponent", ""),
                "home": game.get("is_home", True),
                "proj": round(per_game, 1),
            })
        roster_hitters.append({
            "name":        name,
            "team":        h["team"],
            "pos":         h["pos"],
            "bats":        h["bats"],
            "projFpts":    p.get("projFpts", 0.0),
            "projPerGame": round(per_game, 1),
            "blendWeight": p.get("blendWeight", 0.0),
            "games":       p.get("games", len(h["gameDates"])),
            "seasonStats": _season_line(hitting_current.get(strip_accents(name), {})),
            "days":        days,
        })

    # IL to the bottom, then by weekly projection.
    roster_hitters.sort(key=lambda x: (x["pos"] == "IL", -x["projFpts"]))

    return {
        "ok":            True,
        "teamName":      team_name,
        "weekStart":     week_start,
        "weekEnd":       week_end,
        "matchupDates":  [mp["start"], mp["end"]],
        "schedule":      schedule,
        "rosterHitters": roster_hitters,
        "scoringStats":  sorted(scoring.keys()),
        "computedAt":    datetime.now(timezone.utc).isoformat(),
    }


# ── Caching (mirrors the espn.py warm-serve pattern, lighter) ──────────
HITTER_CACHE_TTL = 1800  # 30 min


def _cache_key(team_id: int, week: int) -> str:
    year = os.environ.get("ESPN_SEASON", "2026")
    return f"cache:hitterdata:{year}:{team_id}:{week}"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs      = parse_qs(urlparse(self.path).query)
        env_tid = os.environ.get("ESPN_TEAM_ID", "")
        team_id = int(env_tid) if env_tid else int(qs.get("teamId", ["1"])[0])
        week    = int(qs.get("week", ["1"])[0])
        fresh   = qs.get("fresh", ["0"])[0] in ("1", "true")

        try:
            payload = None
            if not fresh:
                try:
                    cached = cache_get(_cache_key(team_id, week))
                    if cached and cached.get("ok"):
                        cached["servedFrom"] = "cache"
                        payload = cached
                except Exception:
                    pass
            if payload is None:
                payload = get_hitter_data(team_id, week)
                payload["servedFrom"] = "live"
                try:
                    cache_set(_cache_key(team_id, week), payload, ttl_seconds=HITTER_CACHE_TTL)
                except Exception:
                    pass
        except Exception as e:
            payload = {"ok": False, "error": str(e)}

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
