"""
api/fetcher.py — ESPN Fantasy API data fetching and caching.

Handles all direct ESPN API calls:
  - Auth headers/cookies
  - Pro team map lookup
  - MLB Stats API season stats
  - Actual FPTS retrieval (parallel, with daily caching)

Extracted from espn.py during session 18 refactor.
"""

import os
import requests
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from kv import cache_get, cache_set


SEASON_START = datetime(2026, 3, 25)

# ESPN per-game stat ID mapping for pitching scoring stats.
# Verified against Joe Ryan (W, 7IP/2H/2ER/1BB/1HBP/5K = 23.0 FPTS)
# and Kyle Harrison (L, 4.1IP/4H/2ER/1BB/1HBP/1K = -1.0 FPTS).
# See KNOWLEDGE.md for full verification details.
ESPN_PITCHING_STAT_IDS = {
    "34": "outs",  # outs recorded (divide by 3 for IP)
    "48": "so",    # strikeouts
    "37": "h",     # hits allowed
    "42": "bb",    # walks
    "45": "er",    # earned runs
    "46": "hb",    # hit batsmen
    "53": "w",     # wins (per-game, not season total)
    "54": "l",     # losses (per-game, not season total)
    "57": "sv",    # saves
}


def strip_accents(s: str) -> str:
    """Normalize accented characters for name matching across data sources."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).lower()


def get_headers_and_cookies():
    """Build ESPN API request headers and auth cookies from env vars."""
    espn_s2 = os.environ.get("ESPN_S2", "").strip()
    swid    = os.environ.get("ESPN_SWID", "").strip()
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    return headers, cookies


def get_pro_team_map(headers, cookies):
    """
    Fetch current MLB team ID -> abbreviation mapping from ESPN.
    Falls back to hardcoded 2026 map if the API call fails.
    """
    try:
        year = os.environ.get("ESPN_SEASON", "2026")
        r = requests.get(
            f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}",
            params={"view": "proTeamSchedules_wl"},
            cookies=cookies,
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            team_map = {}
            for team in data.get("proTeams", []):
                team_id = team.get("id")
                abbrev  = team.get("abbrev", "")
                if team_id and abbrev:
                    team_map[team_id] = abbrev
            if team_map:
                return team_map
    except Exception as e:
        print(f"[fetcher.py] Failed to fetch pro team map: {e}")

    return {
        1:  "BAL", 2:  "BOS", 3:  "LAA", 4:  "CWS", 5:  "CLE",
        6:  "DET", 7:  "KC",  8:  "MIL", 9:  "MIN", 10: "NYY",
        11: "ATH", 12: "SEA", 13: "TEX", 14: "TOR", 15: "ATL",
        16: "CHC", 17: "CIN", 18: "HOU", 19: "LAD", 20: "WSH",
        21: "NYM", 22: "PHI", 23: "PIT", 24: "STL", 25: "SD",
        26: "SF",  27: "COL", 28: "MIA", 29: "ARI", 30: "TB",
        31: "FA",  32: "FA",
    }


def date_to_scoring_period(date_str: str) -> int:
    """Convert a YYYY-MM-DD date string to ESPN's daily scoring period ID.
    March 25, 2026 = period 1."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - SEASON_START).days + 1


def period_has_started(schedule: dict, period: int) -> bool:
    """
    Returns True if any MLB game on the date corresponding to `period` is
    in_progress or final. ESPN locks a scoring period's roster once any
    of its games starts; same-day transactions made after that lock are
    reflected in `period + 1` (the next period).

    Replaces an earlier `today_has_started(schedule)` helper which keyed
    off UTC today. That was off-by-one whenever UTC had crossed midnight
    while ESPN's scoring-period boundary (which tracks ET, not UTC) had
    not — causing the lag-fix branch in api/espn.py to silently skip
    when an add happened in the user's evening. The Montero case
    (April 25 evening CT, request fired after UTC midnight on April 26):
    UTC today was already 4/26, no 4/26 games had started yet, so the
    old check returned False even though period 32 (4/25) was very much
    locked. Keying off the period ESPN just returned removes the
    timezone dependency entirely.
    """
    period_date = (SEASON_START + timedelta(days=period - 1)).strftime("%Y-%m-%d")
    period_games = schedule.get(period_date, {})
    return any(
        g.get("status") in ("in_progress", "final")
        for g in period_games.values()
    )


def fetch_season_stats(yr: int) -> dict:
    """Fetch season pitching stats from MLB Stats API.
    Returns { fullname_lower: stat_dict } where each stat_dict has an
    extra "_mlbId" key holding the MLB Stats API personId. PR G added
    this so fetch_game_logs() can iterate the /people/{id}/stats endpoint
    (the bulk /stats?stats=gameLog&playerPool=all endpoint silently
    returns empty — MLB Stats API does not support playerPool=all on
    the gameLog stats type)."""
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/stats",
            params={
                "stats": "season", "playerPool": "all",
                "group": "pitching", "season": str(yr),
                "gameType": "R", "limit": 1000,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if r.status_code != 200:
            return {}
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        result = {}
        for s in splits:
            player = s.get("player", {})
            full_name = player.get("fullName", "")
            if not full_name:
                continue
            stat = dict(s.get("stat", {}))  # shallow copy so we don't mutate upstream
            stat["_mlbId"] = player.get("id")
            result[strip_accents(full_name)] = stat
        return result
    except Exception as e:
        print(f"[fetcher.py] Failed to fetch {yr} MLB stats: {e}")
        return {}


def get_actual_fpts(past_dates: list, player_names: set, headers: dict,
                    cookies: dict, team_id: int = 0) -> tuple:
    """
    Fetch actual fantasy points, saves, and bench status per pitcher per day.
    Caches completed days in KV — only fetches from ESPN for uncached days.
    Also tracks which pitchers were on our team each day (for dropped player detection).

    Returns: (fpts_result, saves_result, bench_result, my_team_pitchers_by_day)
    """
    league_id = os.environ["ESPN_LEAGUE_ID"]
    year      = os.environ.get("ESPN_SEASON", "2026")
    base      = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"
        f"/seasons/{year}/segments/0/leagues/{league_id}"
    )

    fpts_result  = {name: {} for name in player_names}
    saves_result = {name: {} for name in player_names}
    bench_result = {name: [] for name in player_names}
    my_team_pitchers_by_day = {}
    live_stats_result = {}  # pitcher_name -> {fpts, stats: {ip, so, h, bb, er, ...}}

    # ── Check cache for each past day ─────────────────────────────────────
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dates_to_fetch = []

    for date_str in past_dates:
        if date_str >= today_str:
            dates_to_fetch.append(date_str)
            continue
        try:
            cached = cache_get(f"cache:daily:{date_str}")
            if cached:
                cached_fpts    = cached.get("fpts", {})
                cached_saves   = cached.get("saves", {})
                cached_bench   = cached.get("bench", {})
                cached_my_team = cached.get("my_team", {})
                for name in player_names:
                    if name in cached_fpts:
                        fpts_result[name][date_str] = cached_fpts[name]
                    if name in cached_saves:
                        saves_result[name][date_str] = cached_saves[name]
                    if name in cached_bench:
                        bench_result[name].append(date_str)
                if cached_my_team:
                    my_team_pitchers_by_day[date_str] = cached_my_team
                continue
        except Exception:
            pass
        dates_to_fetch.append(date_str)

    if dates_to_fetch:
        print(f"[fetcher.py] Fetching actual FPTS for {len(dates_to_fetch)} days "
              f"(cached {len(past_dates) - len(dates_to_fetch)})")
    else:
        print(f"[fetcher.py] All {len(past_dates)} days loaded from cache")

    # ── Fetch uncached days from ESPN ─────────────────────────────────────
    def fetch_one_day(date_str: str):
        scoring_period = date_to_scoring_period(date_str)
        try:
            r = requests.get(
                base,
                params=[("view", "mRoster"), ("scoringPeriodId", scoring_period)],
                cookies=cookies,
                headers=headers,
                timeout=15
            )
            if r.status_code != 200:
                return date_str, {}
            return date_str, r.json()
        except Exception as e:
            print(f"[fetcher.py] Failed to fetch scoring period {scoring_period}: {e}")
            return date_str, {}

    if dates_to_fetch:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_one_day, d): d for d in dates_to_fetch}
            for future in as_completed(futures):
                date_str, data = future.result()
                if not data:
                    continue
                scoring_period = date_to_scoring_period(date_str)

                day_fpts    = {}
                day_saves   = {}
                day_bench   = set()
                day_my_team = {}
                day_actual_stats = {}

                for team in data.get("teams", []):
                    is_my_team = (team.get("id") == team_id)
                    for entry in team.get("roster", {}).get("entries", []):
                        pool_entry = entry.get("playerPoolEntry", {})
                        player     = pool_entry.get("player", {})
                        name       = player.get("fullName", "")
                        if not name:
                            continue

                        # Track all pitchers on our team (for dropped player detection)
                        if is_my_team:
                            eligible_slots = set(player.get("eligibleSlots", []))
                            if 14 in eligible_slots or 13 in eligible_slots:
                                lineup_slot = entry.get("lineupSlotId", 0)
                                day_my_team[name] = {
                                    "lineupSlotId": lineup_slot,
                                    "team": player.get("proTeamId", 0),
                                    "eligible": sorted(list(eligible_slots)),
                                }

                        # Track bench status
                        lineup_slot = entry.get("lineupSlotId", 0)
                        if lineup_slot == 16:
                            day_bench.add(name)

                        # Pull per-game stats
                        for stat in player.get("stats", []):
                            if (stat.get("statSplitTypeId") == 5 and
                                    stat.get("scoringPeriodId") == scoring_period):
                                fpts = stat.get("appliedTotal", 0.0)
                                if fpts != 0:
                                    day_fpts[name] = round(float(fpts), 1)
                                raw_stats = stat.get("stats", {})
                                sv = raw_stats.get("57", 0)
                                if sv:
                                    day_saves[name] = int(sv)
                                # Extract per-stat actuals for accuracy tracking
                                if raw_stats and fpts != 0:
                                    outs = raw_stats.get("34", 0)
                                    actual_breakdown = {
                                        "fpts": round(float(fpts), 1),
                                        "stats": {
                                            "ip": round(float(outs) / 3, 2),
                                            "so": float(raw_stats.get("48", 0)),
                                            "h":  float(raw_stats.get("37", 0)),
                                            "bb": float(raw_stats.get("42", 0)),
                                            "er": float(raw_stats.get("45", 0)),
                                            "hb": float(raw_stats.get("46", 0)),
                                            "w":  float(raw_stats.get("53", 0)),
                                            "l":  float(raw_stats.get("54", 0)),
                                            "sv": float(raw_stats.get("57", 0)),
                                        },
                                    }
                                    if not day_actual_stats.get(name):
                                        day_actual_stats[name] = actual_breakdown
                                break

                # Apply to result dicts (filtered by player_names)
                for name in player_names:
                    if name in day_fpts:
                        fpts_result[name][date_str] = day_fpts[name]
                    if name in day_saves:
                        saves_result[name][date_str] = day_saves[name]
                    if name in day_bench:
                        bench_result[name].append(date_str)
                if day_my_team:
                    my_team_pitchers_by_day[date_str] = day_my_team

                # Capture today's live stat breakdowns (not cached — changes every refresh)
                if date_str >= today_str and day_actual_stats:
                    for name in player_names:
                        if name in day_actual_stats:
                            live_stats_result[name] = day_actual_stats[name]

                # Cache this day if it's fully completed (not today)
                if date_str < today_str:
                    try:
                        cache_set(f"cache:daily:{date_str}", {
                            "fpts":         day_fpts,
                            "saves":        day_saves,
                            "bench":        list(day_bench),
                            "my_team":      day_my_team,
                            "actual_stats": day_actual_stats,
                        })
                    except Exception:
                        pass

    return fpts_result, saves_result, bench_result, my_team_pitchers_by_day, live_stats_result


def load_cached_data(year_int: int) -> dict:
    """
    Load all cached external data needed by the projection model.
    Fetches from APIs if cache is empty, then stores in KV.

    Returns dict with keys:
      savant_current, savant_previous,
      mlb_stats_current, mlb_stats_previous,
      game_logs_current
    """
    from savant import fetch_expected_stats, fetch_statcast_stats
    from mlb import fetch_game_logs, get_team_win_data, get_team_woba_blended

    # ── Savant expected stats ─────────────────────────────────────────
    savant_previous = {}
    savant_current  = {}
    try:
        savant_previous = cache_get(f"cache:savant:{year_int - 1}") or {}
        savant_current  = cache_get(f"cache:savant:{year_int}") or {}
    except Exception:
        pass

    if not savant_previous or not savant_current:
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if not savant_previous:
                    futures[executor.submit(fetch_expected_stats, year_int - 1)] = "prev"
                if not savant_current:
                    futures[executor.submit(fetch_expected_stats, year_int)] = "cur"
                for future in as_completed(futures):
                    label = futures[future]
                    result = future.result() or {}
                    if label == "prev":
                        savant_previous = result
                        try:
                            cache_set(f"cache:savant:{year_int - 1}", result)
                        except Exception:
                            pass
                    else:
                        savant_current = result
                        try:
                            cache_set(f"cache:savant:{year_int}", result, ttl_seconds=86400)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[fetcher.py] Savant fetch failed: {e}")

    print(f"[fetcher.py] Savant: {len(savant_current)} current, {len(savant_previous)} previous")

    # ── Savant Statcast stats (Barrel%, Whiff%) ───────────────────────
    # Currently only used for display on the Stats tab — not threaded into
    # projections. Cached separately from savant_current under its own
    # key so a Statcast-only outage can't poison the projection cache.
    # Single-year fetch (no _previous) since these are snapshot displays.
    savant_statcast_current = {}
    try:
        savant_statcast_current = cache_get(f"cache:savant-statcast:{year_int}") or {}
    except Exception:
        pass

    if not savant_statcast_current:
        try:
            result = fetch_statcast_stats(year_int) or {}
            if result:
                savant_statcast_current = result
                try:
                    cache_set(f"cache:savant-statcast:{year_int}", result,
                              ttl_seconds=86400)
                except Exception:
                    pass
        except Exception as e:
            print(f"[fetcher.py] Savant statcast fetch failed: {e}")

    print(f"[fetcher.py] Savant statcast: {len(savant_statcast_current)} pitchers")

    # ── MLB Stats API season stats ────────────────────────────────────
    mlb_stats_previous = {}
    mlb_stats_current  = {}
    try:
        mlb_stats_previous = cache_get(f"cache:mlb-stats:{year_int - 1}") or {}
        mlb_stats_current  = cache_get(f"cache:mlb-stats:{year_int}") or {}
    except Exception:
        pass

    if not mlb_stats_previous or not mlb_stats_current:
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if not mlb_stats_previous:
                    futures[executor.submit(fetch_season_stats, year_int - 1)] = "prev"
                if not mlb_stats_current:
                    futures[executor.submit(fetch_season_stats, year_int)] = "cur"
                for future in as_completed(futures):
                    label = futures[future]
                    result = future.result() or {}
                    if label == "prev":
                        mlb_stats_previous = result
                        try:
                            cache_set(f"cache:mlb-stats:{year_int - 1}", result)
                        except Exception:
                            pass
                    else:
                        mlb_stats_current = result
                        try:
                            cache_set(f"cache:mlb-stats:{year_int}", result, ttl_seconds=86400)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[fetcher.py] MLB stats fetch failed: {e}")

    print(f"[fetcher.py] MLB stats: {len(mlb_stats_current)} current, "
          f"{len(mlb_stats_previous)} previous")

    # ── Game logs for recent form weighting ────────────────────────────
    # PR G: fetch_game_logs now requires mlb_stats_current because it
    # iterates the per-player /people/{id}/stats endpoint (see docstring
    # on mlb.fetch_game_logs). The bulk /stats?playerPool=all endpoint
    # silently returns empty for gameLog — this went undetected for
    # weeks, zeroing out recent-form weighting and blocking actual-all:
    # writes in cron.py.
    #
    # Session 25: fetch_game_logs now returns (data, stats). On a cache
    # hit we have no stats — leave game_log_stats empty in that case.
    # Stats only carry meaningful values when we did a fresh fetch.
    game_logs_current = {}
    game_log_stats = {}
    try:
        game_logs_current = cache_get(f"cache:game-logs:{year_int}") or {}
    except Exception:
        pass

    if not game_logs_current:
        try:
            game_logs_current, game_log_stats = fetch_game_logs(
                year_int, mlb_stats_current
            )
            if game_logs_current:
                try:
                    cache_set(f"cache:game-logs:{year_int}", game_logs_current,
                              ttl_seconds=86400)
                except Exception:
                    pass
        except Exception as e:
            print(f"[fetcher.py] Game logs fetch failed: {e}")
            game_logs_current = {}
            game_log_stats = {}

    print(f"[fetcher.py] Game logs: {len(game_logs_current)} pitchers with game-level data")

    # ── Team win data for Pythagorean win probability (24hr TTL) ───────
    team_win_data = {}
    try:
        team_win_data = cache_get(f"cache:team-win-data:{year_int}") or {}
    except Exception:
        pass

    if not team_win_data:
        try:
            team_win_data = get_team_win_data(year_int) or {}
            if team_win_data:
                try:
                    cache_set(f"cache:team-win-data:{year_int}", team_win_data,
                              ttl_seconds=86400)
                except Exception:
                    pass
        except Exception as e:
            print(f"[fetcher.py] Team win data fetch failed: {e}")

    print(f"[fetcher.py] Team win data: {len(team_win_data)} teams")

    # ── Team wOBA factors for opponent quality adjustment (24hr TTL) ───
    # Blended: season wOBA + last 14-day rolling window. See
    # get_team_woba_blended() in mlb.py for the blend formula.
    team_woba_factors = {}
    try:
        team_woba_factors = cache_get(f"cache:team-woba:{year_int}") or {}
    except Exception:
        pass

    if not team_woba_factors:
        try:
            team_woba_factors = get_team_woba_blended(year_int) or {}
            if team_woba_factors:
                try:
                    cache_set(f"cache:team-woba:{year_int}", team_woba_factors,
                              ttl_seconds=86400)
                except Exception:
                    pass
        except Exception as e:
            print(f"[fetcher.py] Team wOBA fetch failed: {e}")

    print(f"[fetcher.py] Team wOBA (blended): {len(team_woba_factors)} teams")

    return {
        "savant_current":          savant_current,
        "savant_previous":         savant_previous,
        "savant_statcast_current": savant_statcast_current,
        "mlb_stats_current":       mlb_stats_current,
        "mlb_stats_previous":      mlb_stats_previous,
        "game_logs_current":       game_logs_current,
        "game_log_stats":          game_log_stats,
        "team_win_data":           team_win_data,
        "team_woba_factors":       team_woba_factors,
    }
