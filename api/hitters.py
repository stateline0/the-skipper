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
from fetcher import (
    get_headers_and_cookies, get_pro_team_map, load_hitter_stats,
    load_hitter_game_logs, load_player_hands, load_hitter_splits,
)
from kv import cache_get, cache_set
from projection_hitter import (
    parse_hitter_scoring, get_projected_hitter_fpts, strip_accents,
    platoon_multiplier, DEFAULT_HITTER_SCORING, _resolve_points,
)


def _hand_probe(pid):
    """TEMP: dump the raw /people/{id} response for one pitcher id so we can see
    whether this env serves player bios (and what fields/handedness exist)."""
    out = {"pid": pid}
    if not pid:
        return out
    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{pid}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
        )
        out["status"] = r.status_code
        try:
            j = r.json()
            out["topKeys"] = list(j.keys())
            ppl = j.get("people", [])
            out["peopleLen"] = len(ppl)
            if ppl:
                out["personKeys"] = sorted(ppl[0].keys())
                out["pitchHand"] = ppl[0].get("pitchHand")
                out["batSide"] = ppl[0].get("batSide")
        except Exception as e:
            out["parseErr"] = str(e)[:160]
            out["bodyHead"] = r.text[:160]
    except Exception as e:
        out["reqErr"] = str(e)[:160]
    return out


def _build_days(name, team, game_dates, schedule, base, hands, splits, overall_ops):
    """Per-day cells with the matchup factor stack. Phase 6 adds a platoon
    factor (batter vs the day's probable-starter hand); later layers append
    more entries to `factors`. day proj = base × Π(factors). Each factor is
    {label, mult} so the frontend popover lists Base → factors → Proj."""
    days = []
    for d in game_dates:
        game = schedule.get(d, {}).get(team, {})
        opp_starter = (game.get("opp_starter") or "").strip()
        opp_hand = (hands.get(strip_accents(opp_starter)) or {}).get("throws", "") if opp_starter else ""
        if opp_hand not in ("L", "R"):
            opp_hand = ""
        factors = []
        mult = 1.0
        if opp_hand and overall_ops:
            side = (splits.get(strip_accents(name)) or {}).get("vL" if opp_hand == "L" else "vR") or {}
            pm = platoon_multiplier(side.get("ops", 0), side.get("pa", 0), overall_ops)
            if pm != 1.0:
                factors.append({"label": f"Platoon (v{opp_hand}HP)", "mult": pm})
                mult *= pm
        days.append({
            "date": d,
            "opp": game.get("opponent", ""),
            "home": game.get("is_home", True),
            "oppStarter": opp_starter.title() if opp_starter else "",
            "oppHand": opp_hand or None,
            "base": round(base, 1),
            "factors": factors,
            "proj": round(base * mult, 1),
        })
    return days

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


def _league_avg(savant_expected: dict, savant_statcast: dict) -> dict:
    """League-average reference values for the advanced columns, averaged over
    all qualified batters in the Savant datasets (min-PA/BBE filtered upstream)."""
    def mean(vals):
        vals = [v for v in vals if v]
        return sum(vals) / len(vals) if vals else None

    xba   = mean([v.get("xba", 0)   for v in savant_expected.values()])
    xslg  = mean([v.get("xslg", 0)  for v in savant_expected.values()])
    xwoba = mean([v.get("xwoba", 0) for v in savant_expected.values()])
    brl   = mean([v.get("brl_pct", 0) for v in savant_statcast.values()])
    ev    = mean([v.get("avg_ev", 0)  for v in savant_statcast.values()])
    return {
        "xba":       round(xba, 3) if xba else None,
        "xslg":      round(xslg, 3) if xslg else None,
        "xwoba":     round(xwoba, 3) if xwoba else None,
        "barrelPct": round(brl, 1) if brl else None,
        "evAvg":     round(ev, 1) if ev else None,
    }


def _advanced_line(name: str, savant_expected: dict, savant_statcast: dict) -> dict | None:
    """Advanced (Savant) display block for the Stats tab: xBA/xSLG/xwOBA + a
    luck signal (est_woba − woba; positive = unlucky/due) and Barrel%/Whiff%.
    Returns None when the hitter has no Savant footprint."""
    key = strip_accents(name)
    exp = savant_expected.get(key, {})
    sc = savant_statcast.get(key, {})
    out = {}
    if exp:
        if exp.get("xba"):   out["xba"]   = round(exp["xba"], 3)
        if exp.get("xslg"):  out["xslg"]  = round(exp["xslg"], 3)
        if exp.get("xwoba"): out["xwoba"] = round(exp["xwoba"], 3)
        if "woba_diff" in exp: out["wobaDiff"] = round(exp["woba_diff"], 3)
    if sc:
        if sc.get("brl_pct"):      out["barrelPct"]  = round(sc["brl_pct"], 1)
        if sc.get("hard_hit_pct"): out["hardHitPct"] = round(sc["hard_hit_pct"], 1)
        if sc.get("avg_ev"):       out["evAvg"]      = round(sc["avg_ev"], 1)
    return out or None


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
    savant_statcast  = hit.get("savant_batter_statcast_current", {})

    # ── Game days per hitter (days their team plays in the period) ────
    for h in hitters_meta:
        team = h["team"]
        h["gameDates"] = [d for d in period_dates if team and team in schedule.get(d, {})]

    # ── Projection (+ Phase-3 recent form from game logs) ─────────────
    roster_keys = [strip_accents(h["name"]) for h in hitters_meta]
    roster_logs = load_hitter_game_logs(year_int, hitting_current, roster_keys)
    splits = load_hitter_splits(year_int, hitting_current, roster_keys)    # Phase 6

    # Phase 6 handedness: opposing-starter IDs (mapped from the schedule's
    # opp_starter names via the cached pitching stats) + rostered hitter IDs.
    pitching = {}
    try:
        pitching = cache_get(f"cache:mlb-stats:{year_int}") or {}
    except Exception:
        pass
    opp_ids = set()
    for d in period_dates:
        for tm in schedule.get(d, {}).values():
            nm = (tm.get("opp_starter") or "").strip()
            pid = (pitching.get(strip_accents(nm)) or {}).get("_mlbId") if nm else None
            if pid:
                opp_ids.add(pid)
    hitter_ids = [(hitting_current.get(nk) or {}).get("_mlbId") for nk in roster_keys]
    hands = load_player_hands(year_int, list(opp_ids) + [i for i in hitter_ids if i])
    _pitching_n = len(pitching)
    _ids_n = len(opp_ids) + len([i for i in hitter_ids if i])
    proj, _details = get_projected_hitter_fpts(
        [{"name": h["name"], "team": h["team"], "gameDates": h["gameDates"]} for h in hitters_meta],
        scoring=scoring,
        stat_current=hitting_current,
        stat_previous=hitting_previous,
        savant_current=savant_current,
        savant_previous=savant_previous,
        game_logs=roster_logs,
        season=year_int, period=week,
    )

    # ── Assemble output ───────────────────────────────────────────────
    roster_hitters = []
    for h in hitters_meta:
        name = h["name"]
        p = proj.get(name, {})
        per_game = p.get("projPerGame", 0.0)
        season = _season_line(hitting_current.get(strip_accents(name), {}))
        overall_ops = (season["obp"] + season["slg"]) if season else None
        bats = (hands.get(strip_accents(name)) or {}).get("bats") or h["bats"]
        # Per-day cells with the matchup factor stack (Phase 6: platoon).
        days = _build_days(name, h["team"], h["gameDates"], schedule, per_game, hands, splits, overall_ops)
        proj_week = round(sum(d["proj"] for d in days), 1)
        roster_hitters.append({
            "name":        name,
            "team":        h["team"],
            "pos":         h["pos"],
            "rank":        h["rank"],
            "bats":        bats,
            "projFpts":    proj_week,
            "projPerGame": round(per_game, 1),
            "blendWeight": p.get("blendWeight", 0.0),
            "modelType":   p.get("modelType", "stats"),
            "recentForm":  p.get("recentForm"),
            "games":       p.get("games", len(h["gameDates"])),
            "seasonStats": season,
            "advanced":    _advanced_line(name, savant_current, savant_statcast),
            "days":        days,
        })

    # Match ESPN's roster order: by lineup-slot rank, ties broken by projection.
    roster_hitters.sort(key=lambda x: (x["rank"], -x["projFpts"]))

    # ── Free-agent hitters (top available by ownership %) ─────────────
    free_agent_hitters = _fetch_fa_hitters(
        base, headers, cookies, PRO_TEAM_MAP, data.get("scoringPeriodId", week),
        schedule, period_dates, scoring, hitting_current, hitting_previous,
        savant_current, savant_previous, savant_statcast, hands, year_int, week,
    )

    return {
        "ok":            True,
        "_diag":         {  # TEMP platoon diagnostic — remove before merge
            "handsCount": len(hands),
            "pitchingCacheSize": _pitching_n,
            "idsRequested": _ids_n,
            "handProbe": _hand_probe(next(iter(opp_ids), None)),
            "sampleHands": dict(list(hands.items())[:4]),
            "splitsCovered": f"{len(splits)}/{len(roster_keys)}",
            "sampleSplits": dict(list(splits.items())[:2]),
            "sampleDays": [
                {"hitter": h["name"], "date": d["date"], "oppStarter": d.get("oppStarter"),
                 "oppHand": d.get("oppHand"), "factors": d.get("factors")}
                for h in roster_hitters[:3] for d in (h.get("days") or [])[:2]
            ],
        },
        "teamName":      team_name,
        "weekStart":     week_start,
        "weekEnd":       week_end,
        "matchupDates":  [mp["start"], mp["end"]],
        "schedule":      schedule,
        "rosterHitters": roster_hitters,
        "freeAgentHitters": free_agent_hitters,
        "leagueAvg":     _league_avg(savant_current, savant_statcast),
        "scoringStats":  sorted(scoring.keys()),
        "computedAt":    datetime.now(timezone.utc).isoformat(),
    }


def _fetch_fa_hitters(base, headers, cookies, PRO_TEAM_MAP, current_week,
                      schedule, period_dates, scoring, hitting_current,
                      hitting_previous, savant_current, savant_previous,
                      savant_statcast, hands, year_int, week):
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

        fa_keys = [strip_accents(h["name"]) for h in meta]
        fa_logs = load_hitter_game_logs(year_int, hitting_current, fa_keys)
        fa_splits = load_hitter_splits(year_int, hitting_current, fa_keys)
        proj, _ = get_projected_hitter_fpts(
            [{"name": h["name"], "team": h["team"], "gameDates": h["gameDates"]} for h in meta],
            scoring=scoring, stat_current=hitting_current, stat_previous=hitting_previous,
            savant_current=savant_current, savant_previous=savant_previous,
            game_logs=fa_logs,
            season=year_int, period=week,
        )

        out = []
        for h in meta:
            p = proj.get(h["name"], {})
            per_game = p.get("projPerGame", 0.0)
            season = _season_line(hitting_current.get(strip_accents(h["name"]), {}))
            overall_ops = (season["obp"] + season["slg"]) if season else None
            bats = (hands.get(strip_accents(h["name"])) or {}).get("bats", "")
            days = _build_days(h["name"], h["team"], h["gameDates"], schedule, per_game, hands, fa_splits, overall_ops)
            out.append({
                "name": h["name"], "team": h["team"], "pos": h["pos"], "bats": bats,
                "percentOwned": h["ownPct"],
                "projFpts": round(sum(d["proj"] for d in days), 1), "projPerGame": round(per_game, 1),
                "games": p.get("games", len(h["gameDates"])),
                "modelType": p.get("modelType", "stats"),
                "recentForm": p.get("recentForm"),
                "seasonStats": season,
                "advanced": _advanced_line(h["name"], savant_current, savant_statcast),
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
#   v7: add advanced (Savant xBA/xSLG/xwOBA, Barrel%/Whiff%) block.
#   v8: advanced uses HardHit% (ev95percent) + EV instead of Whiff%.
#   v9: drop HardHit%; add leagueAvg block for advanced-column headers.
#   v10: Phase 3 — recent-form blend (game-log weighted) in projPerGame.
#   v11: Phase 6 — per-day platoon factor + per-day factors[] for the popover.
#   v12: TEMP — embedded _diag block (remove before merge).
#   v13: handedness hydrated by person ID (/people?personIds) — /sports/1/players was empty.
#   v14: handedness via per-player /people/{id}; opp-starter IDs from pitching cache.
#   v15: TEMP handProbe in _diag to inspect raw /people/{id} bio response.
#   v16: cache handedness BY ID, resolved-only (poisoned id-set caused 0 hands).
#   v17: fix NameError in fetch_player_hands (_strip_accents_mlb) — the real root cause.
HITTER_CACHE_VERSION = 17


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


def platoon_debug(team_id: int, week: int) -> dict:
    """Diagnostic for the Phase-6 platoon layer: handedness-map coverage, a few
    sample hand entries, split coverage, and per-day opp-starter/hand/factor for
    a few rostered hitters. Hit /api/hitters?debug=platoon."""
    year_int = int(os.environ.get("ESPN_SEASON", "2026"))
    hands = load_player_hands(year_int, [])             # read whatever's cached
    payload = get_hitter_data(team_id, week)            # cached
    roster = payload.get("rosterHitters", [])
    keys = [strip_accents(h["name"]) for h in roster]
    hit = load_hitter_stats(year_int)
    splits = load_hitter_splits(year_int, hit["hitting_current"], keys)
    days = []
    for h in roster[:6]:
        for d in (h.get("days") or [])[:3]:
            days.append({
                "hitter": h["name"], "date": d["date"],
                "oppStarter": d.get("oppStarter"), "oppHand": d.get("oppHand"),
                "factors": d.get("factors"),
            })
    return {
        "ok": True,
        "handsCount": len(hands),
        "sampleHands": dict(list(hands.items())[:6]),
        "splitsCovered": f"{len(splits)}/{len(keys)}",
        "sampleSplits": dict(list(splits.items())[:3]),
        "sampleDays": days,
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

        if debug in ("scoring", "savant", "platoon"):
            try:
                payload = (scoring_debug(team_id) if debug == "scoring"
                           else savant_debug(team_id, week) if debug == "savant"
                           else platoon_debug(team_id, week))
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
