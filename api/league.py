"""api/league.py — League rosters viewer (trade engine Phase 1, read-only).

The `mRoster`+`mTeam` call already made by `get_league_data` returns **all 12
teams' rosters** — downloaded today and discarded. This endpoint keeps them: one
`mRoster`+`mTeam`+`mSettings` call → for every team, a pitchers/batters split with
the same Stats-tab payloads The Skipper builds for its own players, plus a
rest-of-season (ROS) FPTS estimate. Projections + season lines are computed
in-process from the **shared all-MLB KV caches** (`load_cached_data` /
`load_hitter_stats`) — no new external fetches beyond the single roster call.
No opponent schedule grid (out of scope).

Imports: only **leaf** modules (fetcher / kv / projection / projection_hitter +
mlb/weather/savant) — the same set `espn.py` imports and Vercel reliably bundles.
We deliberately do NOT import the sibling *endpoint* modules `espn`/`hitters`:
Vercel's Python builder fails to bundle the transitive closure when one new
endpoint imports another, crashing the function at cold start (an opaque 500 the
handler can't catch). The handful of small, pure payload builders that live in
those modules are copied here instead — a contained duplication that keeps this
function's bundle self-contained and reliable.

Cached per league under `cache:league-roster:{year}` (~30-min TTL); behind the
auth gate.
"""

import json
import os
import requests
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from fetcher import (
    get_headers_and_cookies, get_pro_team_map,
    load_cached_data, load_hitter_stats,
)
from kv import cache_get, cache_set
from projection import get_projected_fpts, strip_accents, parse_ip
from projection_hitter import get_projected_hitter_fpts, parse_hitter_scoring
# Force Vercel to bundle the transitive leaf closure (these are imported lazily
# inside fetcher/projection, which the builder can otherwise miss).
import mlb        # noqa: F401
import weather    # noqa: F401
import savant     # noqa: F401

# Rest-of-season horizons. A full MLB season is 162 team games; a healthy
# starter makes ~32 starts (mirrors StatsTable.tsx FULL_SEASON_STARTS).
SEASON_GAMES = 162
FULL_SEASON_STARTS = 32

PITCHER_SLOTS = {13, 14}                                  # 14=SP, 13=RP
HITTER_SLOTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

LEAGUE_CACHE_TTL = 1800  # 30 min


# ─── Pure payload builders (copied from espn.py / hitters.py — see module note) ─

def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_season_stats(stat_dict: dict):
    """Compact pitcher season line for the Stats tab (W/L/ERA/K9/BB9/SV/IP/GS +
    season-to-date FPTS). None when there are no innings."""
    if not stat_dict:
        return None
    ip = parse_ip(stat_dict.get("inningsPitched", "0.0"))
    if ip <= 0:
        return None
    so = int(stat_dict.get("strikeOuts", 0))
    bb = int(stat_dict.get("baseOnBalls", 0))
    w = int(stat_dict.get("wins", 0))
    l = int(stat_dict.get("losses", 0))
    hits = _safe_float(stat_dict.get("hits", 0))
    er = _safe_float(stat_dict.get("earnedRuns", 0))
    hbp = _safe_float(stat_dict.get("hitBatsmen", stat_dict.get("hitByPitch", 0)))
    sv = _safe_float(stat_dict.get("saves", 0))
    season_fpts = (ip * 3 + so - hits - bb + er * -2 - hbp + sv * 5 + w * 5 + l * -5)
    return {
        "w": w, "l": l, "era": _safe_float(stat_dict.get("era", 0)),
        "k9": round(so / ip * 9, 2), "bb9": round(bb / ip * 9, 2),
        "sv": int(sv), "ip": round(ip, 1),
        "gs": int(stat_dict.get("gamesStarted", 0)),
        "seasonFptsToDate": round(season_fpts, 1),
    }


def _build_savant_expected(expected: dict, statcast: dict, whiff_pct: float = 0.0):
    """Pitcher Savant block — xERA/xwOBA/wobaDiff + Barrel% + Whiff%. None when
    every source is empty."""
    if not expected and not statcast and not whiff_pct:
        return None
    out: dict = {}
    if expected:
        if expected.get("xera", 0):  out["xera"] = round(expected["xera"], 2)
        if expected.get("xwoba", 0): out["xwoba"] = round(expected["xwoba"], 3)
        if "woba_diff" in expected:  out["wobaDiff"] = round(expected["woba_diff"], 3)
    if statcast and statcast.get("brl_pct", 0):
        out["barrelPct"] = round(statcast["brl_pct"], 1)
    if whiff_pct:
        out["whiffPct"] = round(whiff_pct, 1)
    return out or None


def _build_fpts_history(games: list, n_starts: int = 10):
    """Per-start FPTS series for the Form sparkline. None with < 2 starts."""
    if not games:
        return None
    starts = [g for g in games if g.get("gs", 0) >= 1]
    if len(starts) < 2:
        return None
    history = []
    for g in starts[-n_starts:]:
        fpts = (g["ip"] * 3 + g["so"] - g["h"] - g["bb"]
                + g["er"] * -2 - g["hb"] + g["w"] * 5 + g["l"] * -5 + g["sv"] * 5)
        history.append(round(fpts, 1))
    return history


def _get_slot_label(eligible_slots: set, injured: bool) -> str:
    if injured:
        return "IL"
    if 14 in eligible_slots:
        return "SP"
    if 13 in eligible_slots and 14 not in eligible_slots:
        return "RP"
    return "P"


def _get_pos_eligible(eligible_slots: set) -> str:
    out = []
    if 14 in eligible_slots: out.append("SP")
    if 15 in eligible_slots: out.append("RP")
    return "/".join(out) or "P"


def _get_status(injured: bool) -> str:
    return "IL" if injured else "Active"


def _season_line(stat: dict):
    """Compact hitter slash + counting line. None when no games played."""
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
        "avg": round(avg, 3), "obp": round(obp, 3), "slg": round(slg, 3),
        "hr": int(f("homeRuns")), "r": int(f("runs")), "rbi": int(f("rbi")),
        "sb": int(f("stolenBases")), "games": games,
    }


def _advanced_line(name: str, savant_expected: dict, savant_statcast: dict):
    """Hitter Savant block — xBA/xSLG/xwOBA + luck + Barrel%/HardHit%/EV."""
    key = strip_accents(name)
    exp = savant_expected.get(key, {})
    sc = savant_statcast.get(key, {})
    out = {}
    if exp:
        if exp.get("xba"):   out["xba"] = round(exp["xba"], 3)
        if exp.get("xslg"):  out["xslg"] = round(exp["xslg"], 3)
        if exp.get("xwoba"): out["xwoba"] = round(exp["xwoba"], 3)
        if "woba_diff" in exp: out["wobaDiff"] = round(exp["woba_diff"], 3)
    if sc:
        if sc.get("brl_pct"):      out["barrelPct"] = round(sc["brl_pct"], 1)
        if sc.get("hard_hit_pct"): out["hardHitPct"] = round(sc["hard_hit_pct"], 1)
        if sc.get("avg_ev"):       out["evAvg"] = round(sc["avg_ev"], 1)
    return out or None


def _eligible_positions(eligible: set) -> str:
    out = []
    for sid, label in ((0, "C"), (1, "1B"), (2, "2B"), (3, "3B"), (4, "SS")):
        if sid in eligible:
            out.append(label)
    if eligible & {5, 8, 9, 10}:
        out.append("OF")
    if out:
        return "/".join(out)
    if 11 in eligible:
        return "DH"
    return "UTIL"


# ─── League assembly ──────────────────────────────────────────────────────────

def _cache_key(year: int) -> str:
    return f"cache:league-roster:{year}"


def _team_games_remaining(team_win_data: dict, abbrev: str):
    info = team_win_data.get(abbrev)
    if not info:
        return None
    return max(0, SEASON_GAMES - int(info.get("games", 0)))


def _team_meta(team: dict, members_by_id: dict) -> dict:
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
    entries = team.get("roster", {}).get("entries", [])

    pitchers_raw, hitters_raw = [], []
    for entry in entries:
        player = entry.get("playerPoolEntry", {}).get("player", {})
        if not player.get("fullName"):
            continue
        eligible = set(player.get("eligibleSlots", []))
        if eligible & PITCHER_SLOTS:
            pitchers_raw.append((player, eligible))
        elif eligible & HITTER_SLOTS:
            hitters_raw.append((player, eligible))

    # ── Pitchers ────────────────────────────────────────────────────────
    pitcher_inputs = [{
        "name": player.get("fullName"),
        "team": PRO_TEAM_MAP.get(player.get("proTeamId", 0), ""),
        "starts": 0, "startDates": [],
        "is_rp": 13 in eligible and 14 not in eligible,
    } for player, eligible in pitchers_raw]
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
    for player, eligible in pitchers_raw:
        name = player.get("fullName")
        nk = strip_accents(name)
        injured = player.get("injured", False)
        season_stats = _build_season_stats(cd.get("mlb_stats_current", {}).get(nk, {}))
        gs = (season_stats or {}).get("gs", 0)
        per = fpts_per_start.get(name, 0.0)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        if 14 in eligible:
            ros = round(per * max(0, FULL_SEASON_STARTS - gs), 1)
        else:
            apps = int(cd.get("mlb_stats_current", {}).get(nk, {}).get("gamesPlayed", 0))
            tgr = _team_games_remaining(cd.get("team_win_data", {}), team_abbrev)
            tgp = (cd.get("team_win_data", {}).get(team_abbrev) or {}).get("games", 0)
            ros = round(per * apps * tgr / tgp, 1) if (tgr and tgp) else None
        pitchers.append({
            "name": name, "team": team_abbrev,
            "slot": _get_slot_label(eligible, injured),
            "posEligible": _get_pos_eligible(eligible),
            "injuryStatus": _get_status(injured),
            "projFpts": round(per, 1),
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
    } for player, eligible in hitters_raw]
    hproj, _ = get_projected_hitter_fpts(
        hitter_inputs, scoring=scoring,
        stat_current=hd.get("hitting_current"), stat_previous=hd.get("hitting_previous"),
        savant_current=hd.get("savant_batter_current"), savant_previous=hd.get("savant_batter_previous"),
        game_logs={}, season=year_int, period=week,
    ) if hitter_inputs else ({}, None)

    batters = []
    for player, eligible in hitters_raw:
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
