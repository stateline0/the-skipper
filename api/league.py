"""api/league.py — League rosters viewer (trade engine Phase 1, read-only).

The `mRoster`+`mTeam` call already made by `get_league_data` returns **all 12
teams' rosters** — they're downloaded today and discarded. This endpoint keeps
them: one `mRoster`+`mTeam`+`mSettings` call → for every team, a pitchers/batters
split with the same Stats-tab payloads The Skipper builds for its own players,
plus a rest-of-season (ROS) FPTS estimate. Everything else (projections, season
lines, Savant blocks) is computed in-process from the **shared all-MLB KV
caches** (`load_cached_data` / `load_hitter_stats`) — no new external fetches
beyond the single roster call. No opponent schedule grid (out of scope).

Cached per league under `cache:league-roster:{year}` (~30-min TTL); behind the
auth gate (middleware protects everything except the explicit diagnostic list).
"""

import json
import os
import requests
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# NOTE: the local-module imports (fetcher / espn / hitters / projection / kv …)
# are done lazily inside the functions below, NOT at module scope. Vercel's
# Python builder doesn't reliably bundle sibling modules for a freshly-added
# endpoint (see /api/injury_probe), and a module-scope import that fails to
# resolve crashes the whole function at cold start — an opaque platform 500 that
# the handler's try/except can't catch. Keeping module scope to stdlib +
# requests guarantees the handler loads and can surface the real error as JSON.

# 14=SP, 13=RP (mirrors espn.py SP/RP_ELIGIBLE). Inlined so no import is needed
# just for the roster split.
HITTER_SLOTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

# Rest-of-season horizons. A full MLB season is 162 team games; a healthy
# starter makes ~32 starts (mirrors the Stats-tab Pace comparator,
# components/StatsTable.tsx FULL_SEASON_STARTS).
SEASON_GAMES = 162
FULL_SEASON_STARTS = 32

PITCHER_SLOTS = {13, 14}  # 14=SP, 13=RP (mirrors espn.py SP/RP_ELIGIBLE)

LEAGUE_CACHE_TTL = 1800  # 30 min


def _cache_key(year: int) -> str:
    return f"cache:league-roster:{year}"


def _team_games_remaining(team_win_data: dict, abbrev: str):
    """Team games left this season from the cached win data (games played =
    W+L+...). None when the team isn't in the cache so ROS shows an em-dash
    rather than a fabricated number."""
    info = team_win_data.get(abbrev)
    if not info:
        return None
    played = info.get("games", 0)
    return max(0, SEASON_GAMES - int(played))


def _team_meta(team: dict, members_by_id: dict) -> dict:
    """{id, name, owner, record} from an mTeam team object."""
    name = (team.get("name") or
            f"{team.get('location', '')} {team.get('nickname', '')}").strip()
    owners = team.get("owners") or []
    owner = members_by_id.get(owners[0], "") if owners else ""
    rec = (team.get("record") or {}).get("overall") or {}
    w, l = rec.get("wins"), rec.get("losses")
    record = f"{w}-{l}" if w is not None and l is not None else ""
    return {"id": team.get("id"), "name": name or f"Team {team.get('id')}",
            "owner": owner, "record": record}


def _build_team(team, cd, hd, scoring, PRO_TEAM_MAP, year_int, week):
    """Pitchers + batters payloads for a single team, projected off the shared
    caches. Returns {pitchers: [...], batters: [...]}."""
    from projection import get_projected_fpts
    from projection_hitter import get_projected_hitter_fpts, strip_accents
    from espn import (
        _build_season_stats, _build_savant_expected, _build_fpts_history,
        get_pos_eligible, get_slot_label, get_status,
    )
    from hitters import _season_line, _advanced_line, _eligible_positions

    entries = team.get("roster", {}).get("entries", [])

    # ── Split the roster ────────────────────────────────────────────────
    pitchers_raw, hitters_raw = [], []
    for entry in entries:
        player = entry.get("playerPoolEntry", {}).get("player", {})
        if not player.get("fullName"):
            continue
        eligible = set(player.get("eligibleSlots", []))
        if eligible & PITCHER_SLOTS:
            pitchers_raw.append((entry, player, eligible))
        elif eligible & HITTER_SLOTS:
            hitters_raw.append((entry, player, eligible))

    # ── Pitchers ────────────────────────────────────────────────────────
    pitcher_inputs = []
    for _entry, player, eligible in pitchers_raw:
        pitcher_inputs.append({
            "name": player.get("fullName"),
            "team": PRO_TEAM_MAP.get(player.get("proTeamId", 0), ""),
            "starts": 0, "startDates": [],
            # RP-only (13 eligible, 14 not) → appearance-based projection path.
            "is_rp": 13 in eligible and 14 not in eligible,
        })
    _proj, _blend, fpts_per_start, _details = get_projected_fpts(
        pitcher_inputs, cd.get("team_woba_factors", {}),
        season=year_int, period=week,
        today_str=datetime.now().strftime("%Y-%m-%d"),
        savant_current=cd.get("savant_current"), savant_previous=cd.get("savant_previous"),
        mlb_stats_current=cd.get("mlb_stats_current"), mlb_stats_previous=cd.get("mlb_stats_previous"),
        game_logs=cd.get("game_logs_current"), team_win_data=cd.get("team_win_data"),
        schedule={},
    ) if pitcher_inputs else ({}, {}, {}, {})

    pitchers = []
    for _entry, player, eligible in pitchers_raw:
        name = player.get("fullName")
        nk = strip_accents(name)
        injured = player.get("injured", False)
        season_stats = _build_season_stats(cd.get("mlb_stats_current", {}).get(nk, {}))
        gs = (season_stats or {}).get("gs", 0)
        per = fpts_per_start.get(name, 0.0)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        # ROS: starters use the Pace horizon (32 − starts made); relievers
        # prorate their appearance pace over the team's remaining games.
        if 14 in eligible:
            ros = round(per * max(0, FULL_SEASON_STARTS - gs), 1)
        else:
            apps = int(cd.get("mlb_stats_current", {}).get(nk, {}).get("gamesPlayed", 0))
            tgr = _team_games_remaining(cd.get("team_win_data", {}), team_abbrev)
            tgp = (cd.get("team_win_data", {}).get(team_abbrev) or {}).get("games", 0)
            ros = round(per * apps * tgr / tgp, 1) if (tgr and tgp) else None
        pitchers.append({
            "name": name, "team": team_abbrev,
            "slot": get_slot_label(eligible, injured),
            "posEligible": get_pos_eligible(eligible),
            "injuryStatus": get_status(injured),
            "projFpts": round(per, 1),           # per-start (Proj FPTS column)
            "rosFpts": ros,
            "seasonStats": season_stats,
            "savantExpected": _build_savant_expected(
                cd.get("savant_current", {}).get(nk, {}),
                cd.get("savant_statcast_current", {}).get(nk, {}),
                cd.get("savant_whiff_current", {}).get(nk, 0.0),
            ),
            "fptsHistory": _build_fpts_history(cd.get("game_logs_current", {}).get(nk, [])),
        })
    pitchers.sort(key=lambda p: -(p["rosFpts"] or p["projFpts"] or 0))

    # ── Batters ─────────────────────────────────────────────────────────
    hitter_inputs = [{
        "name": player.get("fullName"),
        "team": PRO_TEAM_MAP.get(player.get("proTeamId", 0), ""),
        "gameDates": [],
    } for _entry, player, eligible in hitters_raw]
    hproj, _ = get_projected_hitter_fpts(
        hitter_inputs, scoring=scoring,
        stat_current=hd.get("hitting_current"), stat_previous=hd.get("hitting_previous"),
        savant_current=hd.get("savant_batter_current"), savant_previous=hd.get("savant_batter_previous"),
        game_logs={}, season=year_int, period=week,
    ) if hitter_inputs else ({}, None)

    batters = []
    for _entry, player, eligible in hitters_raw:
        name = player.get("fullName")
        nk = strip_accents(name)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        per_game = hproj.get(name, {}).get("projPerGame", 0.0)
        bats = (player.get("batSide") or {}).get("code", "") if isinstance(player.get("batSide"), dict) else ""
        tgr = _team_games_remaining(cd.get("team_win_data", {}), team_abbrev)
        ros = round(per_game * tgr, 1) if tgr is not None else None
        batters.append({
            "name": name, "team": team_abbrev,
            "pos": _eligible_positions(eligible), "bats": bats,
            "projPerGame": round(per_game, 1),
            "rosFpts": ros,
            "seasonStats": _season_line(hd.get("hitting_current", {}).get(nk, {})),
            "advanced": _advanced_line(name, hd.get("savant_batter_current", {}),
                                       hd.get("savant_batter_statcast_current", {})),
        })
    batters.sort(key=lambda b: -(b["rosFpts"] or 0))

    return {"pitchers": pitchers, "batters": batters}


def build_league_rosters() -> dict:
    from fetcher import (
        get_headers_and_cookies, get_pro_team_map,
        load_cached_data, load_hitter_stats,
    )
    from projection_hitter import parse_hitter_scoring

    league_id = os.environ.get("ESPN_LEAGUE_ID")
    if not league_id:
        raise RuntimeError("Missing env var ESPN_LEAGUE_ID")
    year = os.environ.get("ESPN_SEASON", "2026")
    year_int = int(year)
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP = get_pro_team_map(headers, cookies)
    base = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    r = requests.get(
        base,
        params=[("view", "mRoster"), ("view", "mTeam"), ("view", "mSettings")],
        cookies=cookies, headers=headers, timeout=20,
    )
    if r.status_code in (401, 403):
        raise Exception(f"ESPN returned HTTP {r.status_code} — auth failed (check ESPN_S2/ESPN_SWID).")
    if r.status_code != 200:
        raise Exception(f"ESPN returned HTTP {r.status_code}")
    data = r.json()

    week = data.get("scoringPeriodId", 1)
    members_by_id = {m.get("id"): (m.get("displayName") or "").strip()
                     for m in data.get("members", [])}
    scoring = parse_hitter_scoring(data)

    # Shared all-MLB caches (no per-team external fetches).
    cd = load_cached_data(year_int)
    hd = load_hitter_stats(year_int)

    teams_out = []
    for team in data.get("teams", []):
        meta = _team_meta(team, members_by_id)
        rosters = _build_team(team, cd, hd, scoring, PRO_TEAM_MAP, year_int, week)
        teams_out.append({**meta, **rosters})
    teams_out.sort(key=lambda t: t["name"].lower())

    return {"teams": teams_out, "week": week,
            "generatedAt": datetime.utcnow().isoformat() + "Z"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            from kv import cache_get, cache_set
            qs = parse_qs(urlparse(self.path).query)
            fresh = qs.get("fresh", ["0"])[0] == "1"
            year = int(os.environ.get("ESPN_SEASON", "2026"))
            payload = None
            if not fresh:
                try:
                    payload = cache_get(_cache_key(year))
                except Exception:
                    payload = None
            if payload is None:
                payload = build_league_rosters()
                try:
                    cache_set(_cache_key(year), payload, ttl_seconds=LEAGUE_CACHE_TTL)
                except Exception:
                    pass
            status, body = 200, payload
        except Exception as e:
            import traceback
            status, body = 500, {"error": f"{type(e).__name__}: {e}",
                                 "traceback": traceback.format_exc()[-1500:]}
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass
