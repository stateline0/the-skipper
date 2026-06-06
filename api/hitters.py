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
    DEFAULT_HITTER_SCORING, _resolve_points,
)

# ESPN baseball lineup/eligible slot IDs. Hitters occupy 0–12; pitchers 13–15.
HITTER_SLOTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

# Label + display order keyed by the player's current lineupSlotId, to match
# ESPN's roster ordering exactly: C, 1B, 2B, 3B, SS, MI(2B/SS), CI(1B/3B), OF,
# UTIL, then bench, then IL.
LINEUP_LABEL = {
    0: "C", 1: "1B", 2: "2B", 3: "3B", 4: "SS", 5: "OF",
    6: "2B/SS", 7: "1B/3B", 8: "OF", 9: "OF", 10: "OF",
    11: "DH", 12: "UTIL", 16: "BN", 17: "IL",
}
LINEUP_RANK = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 6: 5, 7: 6, 5: 7,
    8: 8, 9: 9, 10: 10, 11: 11, 12: 12, 16: 90, 17: 99,
}


def _eligible_label(eligible: set) -> str:
    """Most-specific position from eligibleSlots (for bench/unknown lineup slots)."""
    for sid, label in ((0, "C"), (1, "1B"), (2, "2B"), (3, "3B"), (4, "SS")):
        if sid in eligible:
            return label
    if eligible & {5, 8, 9, 10}:
        return "OF"
    if 11 in eligible:
        return "DH"
    return "UTIL"


def hitter_slot(slot_id: int, eligible: set, injured: bool):
    """Return (label, sort_rank) for a hitter from their lineupSlotId.

    IL sinks to the bottom; bench hitters sort after starters but keep their
    eligible position as the label (ESPN shows the position, not "BN", there).
    """
    if injured or slot_id == 17:
        return "IL", 99
    if slot_id == 16:                       # bench
        return _eligible_label(eligible), 90
    label = LINEUP_LABEL.get(slot_id)
    if label:
        return label, LINEUP_RANK.get(slot_id, 80)
    return _eligible_label(eligible), 80


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
    roster_entries = my_team.get("roster", {}).get("entries", [])

    # Scoring is read dynamically from the league's mSettings; parse_hitter_scoring
    # validates the result and falls back to the verified DEFAULT_HITTER_SCORING
    # if the parse looks wrong (wrong statId map / odd config), so we never
    # regress to the all-negative projections. The raw items are logged so the
    # ESPN_HITTING_STAT_IDS map can be corrected if a fallback ever fires.
    scoring = parse_hitter_scoring(data)
    try:
        items = data.get("settings", {}).get("scoringSettings", {}).get("scoringItems", [])
        print(f"[hitters.py] raw scoringItems statId→points: "
              f"{[(it.get('statId'), _resolve_points(it)) for it in (items or [])]}")
    except Exception as e:
        print(f"[hitters.py] scoring diagnostic failed: {e}")

    # ── Identify hitters on the roster ────────────────────────────────
    hitters_meta = []   # {name, team, pos, rank, bats, eligible}
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
        slot_id = entry.get("lineupSlotId", 16)
        pos, rank = hitter_slot(slot_id, eligible, injured)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        bats = (player.get("batSide") or {}).get("code", "") if isinstance(player.get("batSide"), dict) else ""
        hitters_meta.append({
            "name": name, "team": team_abbrev,
            "pos": pos, "rank": rank, "bats": bats,
        })
        if team_abbrev:
            team_map[name] = team_abbrev

    # ── Shared schedule (we only need the schedule, not pitcher starts) ─
    _, schedule = get_starts_for_players(
        [h["name"] for h in hitters_meta], week, team_map=team_map
    )

    # ── Season hitting stats + Savant batter expecteds (cached) ───────
    hit = load_hitter_stats(year_int)
    hitting_current  = hit["hitting_current"]
    hitting_previous = hit["hitting_previous"]
    savant_current   = hit["savant_batter_current"]
    savant_previous  = hit["savant_batter_previous"]

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
        savant_current=savant_current,
        savant_previous=savant_previous,
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
            "rank":        h["rank"],
            "bats":        h["bats"],
            "projFpts":    p.get("projFpts", 0.0),
            "projPerGame": round(per_game, 1),
            "blendWeight": p.get("blendWeight", 0.0),
            "modelType":   p.get("modelType", "stats"),
            "games":       p.get("games", len(h["gameDates"])),
            "seasonStats": _season_line(hitting_current.get(strip_accents(name), {})),
            "days":        days,
        })

    # Match ESPN's roster order: by lineup-slot rank, ties broken by projection.
    roster_hitters.sort(key=lambda x: (x["rank"], -x["projFpts"]))

    # ── Free-agent hitters (top available by ownership %) ─────────────
    free_agent_hitters = _fetch_fa_hitters(
        base, headers, cookies, PRO_TEAM_MAP, data.get("scoringPeriodId", week),
        schedule, period_dates, scoring, hitting_current, hitting_previous,
        savant_current, savant_previous, year_int, week,
    )

    return {
        "ok":            True,
        "teamName":      team_name,
        "weekStart":     week_start,
        "weekEnd":       week_end,
        "matchupDates":  [mp["start"], mp["end"]],
        "schedule":      schedule,
        "rosterHitters": roster_hitters,
        "freeAgentHitters": free_agent_hitters,
        "scoringStats":  sorted(scoring.keys()),
        "computedAt":    datetime.now(timezone.utc).isoformat(),
    }


def _fetch_fa_hitters(base, headers, cookies, PRO_TEAM_MAP, current_week,
                      schedule, period_dates, scoring, hitting_current,
                      hitting_previous, savant_current, savant_previous,
                      year_int, week):
    """Top available free-agent hitters by ownership %, projected with the same
    model as the roster. Mirrors the SP free-agent fetch in espn.py, filtered to
    hitter slots. Returns [] on any failure (FA hitters are non-critical)."""
    try:
        xff = json.dumps({
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "filterSlotIds": {"value": sorted(HITTER_SLOTS)},
                "limit": 100,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "filterStatsForCurrentSeasonScoringPeriodId": {"value": [current_week]},
            }
        })
        r = requests.get(
            base,
            params=[("view", "kona_player_info"), ("scoringPeriodId", current_week)],
            cookies=cookies, headers={**headers, "x-fantasy-filter": xff}, timeout=15,
        )
        if r.status_code != 200:
            print(f"[hitters.py] FA hitters HTTP {r.status_code}")
            return []

        meta = []
        for p in r.json().get("players", []):
            player = p.get("player", {})
            name = player.get("fullName", "")
            if not name:
                continue
            eligible = set(player.get("eligibleSlots", []))
            if not (eligible & HITTER_SLOTS):
                continue
            team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
            own = round(float(player.get("ownership", {}).get("percentOwned", 0) or 0), 1)
            meta.append({
                "name": name, "team": team_abbrev,
                "pos": _eligible_label(eligible), "ownPct": own,
                "gameDates": [d for d in period_dates if team_abbrev and team_abbrev in schedule.get(d, {})],
            })

        proj, _ = get_projected_hitter_fpts(
            [{"name": h["name"], "team": h["team"], "gameDates": h["gameDates"]} for h in meta],
            scoring=scoring, stat_current=hitting_current, stat_previous=hitting_previous,
            savant_current=savant_current, savant_previous=savant_previous,
            season=year_int, period=week,
        )

        out = []
        for h in meta:
            p = proj.get(h["name"], {})
            per_game = p.get("projPerGame", 0.0)
            days = []
            for d in h["gameDates"]:
                game = schedule.get(d, {}).get(h["team"], {})
                days.append({"date": d, "opp": game.get("opponent", ""),
                             "home": game.get("is_home", True), "proj": round(per_game, 1)})
            out.append({
                "name": h["name"], "team": h["team"], "pos": h["pos"], "bats": "",
                "percentOwned": h["ownPct"],
                "projFpts": p.get("projFpts", 0.0), "projPerGame": round(per_game, 1),
                "games": p.get("games", len(h["gameDates"])),
                "modelType": p.get("modelType", "stats"),
                "seasonStats": _season_line(hitting_current.get(strip_accents(h["name"]), {})),
                "days": days,
            })
        out.sort(key=lambda x: -x["percentOwned"])
        return out
    except Exception as e:
        print(f"[hitters.py] FA hitters fetch failed: {e}")
        return []


# ── Caching (mirrors the espn.py warm-serve pattern, lighter) ──────────
HITTER_CACHE_TTL = 1800  # 30 min
# Bump whenever the payload shape, scoring, or ordering changes so a deploy
# abandons stale cached blobs instead of serving them for up to TTL.
#   v2: TB scoring + ESPN lineup ordering. v3: scoring read from mSettings.
#   v4: corrected ESPN_HITTING_STAT_IDS map (now parses, no longer falls back).
#   v5: Phase 2 — Savant xBA/xSLG de-luck.
#   v6: add freeAgentHitters to the payload.
HITTER_CACHE_VERSION = 6


def _cache_key(team_id: int, week: int) -> str:
    year = os.environ.get("ESPN_SEASON", "2026")
    return f"cache:hitterdata:v{HITTER_CACHE_VERSION}:{year}:{team_id}:{week}"


def savant_debug(team_id: int, week: int) -> dict:
    """Diagnostic: confirm the Phase-2 Savant de-luck is live. Returns the
    batter-expected-stats coverage counts plus, per rostered hitter, whether a
    Savant row matched (modelType) and the actual SLG vs xSLG that drives the
    de-luck. Hit /api/hitters?debug=savant."""
    year_int = int(os.environ.get("ESPN_SEASON", "2026"))
    payload = get_hitter_data(team_id, week)            # cached; has modelType + seasonStats
    hit = load_hitter_stats(year_int)                   # cached
    sav = hit.get("savant_batter_current", {})
    sav_prev = hit.get("savant_batter_previous", {})

    rows = []
    for h in payload.get("rosterHitters", []):
        key = strip_accents(h["name"])
        srow = sav.get(key)
        season = h.get("seasonStats") or {}
        rows.append({
            "name":      h["name"],
            "modelType": h.get("modelType"),
            "matched":   bool(srow),
            "actualSlg": season.get("slg"),
            "xslg":      round(srow["xslg"], 3) if srow else None,
            "xba":       round(srow["xba"], 3) if srow else None,
            "projPerGame": h.get("projPerGame"),
        })
    matched = sum(1 for r in rows if r["matched"])
    return {
        "ok": True,
        "savantBatterCurrentCount": len(sav),
        "savantBatterPreviousCount": len(sav_prev),
        "rosteredMatched": f"{matched}/{len(rows)}",
        "sample": [
            {"name": n, "xba": round(v.get("xba", 0), 3), "xslg": round(v.get("xslg", 0), 3)}
            for n, v in list(sav.items())[:5]
        ],
        "hitters": rows,
    }


def scoring_debug(team_id: int) -> dict:
    """Diagnostic: fetch the league mSettings and return the raw hitting/relevant
    scoringItems alongside what the parser derives and the hardcoded fallback.
    Lets us verify/repair the ESPN_HITTING_STAT_IDS map against a real league.
    Hit /api/hitters?debug=scoring."""
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year = os.environ.get("ESPN_SEASON", "2026")
    headers, cookies = get_headers_and_cookies()
    base = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )
    r = requests.get(base, params=[("view", "mSettings")], cookies=cookies, headers=headers, timeout=15)
    if r.status_code != 200:
        return {"ok": False, "error": f"ESPN HTTP {r.status_code}"}
    data = r.json()
    items = data.get("settings", {}).get("scoringSettings", {}).get("scoringItems", [])
    raw = [{
        "statId": it.get("statId"),
        "points": it.get("points"),
        "pointsOverrides": it.get("pointsOverrides"),
        "resolved": _resolve_points(it),
    } for it in (items or [])]
    return {
        "ok": True,
        "scoringItems": raw,
        "parsed": parse_hitter_scoring(data),
        "hardcodedFallback": DEFAULT_HITTER_SCORING,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs      = parse_qs(urlparse(self.path).query)
        env_tid = os.environ.get("ESPN_TEAM_ID", "")
        team_id = int(env_tid) if env_tid else int(qs.get("teamId", ["1"])[0])
        week    = int(qs.get("week", ["1"])[0])
        fresh   = qs.get("fresh", ["0"])[0] in ("1", "true")
        debug   = qs.get("debug", [""])[0]

        if debug in ("scoring", "savant"):
            try:
                payload = scoring_debug(team_id) if debug == "scoring" else savant_debug(team_id, week)
            except Exception as e:
                payload = {"ok": False, "error": str(e)}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

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
