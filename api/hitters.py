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
import re
import sys
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mlb import get_starts_for_players, MATCHUP_PERIODS, fetch_probable_pitcher_ids, get_park_factor
from weather import get_weather_factor
from fetcher import (
    get_headers_and_cookies, get_pro_team_map, load_hitter_stats,
    load_hitter_game_logs, load_player_hands, load_hitter_splits, get_actual_fpts,
    load_cached_data,
)
# Pitcher projection + IP parser for the League viewer (api/league.py couldn't
# be its own endpoint — Vercel doesn't bundle sibling modules for newly-added
# Python files; routed through this already-bundled endpoint instead).
from projection import get_projected_fpts, parse_ip
from kv import (
    cache_get, cache_set,
    set_locked_hitter_projection, get_all_locked_hitter_projections,
)
from injuries import get_injuries
from projection_hitter import (
    parse_hitter_scoring, get_projected_hitter_fpts, strip_accents,
    platoon_multiplier, opp_pitcher_multiplier, actuals_from_logs,
    actuals_with_stats_from_logs,
    DEFAULT_HITTER_SCORING, _resolve_points,
)


def _build_days(name, team, game_dates, schedule, base, hands, splits, overall_ops,
                opp_savant, league_xwoba, weather_map, today_iso, actuals=None,
                il_zero=False, il_return=None):
    """Per-day cells with the matchup factor stack:
      Phase 6 — platoon (batter vs the day's probable-starter hand)
      Phase 7 — opposing-starter quality (their xwOBA-against vs league)
      Phase 4 — park factor (host park; applied directly, un-inverted)
      Phase 5 — weather (host park, future days; warm = more offense)
    day proj = base × Π(factors); each factor is {label, mult} so the frontend
    popover lists Base → factors → Proj.
    il_zero: player is on the IL (IL10/IL15/IL60) — IL days gain an IL ×0 factor
    so proj is 0 and the popover explains why. Past days' actuals are untouched.
    il_return (Phase B): the estimated return date (YYYY-MM-DD). When set, only
    days BEFORE it are zeroed — games on/after the return date project normally,
    so a returning player isn't flat-zeroed across the whole window."""
    days = []
    for d in game_dates:
        game = schedule.get(d, {}).get(team, {})
        opp_starter = (game.get("opp_starter") or "").strip()
        opp_key = strip_accents(opp_starter) if opp_starter else ""
        opp_hand = (hands.get(opp_key) or {}).get("throws", "") if opp_key else ""
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
        if opp_key and league_xwoba:
            ox = (opp_savant.get(opp_key) or {}).get("xwoba")
            qm = opp_pitcher_multiplier(ox, league_xwoba)
            if qm != 1.0:
                factors.append({"label": "Opp SP quality", "mult": qm})
                mult *= qm
        # Host park (home team's park): hitter's team if home, else the opponent.
        park_team = team if game.get("is_home", True) else game.get("opponent", "")
        if park_team:
            pf = get_park_factor(park_team)        # run-env factor, applied directly
            if pf != 1.0:
                factors.append({"label": f"Park ({park_team})", "mult": round(pf, 3)})
                mult *= pf
            if game.get("status") == "scheduled":   # unplayed → forecast applies
                wx = weather_map.get((park_team, d))
                wf = wx.get("factor", 1.0) if wx else 1.0
                if wf and wf != 1.0:
                    temp = wx.get("temp_f") if wx else None
                    label = f"Weather ({round(temp)}°F)" if temp else "Weather"
                    factors.append({"label": label, "mult": round(wf, 3)})
                    mult *= wf
        if il_zero and (not il_return or d < il_return):
            factors.append({"label": "IL", "mult": 0.0})
            mult = 0.0
        av = (actuals.get(name) or {}).get(d) if actuals else None
        days.append({
            "date": d,
            "opp": game.get("opponent", ""),
            "home": game.get("is_home", True),
            "status": game.get("status", ""),
            "oppStarter": opp_starter.title() if opp_starter else "",
            "oppHand": opp_hand or None,
            "base": round(base, 1),
            "factors": factors,
            "proj": round(base * mult, 1),
            "actual": round(av, 1) if av is not None else None,
        })
    return days


def _hitter_slug(name: str) -> str:
    """Match kv._make_hitter_key's slug so we can skip already-locked dates."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def _lock_started_days(season, period, name, days, model, today_iso, existing):
    """Freeze each started game-date projection (NX). `status != "scheduled"` is
    the timezone-independent "game has begun" signal (mirrors pitcher per-start
    locks). `existing` is the pre-fetched {slug: {date: ...}} map so we only
    write genuinely new locks — avoids redundant writes + log spam on reloads.

    A date already holding the cron's all-MLB BASELINE lock (model.allMlb —
    per-game rate, no factor stack) is UPGRADED to this factor-adjusted value:
    the noon cron always beats the at-game-start page write to the NX lock, so
    without the upgrade roster hitters' accuracy locks would never carry the
    matchup factors. A factor-adjusted lock is frozen for good — never rewritten.
    Returns the count of new locks written (upgrades included)."""
    have = existing.get(_hitter_slug(name), {})
    new_locks = 0
    for d in days:
        if d.get("status") not in ("final", "in_progress"):
            continue                      # not yet played → still mutable
        date = d.get("date")
        if not date or date > today_iso:
            continue
        prior = have.get(date)
        is_baseline = (isinstance(prior, dict)
                       and bool((prior.get("model") or {}).get("allMlb")))
        if prior is not None and not is_baseline:
            continue                      # factor-adjusted lock already frozen
        model_out = dict(model)
        if is_baseline:
            model_out["upgradedFrom"] = "allMlb"
        set_locked_hitter_projection(season, period, name, date, {
            "name":    name,
            "fpts":    d["proj"],
            "base":    d["base"],
            "factors": d["factors"],
            "matchup": {
                "opp":        d["opp"],
                "isHome":     d["home"],
                "oppStarter": d["oppStarter"],
                "oppHand":    d["oppHand"],
            },
            "model":   model_out,
        }, overwrite=is_baseline)
        new_locks += 1
    return new_locks

# ESPN baseball lineup/eligible slot IDs. Hitters occupy 0–12; pitchers 13–15.
HITTER_SLOTS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

# FA injuryStatus display labels + zero-while-IL set (Phase A, June 13).
# Mirrors api/espn.py's INJ_LABEL_MAP / IL_ZERO_STATUSES (small intentional
# duplicate — the two modules don't otherwise import each other). DTD keeps
# projecting; unknown statuses fall through unzeroed.
FA_INJ_LABEL_MAP = {
    "ACTIVE": "Active", "NORMAL": "Active",
    "TEN_DAY_DL": "IL10", "FIFTEEN_DAY_DL": "IL15", "SIXTY_DAY_DL": "IL60",
    "DAY_TO_DAY": "DTD", "SUSPENSION": "SUSP",
}
FA_IL_ZERO_STATUSES = {"IL10", "IL15", "IL60"}

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


def _eligible_positions(eligible: set) -> str:
    """All eligible defensive positions from eligibleSlots, joined by '/'
    (e.g. '1B/OF'), so the UI can show and filter multi-position eligibility.

    DH (11) is appended only when no fielding position applies — nearly every
    hitter is DH-eligible, so listing it everywhere would just be noise. UTIL
    (12) is a lineup slot, not a position, and is ignored. OF subtypes (LF/CF/
    RF) collapse to a single 'OF'."""
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
    league_id = os.environ.get("ESPN_LEAGUE_ID")
    if not league_id:
        raise RuntimeError("Missing env var ESPN_LEAGUE_ID — set it in Vercel project settings (the number in your ESPN league URL)")
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
        il = injured or slot_id == 17
        # Show the real eligible position(s) for IL'd hitters (the IL status
        # rides on a separate pill); `rank` from hitter_slot still sinks them.
        if il:
            pos = _eligible_positions(eligible)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        bats = (player.get("batSide") or {}).get("code", "") if isinstance(player.get("batSide"), dict) else ""
        hitters_meta.append({
            "name": name, "team": team_abbrev, "id": player.get("id"),
            "pos": pos, "rank": rank, "bats": bats, "il": il,
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

    # Phase 6/7 handedness: opposing-starter IDs from the MLB probables feed
    # (covers debut/recalled starters) with a fallback to the cached pitching
    # stats, plus rostered hitter IDs.
    pitching = {}
    try:
        pitching = cache_get(f"cache:mlb-stats:{year_int}") or {}
    except Exception:
        pass
    probable_ids = fetch_probable_pitcher_ids(mp["start"], mp["end"])  # Phase 7 coverage
    opp_ids = set()
    for d in period_dates:
        for tm in schedule.get(d, {}).values():
            nm = (tm.get("opp_starter") or "").strip()
            if not nm:
                continue
            k = strip_accents(nm)
            pid = probable_ids.get(k) or (pitching.get(k) or {}).get("_mlbId")
            if pid:
                opp_ids.add(pid)
    hitter_ids = [(hitting_current.get(nk) or {}).get("_mlbId") for nk in roster_keys]
    hands = load_player_hands(year_int, list(opp_ids) + [i for i in hitter_ids if i])

    # Phase 7: opposing-pitcher quality — Savant pitcher xwOBA-against + league avg.
    pitch_savant = {}
    try:
        pitch_savant = cache_get(f"cache:savant:{year_int}") or {}
    except Exception:
        pass
    _xw = [v.get("xwoba", 0) for v in pitch_savant.values() if isinstance(v, dict) and v.get("xwoba")]
    league_xwoba = round(sum(_xw) / len(_xw), 3) if _xw else None

    # Phase 4/5: park is a cheap dict lookup; weather is precomputed in parallel
    # for the unique (host park, future date) combos so it's not fetched inside
    # the per-hitter loop. Keyed by the home team's abbrev (the host park).
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    wx_targets = set()
    for d in period_dates:
        for tm_abbrev, g in schedule.get(d, {}).items():
            # Gate on game status ("scheduled" = not yet played) rather than a
            # UTC date compare, so tonight's local games (already UTC-tomorrow)
            # still get a forecast.
            if g.get("is_home") and g.get("status") == "scheduled":
                wx_targets.add((tm_abbrev, d))
    weather_map = {}
    if wx_targets:
        try:
            with ThreadPoolExecutor(max_workers=12) as ex:
                futs = {ex.submit(get_weather_factor, p, dd): (p, dd) for (p, dd) in wx_targets}
                for f in as_completed(futs):
                    try:
                        weather_map[futs[f]] = f.result()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[hitters.py] weather precompute failed: {e}")
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

    # ── Actual / live FPTS for played + in-progress games ─────────────
    # Reuses the pitcher actuals path: per-player applied total per scoring
    # period (cached for completed days, live for today). Roster only — ESPN
    # only exposes a player's FPTS for days they were rostered.
    act_dates = [
        d for d in period_dates
        if any(g.get("status") in ("final", "in_progress") for g in schedule.get(d, {}).values())
    ]
    actual_fpts = {}
    if act_dates:
        try:
            actual_fpts, _s, _b, _mt, _ls = get_actual_fpts(
                act_dates, set(h["name"] for h in hitters_meta), headers, cookies, team_id
            )
        except Exception as e:
            print(f"[hitters.py] hitter actuals fetch failed: {e}")

    # Validate the by-category game-log scoring against ESPN's applied totals on
    # the roster (where both exist) — the basis for trusting it for free agents.
    try:
        checked = match = 0
        for h in hitters_meta:
            la = actuals_from_logs(roster_logs.get(strip_accents(h["name"])), scoring)
            for d, ev in (actual_fpts.get(h["name"]) or {}).items():
                checked += 1
                if abs(la.get(d, 0.0) - ev) <= 0.5:
                    match += 1
        if checked:
            print(f"[hitters.py] actuals validation (game-log vs ESPN): {match}/{checked} match")
    except Exception as e:
        print(f"[hitters.py] actuals validation failed: {e}")

    # ── Persist per-game hitter actuals for the accuracy dashboard ─────
    # Game-log-scored (the validated source above), keyed acth:{date} →
    # {slug: {fpts, stats}}. A date present here means the hitter PLAYED that
    # day, so DNP games (no log entry) are excluded for free — the proj2h lock
    # gets matched against this in /api/accuracy. Scoped to this period's
    # played dates so we don't rewrite the whole season on each load; read-
    # merge-write so loads for different rosters don't clobber each other.
    period_set = set(period_dates)
    acth_by_date: dict = {}
    for h in hitters_meta:
        logs = roster_logs.get(strip_accents(h["name"]))
        if not logs:
            continue
        for d, ev in actuals_with_stats_from_logs(logs, scoring).items():
            if d in period_set and d <= today_iso:
                acth_by_date.setdefault(d, {})[_hitter_slug(h["name"])] = ev
    acth_written = 0
    for d, players in acth_by_date.items():
        key = f"acth:{d}"
        existing = cache_get(key) or {}
        merged = {**existing, **players}
        if merged != existing:
            cache_set(key, merged)          # permanent, like proj2h
            acth_written += len(players)
    if acth_written:
        print(f"[hitters.py] Wrote {acth_written} hitter actual(s) "
              f"across {len(acth_by_date)} date(s)")

    # ── Assemble output ───────────────────────────────────────────────
    # Pre-fetch this period's locked hitter projections once so the per-day
    # freeze below only writes genuinely new locks (see _lock_started_days).
    existing_hit_locks = get_all_locked_hitter_projections(year_int, week)
    hit_locks_new = 0
    # Phase B: real IL grade + est. return date from the public injuries feed,
    # joined by ESPN id. Degrades to {} (bare "IL") if the feed is unreachable.
    injuries = get_injuries()
    roster_hitters = []
    for h in hitters_meta:
        name = h["name"]
        p = proj.get(name, {})
        per_game = p.get("projPerGame", 0.0)
        season = _season_line(hitting_current.get(strip_accents(name), {}))
        overall_ops = (season["obp"] + season["slg"]) if season else None
        bats = (hands.get(strip_accents(name)) or {}).get("bats") or h["bats"]
        inj = injuries.get(h["id"]) if h["il"] else None
        il_return = inj.get("returnDate") if inj else None
        # Per-day cells with the matchup factor stack (Phase 6 platoon + Phase 7 opp SP).
        # IL'd hitters zero only through their return date (Phase B), not the whole week.
        days = _build_days(name, h["team"], h["gameDates"], schedule, per_game,
                           hands, splits, overall_ops, pitch_savant, league_xwoba,
                           weather_map, today_iso, actual_fpts,
                           il_zero=h["il"], il_return=il_return)
        # Freeze each started game's projection for the accuracy dashboard.
        hit_locks_new += _lock_started_days(
            year_int, week, name, days,
            {"type": p.get("modelType", "stats"),
             "blendWeight": p.get("blendWeight", 0.0),
             "recentForm": p.get("recentForm")},
            today_iso, existing_hit_locks,
        )
        proj_week = round(sum(d["proj"] for d in days), 1)
        act_week = round(sum(d["actual"] for d in days if d.get("actual") is not None), 1)
        roster_hitters.append({
            "name":        name,
            "team":        h["team"],
            "pos":         h["pos"],
            "rank":        h["rank"],
            "bats":        bats,
            # Phase B: the injuries feed supplies the real IL grade + est. return
            # for rostered hitters (the fantasy roster feed's injuryStatus is
            # empty — KNOWLEDGE.md). Falls back to a bare "IL" if unmatched.
            "injuryStatus": ((inj.get("grade") if inj else None) or "IL") if h["il"] else None,
            "estReturn":    il_return,
            "injuryDetail": inj.get("detail") if inj else None,
            "projFpts":    proj_week,
            "actualFpts":  act_week,
            "projPerGame": round(per_game, 1),
            "blendWeight": p.get("blendWeight", 0.0),
            "modelType":   p.get("modelType", "stats"),
            "recentForm":  p.get("recentForm"),
            "games":       p.get("games", len(h["gameDates"])),
            "seasonStats": season,
            "advanced":    _advanced_line(name, savant_current, savant_statcast),
            "days":        days,
        })

    if hit_locks_new:
        print(f"[hitters.py] Locked {hit_locks_new} new hitter projection(s) "
              f"(season {year_int}, period {week})")

    # Match ESPN's roster order: by lineup-slot rank, ties broken by projection.
    roster_hitters.sort(key=lambda x: (x["rank"], -x["projFpts"]))

    # ── Free-agent hitters (top available by ownership %) ─────────────
    free_agent_hitters = _fetch_fa_hitters(
        base, headers, cookies, PRO_TEAM_MAP, data.get("scoringPeriodId", week),
        schedule, period_dates, scoring, hitting_current, hitting_previous,
        savant_current, savant_previous, savant_statcast, hands,
        pitch_savant, league_xwoba, weather_map, today_iso, year_int, week,
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
        "leagueAvg":     _league_avg(savant_current, savant_statcast),
        "scoringStats":  sorted(scoring.keys()),
        "computedAt":    datetime.now(timezone.utc).isoformat(),
    }


def _fetch_fa_hitters(base, headers, cookies, PRO_TEAM_MAP, current_week,
                      schedule, period_dates, scoring, hitting_current,
                      hitting_previous, savant_current, savant_previous,
                      savant_statcast, hands, pitch_savant, league_xwoba,
                      weather_map, today_iso, year_int, week):
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
            inj = FA_INJ_LABEL_MAP.get(player.get("injuryStatus", "ACTIVE"),
                                       player.get("injuryStatus", "ACTIVE"))
            meta.append({
                "name": name, "team": team_abbrev, "id": player.get("id"),
                "pos": _eligible_positions(eligible), "ownPct": own, "inj": inj,
                "gameDates": [d for d in period_dates if team_abbrev and team_abbrev in schedule.get(d, {})],
            })

        fa_keys = [strip_accents(h["name"]) for h in meta]
        fa_logs = load_hitter_game_logs(year_int, hitting_current, fa_keys)
        fa_splits = load_hitter_splits(year_int, hitting_current, fa_keys)
        # FA actuals: computed by category from the MLB game logs (ESPN won't
        # expose FPTS for unrostered players). Keyed by display name.
        fa_actuals = {h["name"]: actuals_from_logs(fa_logs.get(strip_accents(h["name"])), scoring) for h in meta}
        proj, _ = get_projected_hitter_fpts(
            [{"name": h["name"], "team": h["team"], "gameDates": h["gameDates"]} for h in meta],
            scoring=scoring, stat_current=hitting_current, stat_previous=hitting_previous,
            savant_current=savant_current, savant_previous=savant_previous,
            game_logs=fa_logs,
            season=year_int, period=week,
        )

        # Phase B: enrich FA injury labels with the feed's grade + est. return
        # (the kona path gives a grade but no return date). Joined by ESPN id.
        injuries = get_injuries()
        out = []
        for h in meta:
            p = proj.get(h["name"], {})
            per_game = p.get("projPerGame", 0.0)
            season = _season_line(hitting_current.get(strip_accents(h["name"]), {}))
            overall_ops = (season["obp"] + season["slg"]) if season else None
            bats = (hands.get(strip_accents(h["name"])) or {}).get("bats", "")
            finj = injuries.get(h["id"])
            # Prefer the feed grade; fall back to the kona label.
            inj_label = (finj.get("grade") if finj else None) or h["inj"]
            il_return = finj.get("returnDate") if finj else None
            days = _build_days(h["name"], h["team"], h["gameDates"], schedule, per_game,
                               hands, fa_splits, overall_ops, pitch_savant, league_xwoba,
                               weather_map, today_iso, fa_actuals,
                               il_zero=(inj_label in FA_IL_ZERO_STATUSES), il_return=il_return)
            out.append({
                "name": h["name"], "team": h["team"], "pos": h["pos"], "bats": bats,
                "percentOwned": h["ownPct"],
                "injuryStatus": inj_label,
                "estReturn": il_return,
                "injuryDetail": finj.get("detail") if finj else None,
                "projFpts": round(sum(d["proj"] for d in days), 1), "projPerGame": round(per_game, 1),
                "actualFpts": round(sum(d["actual"] for d in days if d.get("actual") is not None), 1),
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
#   v18: remove temp _diag block.
#   v19: Phase 7 — opposing-pitcher quality factor + probable-id starter coverage.
#   v20: Phase 4/5 — park + weather per-day factors.
#   v21: gate weather on game status (scheduled), not UTC date (today boundary).
#   v22: capture actual/live FPTS per day (roster) — status + actual on day cells.
#   v23: FA actuals computed from game logs by category (ESPN can't expose them).
#   v24: Phase A IL-awareness — FA injuryStatus label + IL ×0 day factor (roster + FA).
#   v25: roster IL hitters keep real position + carry injuryStatus "IL" (split pill).
#   v26: Phase B — real IL grade + est. return (injuries feed, ESPN-id join);
#        IL days zero only through the return date (roster + FA).
HITTER_CACHE_VERSION = 26


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
    league_id = os.environ.get("ESPN_LEAGUE_ID")
    if not league_id:
        raise RuntimeError("Missing env var ESPN_LEAGUE_ID — set it in Vercel project settings (the number in your ESPN league URL)")
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


# ─── League rosters viewer (trade engine Phase 1) ─────────────────────────────
# Lives here, served as /api/hitters?view=league, because a standalone
# api/league.py can't import its sibling modules on Vercel (the builder doesn't
# bundle them for newly-added endpoint files). This endpoint already bundles the
# hitter + (via the import above) pitcher projection stack, so the league
# assembly rides along. Read-only; no opponent schedule grid (out of scope).

LEAGUE_SEASON_GAMES = 162
LEAGUE_FULL_SEASON_STARTS = 32   # mirrors StatsTable.tsx FULL_SEASON_STARTS
LEAGUE_PITCHER_SLOTS = {13, 14}  # 14=SP, 13=RP
LEAGUE_CACHE_TTL = 1800


def _league_cache_key(year: int) -> str:
    # v2: rows now carry trade-engine fields (surfaceRate/horizon/fullHorizon/
    # recentHeat) — bump so stale pre-trade-engine payloads aren't served.
    return f"cache:league-roster:v2:{year}"


def _lg_safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _lg_pitcher_season_stats(stat_dict: dict):
    """Pitcher season line (copied from espn.py — see module note)."""
    if not stat_dict:
        return None
    ip = parse_ip(stat_dict.get("inningsPitched", "0.0"))
    if ip <= 0:
        return None
    so = int(stat_dict.get("strikeOuts", 0)); bb = int(stat_dict.get("baseOnBalls", 0))
    w = int(stat_dict.get("wins", 0)); l = int(stat_dict.get("losses", 0))
    hits = _lg_safe_float(stat_dict.get("hits", 0)); er = _lg_safe_float(stat_dict.get("earnedRuns", 0))
    hbp = _lg_safe_float(stat_dict.get("hitBatsmen", stat_dict.get("hitByPitch", 0)))
    sv = _lg_safe_float(stat_dict.get("saves", 0))
    season_fpts = ip * 3 + so - hits - bb + er * -2 - hbp + sv * 5 + w * 5 + l * -5
    return {"w": w, "l": l, "era": _lg_safe_float(stat_dict.get("era", 0)),
            "k9": round(so / ip * 9, 2), "bb9": round(bb / ip * 9, 2),
            "sv": int(sv), "ip": round(ip, 1), "gs": int(stat_dict.get("gamesStarted", 0)),
            "seasonFptsToDate": round(season_fpts, 1)}


def _lg_pitcher_savant(expected: dict, statcast: dict, whiff_pct: float = 0.0):
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


def _lg_pitcher_fpts_history(games: list, n_starts: int = 10):
    if not games:
        return None
    starts = [g for g in games if g.get("gs", 0) >= 1]
    if len(starts) < 2:
        return None
    return [round(g["ip"] * 3 + g["so"] - g["h"] - g["bb"] + g["er"] * -2
                  - g["hb"] + g["w"] * 5 + g["l"] * -5 + g["sv"] * 5, 1)
            for g in starts[-n_starts:]]


def _lg_slot_label(eligible: set, injured: bool) -> str:
    if injured: return "IL"
    if 14 in eligible: return "SP"
    if 13 in eligible and 14 not in eligible: return "RP"
    return "P"


def _lg_pos_eligible(eligible: set) -> str:
    out = []
    if 14 in eligible: out.append("SP")
    if 15 in eligible: out.append("RP")
    return "/".join(out) or "P"


def _lg_games_remaining(team_win_data: dict, abbrev: str):
    info = team_win_data.get(abbrev)
    if not info:
        return None
    return max(0, LEAGUE_SEASON_GAMES - int(info.get("games", 0)))


def _lg_team_meta(team: dict, members_by_id: dict) -> dict:
    name = (team.get("name") or
            f"{team.get('location', '')} {team.get('nickname', '')}").strip()
    owners = team.get("owners") or []
    owner = members_by_id.get(owners[0], "") if owners else ""
    rec = (team.get("record") or {}).get("overall") or {}
    w, l = rec.get("wins"), rec.get("losses")
    record = f"{w}-{l}" if w is not None and l is not None else ""
    return {"id": team.get("id"), "name": name or f"Team {team.get('id')}",
            "owner": owner, "record": record}


def _lg_build_team(team, cd, hd, scoring, PRO_TEAM_MAP, year_int, week, pick_by_id=None):
    pick_by_id = pick_by_id or {}
    entries = team.get("roster", {}).get("entries", [])
    pitchers_raw, hitters_raw = [], []
    for entry in entries:
        player = entry.get("playerPoolEntry", {}).get("player", {})
        if not player.get("fullName"):
            continue
        eligible = set(player.get("eligibleSlots", []))
        if eligible & LEAGUE_PITCHER_SLOTS:
            pitchers_raw.append((player, eligible))
        elif eligible & HITTER_SLOTS:
            hitters_raw.append((player, eligible))

    pitcher_inputs = [{
        "name": p.get("fullName"), "team": PRO_TEAM_MAP.get(p.get("proTeamId", 0), ""),
        "starts": 0, "startDates": [], "is_rp": 13 in e and 14 not in e,
    } for p, e in pitchers_raw]
    _pf, _pb, fpts_per_start, _pd = get_projected_fpts(
        pitcher_inputs, cd.get("team_woba_factors", {}), season=year_int, period=week,
        today_str=datetime.now().strftime("%Y-%m-%d"),
        savant_current=cd.get("savant_current"), savant_previous=cd.get("savant_previous"),
        mlb_stats_current=cd.get("mlb_stats_current"), mlb_stats_previous=cd.get("mlb_stats_previous"),
        game_logs=cd.get("game_logs_current"), team_win_data=cd.get("team_win_data"),
        schedule={},
    ) if pitcher_inputs else ({}, {}, {}, {})

    pitchers = []
    for player, eligible in pitchers_raw:
        name = player.get("fullName"); nk = strip_accents(name)
        injured = player.get("injured", False)
        ss = _lg_pitcher_season_stats(cd.get("mlb_stats_current", {}).get(nk, {}))
        gs = (ss or {}).get("gs", 0); per = fpts_per_start.get(name, 0.0)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        # seasonBase = the de-lucked per-start rate BEFORE the 60/40 recent-form
        # blend — the basis for the trade engine's "model ROS value" axis.
        season_base = (_pd.get(name) or {}).get("seasonBase")
        if 14 in eligible:
            horizon = max(0, LEAGUE_FULL_SEASON_STARTS - gs)
            ros = round(per * horizon, 1)
            produced = per * gs
            full_horizon = LEAGUE_FULL_SEASON_STARTS
        else:
            apps = int(cd.get("mlb_stats_current", {}).get(nk, {}).get("gamesPlayed", 0))
            tgr = _lg_games_remaining(cd.get("team_win_data", {}), team_abbrev)
            tgp = (cd.get("team_win_data", {}).get(team_abbrev) or {}).get("games", 0)
            horizon = (apps * tgr / tgp) if (tgr and tgp) else 0
            ros = round(per * horizon, 1) if (tgr and tgp) else None
            produced = per * apps
            full_horizon = apps + horizon
        sb_ros = round(season_base * horizon, 1) if (season_base is not None and horizon) else None
        # Recent-form heat: how far the 60/40-blended rate runs above/below the
        # de-lucked base. Opposing managers extrapolate it → feeds perceived value.
        heat = max(-0.5, min(0.5, (per - season_base) / season_base)) if season_base else 0.0
        full_pace = (round(season_base * full_horizon, 1) if (season_base is not None and full_horizon)
                     else round(produced + (ros or 0), 1))
        pitchers.append({
            "name": name, "team": team_abbrev,
            "slot": _lg_slot_label(eligible, injured),
            "posEligible": _lg_pos_eligible(eligible),
            "injuryStatus": "IL" if injured else "Active",
            "projFpts": round(per, 1), "rosFpts": ros,
            "seasonBaseRos": sb_ros,
            "fullSeasonPace": full_pace, "recentHeat": round(heat, 3),
            "surfaceRate": round(per, 3), "horizon": round(horizon, 2),
            "fullHorizon": round(full_horizon, 2),
            "draftPick": pick_by_id.get(player.get("id")),
            "adp": (player.get("ownership") or {}).get("averageDraftPosition"),
            "seasonStats": ss,
            "savantExpected": _lg_pitcher_savant(
                cd.get("savant_current", {}).get(nk, {}),
                cd.get("savant_statcast_current", {}).get(nk, {}),
                cd.get("savant_whiff_current", {}).get(nk, 0.0)),
            "fptsHistory": _lg_pitcher_fpts_history(cd.get("game_logs_current", {}).get(nk, [])),
        })
    pitchers.sort(key=lambda p: -(p["rosFpts"] or p["projFpts"] or 0))

    hitter_inputs = [{
        "name": p.get("fullName"), "team": PRO_TEAM_MAP.get(p.get("proTeamId", 0), ""),
        "gameDates": [],
    } for p, e in hitters_raw]
    # Game logs unlock the 60/40 recent-form blend (the League view passed {});
    # we keep the displayed ROS de-lucked but use the blend to derive recentHeat.
    hitter_keys = [strip_accents(p.get("fullName")) for p, e in hitters_raw]
    try:
        hit_logs = load_hitter_game_logs(year_int, hd.get("hitting_current"), hitter_keys) if hitter_keys else {}
    except Exception:
        hit_logs = {}   # degrade to de-lucked (no recent-form heat) rather than 500
    hproj, hdet = get_projected_hitter_fpts(
        hitter_inputs, scoring=scoring,
        stat_current=hd.get("hitting_current"), stat_previous=hd.get("hitting_previous"),
        savant_current=hd.get("savant_batter_current"), savant_previous=hd.get("savant_batter_previous"),
        game_logs=hit_logs, season=year_int, period=week,
    ) if hitter_inputs else ({}, None)

    batters = []
    for player, eligible in hitters_raw:
        name = player.get("fullName"); nk = strip_accents(name)
        team_abbrev = PRO_TEAM_MAP.get(player.get("proTeamId", 0), "")
        per_game = hproj.get(name, {}).get("projPerGame", 0.0)   # 60/40 blended
        bats = (player.get("batSide") or {}).get("code", "") if isinstance(player.get("batSide"), dict) else ""
        tgr = _lg_games_remaining(cd.get("team_win_data", {}), team_abbrev)
        # seasonBase = de-lucked per-game rate before the recent-form blend. The
        # displayed ROS stays de-lucked (unchanged); the blend only drives heat.
        season_base = (hdet.get(name) or {}).get("seasonBase") if hdet else None
        base_rate = season_base if season_base is not None else per_game
        ros = round(base_rate * tgr, 1) if tgr is not None else None
        sb_ros = round(season_base * tgr, 1) if (season_base is not None and tgr is not None) else None
        heat = max(-0.5, min(0.5, (per_game - season_base) / season_base)) if season_base else 0.0
        batters.append({
            "name": name, "team": team_abbrev,
            "pos": _eligible_positions(eligible), "bats": bats,
            "projPerGame": round(base_rate, 1), "rosFpts": ros,
            "seasonBaseRos": sb_ros,
            "fullSeasonPace": round(base_rate * LEAGUE_SEASON_GAMES, 1),
            "recentHeat": round(heat, 3),
            "surfaceRate": round(per_game, 3),
            "horizon": (tgr if tgr is not None else 0), "fullHorizon": LEAGUE_SEASON_GAMES,
            "draftPick": pick_by_id.get(player.get("id")),
            "adp": (player.get("ownership") or {}).get("averageDraftPosition"),
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
    year = os.environ.get("ESPN_SEASON", "2026"); year_int = int(year)
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP = get_pro_team_map(headers, cookies)
    base = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
            f"/seasons/{year}/segments/0/leagues/{league_id}")
    r = requests.get(base, params=[("view", "mRoster"), ("view", "mTeam"),
                                   ("view", "mSettings"), ("view", "mDraftDetail")],
                     cookies=cookies, headers=headers, timeout=20)
    if r.status_code in (401, 403):
        raise Exception(f"ESPN returned HTTP {r.status_code} — auth failed (check ESPN_S2/ESPN_SWID).")
    if r.status_code != 200:
        raise Exception(f"ESPN returned HTTP {r.status_code}")
    data = r.json()
    week = data.get("scoringPeriodId", 1)
    members_by_id = {m.get("id"): (m.get("displayName") or "").strip() for m in data.get("members", [])}
    scoring = parse_hitter_scoring(data)
    # Draft slot → the trade engine's strongest perceived-value anchor. Static for
    # the season; comes free on the same league fetch via the mDraftDetail view.
    pick_by_id = {}
    for pk in ((data.get("draftDetail") or {}).get("picks") or []):
        pid, ov = pk.get("playerId"), pk.get("overallPickNumber")
        if pid and ov:
            pick_by_id[pid] = ov
    cd = load_cached_data(year_int)
    hd = load_hitter_stats(year_int)
    teams_out = []
    for team in data.get("teams", []):
        teams_out.append({**_lg_team_meta(team, members_by_id),
                          **_lg_build_team(team, cd, hd, scoring, PRO_TEAM_MAP, year_int, week, pick_by_id)})
    teams_out.sort(key=lambda t: t["name"].lower())
    return {"teams": teams_out, "week": week, "generatedAt": datetime.utcnow().isoformat() + "Z"}


def _league_response() -> dict:
    year = int(os.environ.get("ESPN_SEASON", "2026"))
    try:
        cached = cache_get(_league_cache_key(year))
        if cached:
            return cached
    except Exception:
        pass
    payload = build_league_rosters()
    try:
        cache_set(_league_cache_key(year), payload, ttl_seconds=LEAGUE_CACHE_TTL)
    except Exception:
        pass
    return payload


# ──────────────────────────────────────────────────────────────────────────
# Trade engine — Phase 2 (perceived-value arbitrage)
#
# Two axes per player, kept deliberately separate:
#   • model ROS value — de-lucked rest-of-season FPTS (seasonBaseRos: the
#     Savant-de-lucked rate × remaining-games horizon, WITHOUT the 60/40
#     recent-form blend). This is the truth.
#   • perceived value — what an opposing manager prices the player at: a
#     time-varying blend of draft slot (their own league-draft anchor),
#     current full-season production, and ADP, with a light positional-scarcity
#     tilt. Expressed in FPTS-equivalent so the edge reads in one currency.
#
# The Skipper edge = balance the PERCEIVED axis (so a trade looks fair and the
# other manager accepts) while winning the MODEL axis (real ROS FPTS gained).
#
# v1 scope: replacement-level netting and a numeric IL haircut are deferred to
# v1.1 (injured players are flagged, not yet discounted); preseason-proj
# reach/fall is v2 (FanGraphs CSV). These show up in summary.model.caveats.
# ──────────────────────────────────────────────────────────────────────────

TRADE_SEASON_OPEN = datetime(2026, 3, 25)
TRADE_SEASON_DAYS = 183            # ~opening day → late September
TRADE_ACCEPT_CUSHION = 0.05        # bias proposals 5% perceived-favorable to them
TRADE_EDGE_MIN = 8.0               # ROS FPTS edge below which a deal isn't worth it
TRADE_FAIR_BAND = 0.08             # perceived imbalance within 8% reads as "fair"
TRADE_RECENCY_OVERREACTION = 0.5   # managers extrapolate hot/cold streaks past their weight
TRADE_SANITY_EDGE = 60.0           # ROS edge above which a "fair" deal is flagged suspect

# Light positional-scarcity tilt on perceived value (deep pools < 1, scarce > 1).
TRADE_SCARCITY_MULT = {
    "C": 1.06, "SS": 1.04, "2B": 1.02, "3B": 1.00, "1B": 0.98,
    "OF": 0.98, "DH": 0.96, "SP": 1.00, "RP": 1.00, "P": 1.00,
}


def _trade_season_progress():
    """Season fraction elapsed (0..1) — drives the time-varying weights."""
    try:
        elapsed = (datetime.now() - TRADE_SEASON_OPEN).days
    except Exception:
        elapsed = 0
    return max(0.0, min(1.0, elapsed / TRADE_SEASON_DAYS))


def _trade_weights(p):
    """Time-varying perceived-value weights. Early season anchors on the draft;
    perception migrates toward in-season production as p (progress) grows."""
    w_prod = max(0.30, min(0.75, 0.30 + 0.45 * p))
    w_anchor = 1.0 - w_prod
    return {"prod": w_prod, "draft": w_anchor * 0.8, "adp": w_anchor * 0.2}


def _fit_log_curve(points):
    """OLS log-log fit value ≈ exp(b0 + b1·ln(pick)). Returns curve(pick)→value,
    or None if too few/degenerate points. Used to turn a draft slot (or ADP)
    into an FPTS-equivalent value with the right convex decay."""
    import math
    pts = [(math.log(pk), math.log(v)) for pk, v in points
           if pk and pk > 0 and v and v > 0]
    n = len(pts)
    if n < 4:
        return None
    sx = sum(x for x, _ in pts); sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts); sxy = sum(x * y for x, y in pts)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    def curve(pick):
        if not pick or pick <= 0:
            return None
        return math.exp(intercept + slope * math.log(pick))
    return curve


def _pos_group(row):
    pos = (row.get("pos") or row.get("posEligible") or "").upper()
    for g in ("C", "SS", "2B", "3B", "1B", "OF", "DH", "SP", "RP"):
        if g in pos:
            return g
    return "P" if "P" in pos else (pos.split("/")[0] if pos else "")


def _perceived_components(row, curve, weights):
    """Perceived rest-of-season value (FPTS) with its factor breakdown — same
    horizon/scale as model ROS, so the fairness ratio is apples-to-apples with
    the edge. Blends, as RATES: surface production (what they see, incl. recent-
    form overreaction), draft-slot pedigree, ADP; renorms over present
    components; × scarcity; × horizon. Returns None if there's nothing to value."""
    horizon, full_h = row.get("horizon"), row.get("fullHorizon")
    if not horizon or not full_h:
        return None
    heat = row.get("recentHeat") or 0.0
    surface = row.get("surfaceRate")
    surface_adj = surface * (1.0 + TRADE_RECENCY_OVERREACTION * heat) if surface is not None else None
    # Draft / ADP curves return a full-season value → divide to a per-game rate.
    draft_rate = (curve(row.get("draftPick")) / full_h) if (curve and row.get("draftPick")) else None
    adp_rate = (curve(row.get("adp")) / full_h) if (curve and row.get("adp")) else None
    parts, acc, wsum = [], 0.0, 0.0
    for label, val, w in (("Surface production", surface_adj, weights["prod"]),
                          ("Draft pedigree", draft_rate, weights["draft"]),
                          ("ADP", adp_rate, weights["adp"])):
        if val is not None:
            acc += w * val; wsum += w
            parts.append({"label": label, "rate": round(val, 2), "rawWeight": w})
    if wsum <= 0:
        return None
    mult = TRADE_SCARCITY_MULT.get(_pos_group(row), 1.0)
    rate = (acc / wsum) * mult
    for pt in parts:                       # normalize to present components + ROS contribution
        pt["weight"] = round(pt["rawWeight"] / wsum, 3)
        pt["ros"] = round(pt["rate"] * (pt["rawWeight"] / wsum) * mult * horizon, 1)
        pt.pop("rawWeight", None)
    return {"perceived": round(rate * horizon, 1), "horizon": round(horizon, 1),
            "scarcityMult": mult, "recentHeat": round(heat, 3), "components": parts}


def _perceived_value(row, curve, weights):
    b = _perceived_components(row, curve, weights)
    return b["perceived"] if b else None


def _classify_trade(edge, perc_give, perc_get):
    """Deterministic verdict. `give` is what we send the counterparty, so THEY
    perceive a win when perc_give ≥ perc_get. The cushion sweetens that for them."""
    perc_balance = round(perc_give - perc_get, 1)
    perc_ratio = perc_give / max(perc_get, 1.0)
    fair = perc_ratio >= (1.0 - TRADE_FAIR_BAND)
    sweetened = perc_ratio >= (1.0 + TRADE_ACCEPT_CUSHION)
    if edge >= TRADE_EDGE_MIN and fair:
        verdict = "steal" if sweetened else "win"
    elif edge >= TRADE_EDGE_MIN and not fair:
        verdict = "lopsided"
    elif edge <= -TRADE_EDGE_MIN:
        verdict = "avoid"
    else:
        verdict = "marginal"
    return {"perceivedBalance": perc_balance, "perceivedRatio": round(perc_ratio, 3),
            "fairToThem": fair, "sweetened": sweetened, "verdict": verdict}


def _flatten_league(payload):
    """name(normalized) → enriched player row, across all teams & both groups."""
    idx = {}
    for t in payload.get("teams", []):
        owner = t.get("name", "")
        for grp in ("pitchers", "batters"):
            for pl in t.get(grp, []):
                idx[strip_accents(pl.get("name", ""))] = {**pl, "owner": owner, "kind": grp}
    return idx


def _resolve_players(names, idx):
    found, missing = [], []
    for nm in names:
        row = idx.get(strip_accents(nm or ""))
        if row:
            found.append(row)
        else:
            missing.append(nm)
    return found, missing


def build_trade_eval(give_players, get_players, with_team_id=None, want_rationale=False):
    """Evaluate a give/get trade on both axes. Returns per-player + per-side
    numbers, a deterministic verdict, and (optionally) a Claude pitch."""
    payload = _league_response()
    idx = _flatten_league(payload)
    give_rows, give_missing = _resolve_players(give_players, idx)
    get_rows, get_missing = _resolve_players(get_players, idx)
    if give_missing or get_missing:
        return {"error": "Unrecognized player name(s)",
                "unmatched": give_missing + get_missing,
                "hint": "Use full names exactly as they appear in the League view."}
    if not give_rows or not get_rows:
        return {"error": "Both sides of the trade need at least one player."}

    # Fit the draft-value curve from every rostered player with a pick + pace.
    pts = [(r.get("draftPick"), r.get("fullSeasonPace")) for r in idx.values()
           if r.get("draftPick") and r.get("fullSeasonPace")]
    curve = _fit_log_curve(pts)
    p = _trade_season_progress()
    weights = _trade_weights(p)

    def enrich(r):
        model = r.get("seasonBaseRos")
        if model is None:
            model = r.get("rosFpts")          # fallback if de-lucked base missing
        comp = _perceived_components(r, curve, weights)
        pv = comp["perceived"] if comp else None
        injured = (r.get("injuryStatus") or "").upper() not in ("", "ACTIVE")
        # ROS FPTS earned per unit of perceived value — scale-robust arbitrage
        # signal. High = undervalued (acquire); low = overvalued (move).
        ratio = round(model / pv, 3) if (model is not None and pv) else None
        hz = r.get("horizon")
        base_rate = round(model / hz, 2) if (model is not None and hz) else None
        return {"name": r.get("name"), "owner": r.get("owner"), "team": r.get("team"),
                "pos": r.get("pos") or r.get("posEligible"),
                "modelRos": round(model, 1) if model is not None else None,
                "perceived": pv, "blendedRos": r.get("rosFpts"),
                "draftPick": r.get("draftPick"), "valueRatio": ratio,
                "injured": injured, "injuryStatus": r.get("injuryStatus"),
                "breakdown": {
                    "model": {"baseRate": base_rate, "horizon": round(hz, 1) if hz else None,
                              "recentHeat": r.get("recentHeat"),
                              "note": "Savant de-lucked rate × remaining horizon (no recent-form blend)"},
                    "perceived": comp,
                }}

    give_e = [enrich(r) for r in give_rows]
    get_e = [enrich(r) for r in get_rows]
    _s = lambda rows, k: round(sum((x.get(k) or 0) for x in rows), 1)
    model_give, model_get = _s(give_e, "modelRos"), _s(get_e, "modelRos")
    perc_give, perc_get = _s(give_e, "perceived"), _s(get_e, "perceived")

    edge = round(model_get - model_give, 1)
    cls = _classify_trade(edge, perc_give, perc_get)
    blurb = {
        "steal": f"Steal — you gain {edge:+} ROS FPTS and they perceive it as a win.",
        "win": f"Good deal — {edge:+} ROS FPTS and it reads as fair to them.",
        "lopsided": f"{edge:+} ROS FPTS for you, but you're perceived as winning by "
                    f"{abs(cls['perceivedBalance'])} — they may balk. Sweeten it.",
        "avoid": f"Pass — you lose {abs(edge)} ROS FPTS.",
        "marginal": f"Marginal — only {edge:+} ROS FPTS; not worth the roster churn.",
    }[cls["verdict"]]

    caveats = ["Replacement-level netting is deferred to v1.1."]
    if any(x["injured"] for x in give_e + get_e):
        caveats.append("Injured players are flagged but not yet numerically discounted (v1.1).")
    if not any(r.get("adp") for r in idx.values()):
        caveats.append("ADP unavailable from the roster feed; draft slot carries the anchor.")

    result = {
        "give": give_e, "get": get_e,
        "summary": {"modelGive": model_give, "modelGet": model_get, "edge": edge,
                    "perceivedGive": perc_give, "perceivedGet": perc_get,
                    "blurb": blurb, **cls},
        "model": {"seasonProgress": round(p, 3),
                  "weights": {k: round(v, 3) for k, v in weights.items()},
                  "draftCurveFit": curve is not None, "draftCurvePoints": len(pts),
                  "cushion": TRADE_ACCEPT_CUSHION, "caveats": caveats},
        "week": payload.get("week"),
    }
    if want_rationale:
        result["rationale"] = _trade_rationale(result)
    return result


def _trade_rationale(result):
    """Optional Claude pitch — mirrors api/analyze.py's client pattern."""
    try:
        import anthropic
    except Exception:
        return ""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    s = result["summary"]
    give_s = ", ".join(f"{x['name']} (model {x['modelRos']}, perceived {x['perceived']})" for x in result["give"])
    get_s = ", ".join(f"{x['name']} (model {x['modelRos']}, perceived {x['perceived']})" for x in result["get"])
    prompt = (
        "You are a sharp fantasy baseball trade analyst. Two axes matter: MODEL "
        "ROS FPTS (the truth) and PERCEIVED value (what the other manager prices "
        "players at, anchored on draft slot + current stats). Advise whether to "
        "send this offer and how to pitch it so the other manager accepts. Be "
        "specific and reference the numbers.\n\n"
        f"You GIVE: {give_s}\nYou GET: {get_s}\n"
        f"Your ROS edge: {s['edge']:+} FPTS. Perceived balance (their view): "
        f"{s['perceivedBalance']:+}. Verdict: {s['verdict']}."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        msg = client.messages.create(model=model, max_tokens=600,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if hasattr(b, "text"))
    except Exception as e:
        return f"(rationale unavailable: {type(e).__name__})"


# ──────────────────────────────────────────────────────────────────────────
# Trade finder — Phase 3. Deterministic scan of 1-for-1 / 2-for-1 swaps between
# your roster and other teams, keeping only deals you win on ROS that still read
# fair (or favorable) to them — the same accept-worthy steals the evaluator
# scores, surfaced automatically with every underlying number.
# ──────────────────────────────────────────────────────────────────────────

TRADE_FINDER_POOL_CAP = 20    # per-team players considered (top by model ROS)
TRADE_FINDER_MAX = 12         # proposals returned


def _finder_rank(edge, perc_give, perc_get):
    """Keep deals you win on ROS that they'd accept; steals score above fair wins."""
    cls = _classify_trade(edge, perc_give, perc_get)
    keep = cls["verdict"] in ("steal", "win")
    score = round(edge + (5.0 if cls["verdict"] == "steal" else 0.0), 1)
    return keep, score, cls


def build_trade_finder(my_team_id, target_team_id=None, want_rationale=False,
                       max_results=TRADE_FINDER_MAX):
    from itertools import combinations
    payload = _league_response()
    teams = payload.get("teams", [])
    if not teams:
        return {"error": "League payload is empty."}
    idx = _flatten_league(payload)
    pts = [(r.get("draftPick"), r.get("fullSeasonPace")) for r in idx.values()
           if r.get("draftPick") and r.get("fullSeasonPace")]
    curve = _fit_log_curve(pts)
    p = _trade_season_progress()
    weights = _trade_weights(p)

    def enrich_team(t):
        out = []
        for grp in ("pitchers", "batters"):
            for pl in t.get(grp, []):
                model = pl.get("seasonBaseRos")
                if model is None:
                    model = pl.get("rosFpts")
                pv = _perceived_value(pl, curve, weights)
                if model is None or pv is None:
                    continue
                out.append({"name": pl.get("name"), "pos": pl.get("pos") or pl.get("posEligible"),
                            "model": round(model, 1), "perceived": pv,
                            "injured": (pl.get("injuryStatus") or "").upper() not in ("", "ACTIVE")})
        out.sort(key=lambda x: -x["model"])
        return out[:TRADE_FINDER_POOL_CAP]

    my_team = next((t for t in teams if t.get("id") == my_team_id), None)
    if my_team is None:
        return {"error": f"Team id {my_team_id} not found — set ESPN_TEAM_ID or pass ?myTeam=",
                "teams": [{"id": t.get("id"), "name": t.get("name")} for t in teams]}
    mine = enrich_team(my_team)
    targets = [t for t in teams if t.get("id") != my_team_id
               and (target_team_id is None or t.get("id") == target_team_id)]
    all_teams_scan = target_team_id is None

    candidates = []

    def consider(give_rows, get_rows, owner):
        mg = sum(x["model"] for x in give_rows)
        mt = sum(x["model"] for x in get_rows)
        edge = round(mt - mg, 1)
        if edge < TRADE_EDGE_MIN:          # cheap reject before classifying
            return
        pg = sum(x["perceived"] for x in give_rows)
        pt = sum(x["perceived"] for x in get_rows)
        keep, score, cls = _finder_rank(edge, pg, pt)
        if not keep:
            return
        candidates.append({"with": owner, "give": give_rows, "get": get_rows,
                           "edge": edge, "perceivedBalance": cls["perceivedBalance"],
                           "verdict": cls["verdict"], "score": score})

    for t in targets:
        theirs = enrich_team(t)
        owner = t.get("name")
        for g in mine:
            for r in theirs:
                consider([g], [r], owner)
        for g2 in combinations(mine, 2):
            for r in theirs:
                consider(list(g2), [r], owner)
        # 1-for-2 only on a focused single-team scan (keeps the all-teams sweep bounded)
        if not all_teams_scan:
            for g in mine:
                for r2 in combinations(theirs, 2):
                    consider([g], list(r2), owner)

    # Guardrail: greedily keep the best deal, then suppress any later proposal
    # reusing a player already spent on either side — a diverse matching instead
    # of "every one of my guys for the same target". Flag implausible edges.
    candidates.sort(key=lambda c: -c["score"])
    used_give, used_get, top = set(), set(), []
    for c in candidates:
        gnames = {x["name"] for x in c["give"]}
        rnames = {x["name"] for x in c["get"]}
        if (gnames & used_give) or (rnames & used_get):
            continue
        c["suspect"] = c["edge"] > TRADE_SANITY_EDGE
        top.append(c)
        used_give |= gnames; used_get |= rnames
        if len(top) >= max_results:
            break
    result = {"proposals": top,
              "scanned": {"myTeam": my_team.get("name"),
                          "targets": [t.get("name") for t in targets],
                          "found": len(candidates)},
              "model": {"seasonProgress": round(p, 3), "draftCurveFit": curve is not None,
                        "weights": {k: round(v, 3) for k, v in weights.items()}}}
    if want_rationale and top:
        result["rationale"] = _finder_rationale(top, my_team.get("name"))
    return result


def _finder_rationale(proposals, my_team_name):
    try:
        import anthropic
    except Exception:
        return ""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    lines = [f"You are a fantasy baseball trade strategist for {my_team_name}. Below are "
             "candidate trades that gain rest-of-season FPTS while reading fair/favorable "
             "to the other manager (model = de-lucked ROS truth; perceived = how they price "
             "players). Rank the best 5 and give a one-line pitch for each.\n"]
    for i, c in enumerate(proposals[:10], 1):
        g = ", ".join(x["name"] for x in c["give"])
        r = ", ".join(x["name"] for x in c["get"])
        lines.append(f"{i}. with {c['with']}: give {g} → get {r} "
                     f"(edge {c['edge']:+}, perceived {c['perceivedBalance']:+}, {c['verdict']})")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        msg = client.messages.create(model=model, max_tokens=800,
                                     messages=[{"role": "user", "content": "\n".join(lines)}])
        return "".join(b.text for b in msg.content if hasattr(b, "text"))
    except Exception as e:
        return f"(rationale unavailable: {type(e).__name__})"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs      = parse_qs(urlparse(self.path).query)

        # League rosters viewer — isolated branch, returns early (the default
        # hitter path below is untouched).
        if qs.get("view", [""])[0] == "league":
            try:
                body = _league_response()
            except Exception as e:
                import traceback
                body = {"error": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-1500:]}
            self.send_response(200 if "error" not in body else 500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
            return

        # Trade evaluator / finder — GET form for quick testing:
        #   ?view=trade&give=Name A,Name B&get=Name C&rationale=0
        #   ?view=trade&mode=find[&team=<id>][&myTeam=<id>][&rationale=1]
        if qs.get("view", [""])[0] == "trade":
            want = qs.get("rationale", ["0"])[0] in ("1", "true")
            if qs.get("mode", [""])[0] == "find":
                my_tid = int((qs.get("myTeam", [""])[0] or os.environ.get("ESPN_TEAM_ID", "0")) or 0)
                tgt = qs.get("team", [""])[0]
                self._send_finder(my_tid, int(tgt) if tgt.isdigit() else None, want)
                return
            give = [g for g in (qs.get("give", [""])[0]).split(",") if g.strip()]
            get_ = [g for g in (qs.get("get", [""])[0]).split(",") if g.strip()]
            self._send_trade(give, get_, qs.get("team", [None])[0], want)
            return

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

    def do_POST(self):
        qs = parse_qs(urlparse(self.path).query)
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        if qs.get("view", [""])[0] == "trade" or data.get("view") == "trade":
            want = bool(data.get("rationale"))
            if data.get("mode") == "find" or qs.get("mode", [""])[0] == "find":
                my_tid = int(data.get("myTeam") or os.environ.get("ESPN_TEAM_ID", "0") or 0)
                tgt = data.get("targetTeamId")
                self._send_finder(my_tid, int(tgt) if str(tgt).isdigit() else None, want)
                return
            self._send_trade(data.get("give", []), data.get("get", []),
                             data.get("withTeamId"), want)
            return
        self._send_json(404, {"error": "Unknown POST endpoint"})

    def _send_json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _send_trade(self, give, get_, team, want_rationale):
        try:
            body = build_trade_eval(give or [], get_ or [], team, want_rationale)
        except Exception as e:
            import traceback
            body = {"error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc()[-1500:]}
        self._send_json(200 if "error" not in body else 400, body)

    def _send_finder(self, my_team_id, target_team_id, want_rationale):
        try:
            body = build_trade_finder(my_team_id, target_team_id, want_rationale)
        except Exception as e:
            import traceback
            body = {"error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc()[-1500:]}
        self._send_json(200 if "error" not in body else 400, body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
