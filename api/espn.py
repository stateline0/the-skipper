"""
/api/espn.py  — Vercel Python serverless function
Orchestrates roster + free agent data from ESPN Fantasy Baseball API.

This file is the API endpoint handler. It coordinates:
  - fetcher.py: ESPN data fetching, caching, auth
  - projection.py: FPTS projection model
  - mlb.py: probable pitchers, schedule, wOBA, park factors
  - kv.py: Redis caching and projection locking

Refactored in session 18 — split from a 1220-line monolith into focused modules.
"""
import json
import os
import sys
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mlb import get_starts_for_players, get_team_woba, MATCHUP_PERIODS
from kv import get_all_locked_projections
from fetcher import (
    get_headers_and_cookies, get_pro_team_map, today_has_started,
    get_actual_fpts, load_cached_data,
)
from projection import get_projected_fpts


# ── Roster helpers ────────────────────────────────────────────────────

def get_slot_label(eligible_slots: set, injured: bool) -> str:
    """Determine position label from eligibility and injury status.
    Uses eligibleSlots for SP/RP (stable player attribute) and
    player.injured for IL detection (not lineupSlotId, which is daily)."""
    if injured:
        return "IL"
    if 14 in eligible_slots:
        return "SP"
    if 13 in eligible_slots and 14 not in eligible_slots:
        return "RP"
    return "P"


def get_status(injured: bool) -> str:
    """Simple status label. Bench is not tracked — it's a daily lineup decision."""
    if injured:
        return "IL"
    return "Active"


# ── Main data assembly ────────────────────────────────────────────────

def get_league_data(team_id: int, week: int) -> dict:
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    year_int  = int(year)
    headers, cookies = get_headers_and_cookies()
    PRO_TEAM_MAP     = get_pro_team_map(headers, cookies)
    base = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    # ── Load cached external data (Savant, MLB Stats, game logs, team win) ─
    cached = load_cached_data(year_int)
    savant_current     = cached["savant_current"]
    savant_previous    = cached["savant_previous"]
    mlb_stats_current  = cached["mlb_stats_current"]
    mlb_stats_previous = cached["mlb_stats_previous"]
    game_logs_current  = cached["game_logs_current"]
    team_win_data      = cached["team_win_data"]

    # ── Team wOBA factors for opponent quality adjustment ─────────────
    team_woba_factors = get_team_woba(year_int)

    # ── Matchup period metadata ──────────────────────────────────────
    mp            = MATCHUP_PERIODS.get(week, {})
    week_start    = ""
    week_end      = ""
    matchup_limit = int(os.environ.get("ESPN_STARTS_LIMIT", "12"))

    if mp:
        def fmt(d):
            return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d")
        week_start    = fmt(mp["start"])
        week_end      = fmt(mp["end"])
        matchup_limit = mp["limit"]

    # ── Fetch roster ─────────────────────────────────────────────────
    r = requests.get(
        base,
        params=[
            ("view", "mRoster"),
            ("view", "mTeam"),
            ("view", "mSettings"),
            ("view", "mMatchupScore"),
            ("_", int(datetime.now().timestamp())),
        ],
        cookies=cookies,
        headers=headers,
        timeout=15
    )
    if r.status_code != 200:
        raise Exception(f"ESPN returned HTTP {r.status_code}")

    data         = r.json()
    teams        = data.get("teams", [])
    my_team      = next((t for t in teams if t.get("id") == team_id), teams[0] if teams else {})
    team_name    = my_team.get("name", "").strip()
    current_week = data.get("scoringPeriodId", week)

    # ── Fetch per-player projected stats ─────────────────────────────
    xff_roster = json.dumps({
        "players": {
            "filterIds": {"value": [
                e.get("playerId")
                for e in my_team.get("roster", {}).get("entries", [])
                if e.get("playerId")
            ]},
            "filterStatsForCurrentSeasonScoringPeriodId": {"value": [current_week]},
        }
    })
    stats_r = requests.get(
        base,
        params=[("view", "kona_player_info"), ("scoringPeriodId", current_week)],
        cookies=cookies,
        headers={**headers, "x-fantasy-filter": xff_roster},
        timeout=15
    )
    proj_fpts_by_player = {}
    if stats_r.status_code == 200:
        for p in stats_r.json().get("players", []):
            pid  = p.get("id")
            proj = p.get("playerPoolEntry", {}).get("appliedStatTotal", 0)
            proj_fpts_by_player[pid] = round(float(proj or 0), 1)

    # ── Fetch probable pitchers + full game schedule ──────────────────
    roster_entries   = my_team.get("roster", {}).get("entries", [])
    all_player_names = [
        e.get("playerPoolEntry", {}).get("player", {}).get("fullName", "")
        for e in roster_entries
        if e.get("playerPoolEntry", {}).get("player", {}).get("fullName")
    ]
    roster_team_map = {}
    for e in roster_entries:
        pool   = e.get("playerPoolEntry", {})
        player = pool.get("player", {})
        name   = player.get("fullName", "")
        pro_id = player.get("proTeamId", 0)
        if name and pro_id:
            roster_team_map[name] = PRO_TEAM_MAP.get(pro_id, "")
    starts_map, schedule = get_starts_for_players(all_player_names, week, team_map=roster_team_map)

    # ── Roster transaction lag fix ────────────────────────────────────
    if today_has_started(schedule):
        next_period = current_week + 1
        print(f"[espn.py] Games in progress — fetching roster at scoringPeriodId={next_period}")
        r2 = requests.get(
            base,
            params=[
                ("view", "mRoster"),
                ("view", "mTeam"),
                ("scoringPeriodId", next_period),
                ("_", int(datetime.now().timestamp())),
            ],
            cookies=cookies,
            headers=headers,
            timeout=15
        )
        if r2.status_code == 200:
            data2    = r2.json()
            teams2   = data2.get("teams", [])
            my_team2 = next((t for t in teams2 if t.get("id") == team_id), None)
            if my_team2:
                my_team        = my_team2
                roster_entries = my_team.get("roster", {}).get("entries", [])
                print(f"[espn.py] Roster re-fetched successfully at period {next_period}")
            else:
                print(f"[espn.py] Re-fetch succeeded but team {team_id} not found — keeping original")
        else:
            print(f"[espn.py] Re-fetch failed (HTTP {r2.status_code}) — keeping original roster")

    # ── Projection model inputs ─────────────────────────────────────
    days_in_period = 7
    if mp:
        start_d = datetime.strptime(mp["start"], "%Y-%m-%d").date()
        end_d   = datetime.strptime(mp["end"],   "%Y-%m-%d").date()
        days_in_period = (end_d - start_d).days + 1

    projection_inputs = []
    for entry in roster_entries:
        pool_entry     = entry.get("playerPoolEntry", {})
        player         = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        full_name      = player.get("fullName", "")
        if not full_name:
            continue
        if not (14 in eligible_slots or 13 in eligible_slots):
            continue
        is_rp = (14 not in eligible_slots and 13 in eligible_slots)
        pitcher_data = starts_map.get(full_name, {})
        pro_team_id  = player.get("proTeamId", 0)
        projection_inputs.append({
            "name":           full_name,
            "starts":         pitcher_data.get("starts", 0),
            "startDates":     pitcher_data.get("startDates", []),
            "is_rp":          is_rp,
            "days_in_period": days_in_period,
            "team":           PRO_TEAM_MAP.get(pro_team_id, ""),
        })

    proj_fpts_by_name, proj_blend_by_name, fpts_per_start_roster, proj_details_roster = get_projected_fpts(
        projection_inputs, team_woba_factors,
        season=year_int, period=week,
        today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        savant_current=savant_current,
        savant_previous=savant_previous,
        mlb_stats_current=mlb_stats_current,
        mlb_stats_previous=mlb_stats_previous,
        game_logs=game_logs_current,
        team_win_data=team_win_data,
        schedule=schedule,
    )

    # ── Parse roster ──────────────────────────────────────────────────
    roster_sps  = []
    SP_ELIGIBLE = {14}
    RP_ELIGIBLE = {13}
    today_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for entry in roster_entries:
        pool_entry     = entry.get("playerPoolEntry", {})
        player         = pool_entry.get("player", {})
        eligible_slots = set(player.get("eligibleSlots", []))
        player_id      = entry.get("playerId")

        if not (eligible_slots & SP_ELIGIBLE) and not (eligible_slots & RP_ELIGIBLE):
            continue

        injured      = player.get("injured", False)
        slot_label   = get_slot_label(eligible_slots, injured)
        status_label = get_status(injured)
        pro_team_id  = player.get("proTeamId", 0)
        team_abbrev  = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
        player_name  = player.get("fullName", "Unknown")

        pitcher_data     = starts_map.get(player_name, {"starts": 0, "startDates": []})
        scheduled_starts = pitcher_data["starts"]
        start_dates      = pitcher_data["startDates"]
        proj_fpts        = proj_fpts_by_name.get(
            player_name,
            proj_fpts_by_player.get(player_id, 0.0)
        )

        if 14 in eligible_slots:
            position = "SP"
        elif 13 in eligible_slots:
            position = "RP"
        else:
            position = "P"

        roster_sps.append({
            "name":         player_name,
            "team":         team_abbrev,
            "slot":         slot_label,
            "position":     position,
            "injuryStatus": status_label,
            "starts":       scheduled_starts,
            "startDates":   start_dates,
            "projFpts":     proj_fpts,
            "projBlend":    proj_blend_by_name.get(player_name, 0.0),
            "percentOwned": round(pool_entry.get("percentOwned", 100), 1),
        })

    slot_order = {"SP": 0, "RP": 1, "IL": 2, "Bench": 3, "P": 1}
    # Sort by slot group, then by average FPTS per start (best pitchers first).
    # Pitchers with 0 starts go to the bottom within their slot group.
    def sort_key(x):
        slot = slot_order.get(x["slot"], 1)
        starts = x["starts"]
        if starts > 0:
            per_start = x["projFpts"] / starts
        else:
            per_start = 0.0
        return (slot, -per_start)
    roster_sps.sort(key=sort_key)

    # ── Fetch free agents ─────────────────────────────────────────────
    xff_fa = json.dumps({
        "players": {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "filterSlotIds": {"value": [14]},
            "limit": 100,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "filterStatsForCurrentSeasonScoringPeriodId": {"value": [current_week]},
        }
    })
    fa_r = requests.get(
        base,
        params=[("view", "kona_player_info"), ("scoringPeriodId", current_week)],
        cookies=cookies,
        headers={**headers, "x-fantasy-filter": xff_fa},
        timeout=15
    )
    free_agents = []
    fa_fpts_per_start = {}
    fa_proj_details = {}
    if fa_r.status_code == 200:
        fa_names      = []
        fa_players_raw = []
        for p in fa_r.json().get("players", []):
            player = p.get("player", {})
            if not player.get("fullName"):
                continue
            eligible_slots = set(player.get("eligibleSlots", []))
            if 14 not in eligible_slots:
                continue
            fa_names.append(player["fullName"])
            fa_players_raw.append(p)

        fa_team_map = {}
        for p in fa_players_raw:
            player = p.get("player", {})
            name   = player.get("fullName", "")
            pro_id = player.get("proTeamId", 0)
            if name and pro_id:
                fa_team_map[name] = PRO_TEAM_MAP.get(pro_id, "")
        fa_starts_map, _ = get_starts_for_players(fa_names, week, team_map=fa_team_map)

        fa_projection_inputs = []
        for p in fa_players_raw:
            player         = p.get("player", {})
            fa_name        = player.get("fullName", "")
            eligible_slots = set(player.get("eligibleSlots", []))
            is_rp          = (14 not in eligible_slots and 13 in eligible_slots)
            if not fa_name:
                continue
            fa_pitcher_data = fa_starts_map.get(fa_name, {})
            pro_team_id     = player.get("proTeamId", 0)
            fa_projection_inputs.append({
                "name":           fa_name,
                "starts":         fa_pitcher_data.get("starts", 0),
                "startDates":     fa_pitcher_data.get("startDates", []),
                "is_rp":          is_rp,
                "days_in_period": days_in_period,
                "team":           PRO_TEAM_MAP.get(pro_team_id, ""),
            })

        fa_proj_fpts, fa_proj_blend, fa_fpts_per_start, fa_proj_details = get_projected_fpts(
            fa_projection_inputs, team_woba_factors,
            season=year_int, period=week,
            today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            savant_current=savant_current,
            savant_previous=savant_previous,
            mlb_stats_current=mlb_stats_current,
            mlb_stats_previous=mlb_stats_previous,
            game_logs=game_logs_current,
            team_win_data=team_win_data,
            schedule=schedule,
        )

        inj_label_map = {
            "ACTIVE": "Active", "NORMAL": "Active",
            "FIFTEEN_DAY_DL": "IL15", "SIXTY_DAY_DL": "IL60",
            "DAY_TO_DAY": "DTD", "SUSPENSION": "SUSP",
        }
        for p in fa_players_raw:
            player       = p.get("player", {})
            fa_name      = player.get("fullName", "Unknown")
            pro_team_id  = player.get("proTeamId", 0)
            team_abbrev  = PRO_TEAM_MAP.get(pro_team_id, str(pro_team_id))
            raw_inj      = player.get("injuryStatus", "ACTIVE")
            pitcher_data = fa_starts_map.get(fa_name, {"starts": 0, "startDates": []})

            free_agents.append({
                "name":         fa_name,
                "team":         team_abbrev,
                "injuryStatus": inj_label_map.get(raw_inj, raw_inj),
                "percentOwned": round(player.get("ownership", {}).get("percentOwned", 0), 1),
                "projFpts":     fa_proj_fpts.get(fa_name, 0.0),
                "projBlend":    fa_proj_blend.get(fa_name, 0.0),
                "starts":       pitcher_data["starts"],
                "startDates":   pitcher_data["startDates"],
                "opps":         "",
                "checked":      player.get("ownership", {}).get("percentOwned", 0) >= 15,
            })

    # ── Fetch actual FPTS for past dates + today (for live stats) ────
    today     = datetime.now(timezone.utc).date()
    all_dates = []
    if mp:
        start = datetime.strptime(mp["start"], "%Y-%m-%d").date()
        end   = datetime.strptime(mp["end"], "%Y-%m-%d").date()
        d     = start
        while d <= today and d <= end:
            all_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

    all_pitcher_names = set(p["name"] for p in roster_sps)
    fa_pitcher_names  = set(p["name"] for p in free_agents)
    actual_fpts  = {}
    actual_saves = {}
    bench_days   = {}
    my_team_pitchers_by_day = {}
    live_stats = {}
    if all_dates:
        actual_fpts, actual_saves, bench_days, my_team_pitchers_by_day, live_stats = get_actual_fpts(
            all_dates, all_pitcher_names | fa_pitcher_names, headers, cookies, team_id
        )

    fa_actual_fpts = {name: actual_fpts[name] for name in fa_pitcher_names if name in actual_fpts}
    roster_actual_fpts = {name: actual_fpts[name] for name in all_pitcher_names if name in actual_fpts}

    # ── Detect dropped players ────────────────────────────────────────
    dropped_players = []
    current_roster_names = set(p["name"] for p in roster_sps)
    all_past_names = set()
    for day_players in my_team_pitchers_by_day.values():
        all_past_names.update(day_players.keys())
    dropped_names = all_past_names - current_roster_names

    # Build team_map and pre-filter to SP-eligible dropped names so we
    # don't waste a starts/projection call on relievers we'd skip anyway.
    dropped_sp_info = {}  # name -> {team_abbrev, days_on_team, player_info, player_fpts}
    for name in sorted(dropped_names):
        days_on_team = sorted([d for d, players in my_team_pitchers_by_day.items() if name in players])
        if not days_on_team:
            continue
        first_day = days_on_team[0]
        player_info = my_team_pitchers_by_day[first_day][name]
        eligible = set(player_info.get("eligible", []))
        if 14 not in eligible:
            continue  # not SP-eligible
        team_abbrev = PRO_TEAM_MAP.get(player_info.get("team", 0), "")
        dropped_sp_info[name] = {
            "team_abbrev": team_abbrev,
            "days_on_team": days_on_team,
            "player_info": player_info,
            "player_fpts": actual_fpts.get(name, fa_actual_fpts.get(name, {})),
        }

    # Fetch starts and projections for dropped SPs (same pattern as roster + FAs).
    if dropped_sp_info:
        dropped_team_map = {n: info["team_abbrev"] for n, info in dropped_sp_info.items()}
        dropped_starts_map, _ = get_starts_for_players(
            list(dropped_sp_info.keys()), week, team_map=dropped_team_map
        )

        # Intersect startDates with days_on_team — only count starts that
        # happened while the player was actually on our roster.
        dropped_projection_inputs = []
        dropped_intersected = {}  # name -> {starts, startDates} (rostered-window only)
        for name, info in dropped_sp_info.items():
            raw_pitcher_data = dropped_starts_map.get(name, {"starts": 0, "startDates": []})
            days_on_team_set = set(info["days_on_team"])
            filtered_dates = [
                sd for sd in raw_pitcher_data.get("startDates", [])
                if sd.get("date") in days_on_team_set
            ]
            dropped_intersected[name] = {
                "starts": len(filtered_dates),
                "startDates": filtered_dates,
            }
            dropped_projection_inputs.append({
                "name":           name,
                "starts":         len(filtered_dates),
                "startDates":     filtered_dates,
                "is_rp":          False,
                "days_in_period": days_in_period,
                "team":           info["team_abbrev"],
            })

        dropped_proj_fpts, dropped_proj_blend, _, dropped_proj_details = get_projected_fpts(
            dropped_projection_inputs, team_woba_factors,
            season=year_int, period=week,
            today_str=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            savant_current=savant_current,
            savant_previous=savant_previous,
            mlb_stats_current=mlb_stats_current,
            mlb_stats_previous=mlb_stats_previous,
            game_logs=game_logs_current,
            team_win_data=team_win_data,
            schedule=schedule,
        )
    else:
        dropped_intersected = {}
        dropped_proj_fpts = {}
        dropped_proj_blend = {}
        dropped_proj_details = {}

    # Build the dropped player dicts using the real starts + projection data.
    for name, info in dropped_sp_info.items():
        intersected = dropped_intersected.get(name, {"starts": 0, "startDates": []})
        dropped_players.append({
            "name":         name,
            "team":         info["team_abbrev"],
            "slot":         "EX",
            "position":     "SP",
            "injuryStatus": "Dropped",
            "starts":       intersected["starts"],
            "startDates":   intersected["startDates"],
            "projFpts":     dropped_proj_fpts.get(name, 0.0),
            "projBlend":    dropped_proj_blend.get(name, 0.0),
            "projDetails":  dropped_proj_details.get(name),
            "percentOwned": 0.0,
            "daysOnTeam":   info["days_on_team"],
        })
        if name not in roster_actual_fpts and info["player_fpts"]:
            roster_actual_fpts[name] = info["player_fpts"]

    return {
        "ok":                True,
        "teamName":          team_name,
        "currentWeek":       current_week,
        "weekStart":         week_start,
        "weekEnd":           week_end,
        "rosterSPs":         roster_sps,
        "freeAgentSPs":      free_agents,
        "schedule":          schedule,
        "matchupDates":      [mp["start"], mp["end"]] if mp else [],
        "actualFpts":        roster_actual_fpts,
        "actualSaves":       actual_saves,
        "benchDays":         bench_days,
        "rosterFptsPerStart": fpts_per_start_roster,
        "faFptsPerStart":     fa_fpts_per_start,
        "faActualFpts":       fa_actual_fpts,
        "lockedProjections":  get_all_locked_projections(year_int, week),
        "droppedPlayers":     dropped_players,
        "liveStats":          live_stats,
        "projectionDetails":  proj_details_roster,
        "faProjectionDetails": fa_proj_details,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs      = parse_qs(urlparse(self.path).query)
        env_tid = os.environ.get("ESPN_TEAM_ID", "")
        team_id = int(env_tid) if env_tid else int(qs.get("teamId", ["1"])[0])
        week    = int(qs.get("week", ["1"])[0])

        try:
            payload = get_league_data(team_id, week)
            payload["teamId"]       = team_id
            payload["defaultLimit"] = int(os.environ.get("ESPN_STARTS_LIMIT", "12"))
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
