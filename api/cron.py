"""
/api/cron.py — Daily cron job for all-MLB projection locking.

Triggered once daily by Vercel Cron (noon CT / 17:00 UTC).
Projects FPTS for every probable MLB starter and locks projections
into KV under `proj2all:` prefix. This gives us ~60 data points per day
for model accuracy tracking instead of ~5-10 from roster-only.

Secured with CRON_SECRET environment variable — Vercel sends it
automatically as an Authorization header.

Also computes actual FPTS from MLB Stats API game logs for completed
games and stores them under `actual-all:{date}` keys.
"""
import json
import os
import sys
import re
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from mlb import (
    fetch_espn_probables, fetch_mlb_probables, build_pitcher_starts,
    MATCHUP_PERIODS, get_park_factor,
    compute_matchup_win_prob, compute_recent_form_fpts,
)
from fetcher import load_cached_data, strip_accents
from kv import cache_get, cache_set

try:
    from upstash_redis import Redis
    _redis = Redis(
        url=os.environ.get("KV_REST_API_URL", ""),
        token=os.environ.get("KV_REST_API_TOKEN", ""),
    )
    KV_AVAILABLE = bool(
        os.environ.get("KV_REST_API_URL") and
        os.environ.get("KV_REST_API_TOKEN")
    )
except Exception:
    _redis = None
    KV_AVAILABLE = False


# ── Constants (must match projection.py) ─────────────────────────────
SCORING = {"ip": 3, "so": 1, "h": -1, "bb": -1, "er": -2, "hb": -1, "w": 5, "l": -5, "sv": 5}
IP_THRESHOLD_SP = 50.0
MIN_STARTS_SP = 3
STARTER_WIN_SHARE = 0.57
DEFAULT_WIN_PROB = 0.5


def _make_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def _parse_ip(ip_str) -> float:
    try:
        parts = str(ip_str).split(".")
        full = int(parts[0])
        outs = int(parts[1]) if len(parts) > 1 else 0
        return full + outs / 3
    except Exception:
        return 0.0


def get_current_period() -> tuple:
    """Return (period_number, period_dict) for today's date."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for num, mp in MATCHUP_PERIODS.items():
        if mp["start"] <= today <= mp["end"]:
            return num, mp
    return 1, MATCHUP_PERIODS.get(1, {})


def lock_all_mlb_projections() -> dict:
    """
    Project FPTS for every probable MLB starter today and lock to KV.
    Returns summary of what was locked.
    """
    if not KV_AVAILABLE or _redis is None:
        return {"error": "KV not available"}

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year_int = int(os.environ.get("ESPN_SEASON", "2026"))
    period_num, mp = get_current_period()

    if not mp:
        return {"error": f"No matchup period found for {today_str}"}

    print(f"[cron.py] Starting all-MLB lock for {today_str} (period {period_num})")

    # ── Fetch all probable starters for today ────────────────────────────
    mlb_data = fetch_mlb_probables(today_str, today_str)
    espn_data, schedule = fetch_espn_probables(today_str, today_str)
    pitcher_starts = build_pitcher_starts(mlb_data, espn_data, today_str, today_str)

    if not pitcher_starts:
        return {"message": "No probable starters found for today", "date": today_str}

    print(f"[cron.py] Found {len(pitcher_starts)} probable starters for {today_str}")

    # ── Load cached model data ───────────────────────────────────────────
    cached = load_cached_data(year_int)
    savant_current     = cached["savant_current"]
    savant_previous    = cached["savant_previous"]
    mlb_stats_current  = cached["mlb_stats_current"]
    mlb_stats_previous = cached["mlb_stats_previous"]
    game_logs_current  = cached["game_logs_current"]
    team_win_data      = cached["team_win_data"]
    team_woba_factors  = cached["team_woba_factors"]

    # ── Project each probable starter ────────────────────────────────────
    locked_count = 0
    skipped_count = 0
    results = []

    for pitcher_name_lower, starts_info in pitcher_starts.items():
        start_dates = starts_info.get("startDates", [])
        today_start = None
        for sd in start_dates:
            if sd.get("date") == today_str:
                today_start = sd
                break

        if not today_start:
            continue

        # Check if already locked
        slug = _make_slug(pitcher_name_lower)
        lock_key = f"proj2all:{year_int}:{period_num}:{slug}:{today_str}"
        existing = _redis.get(lock_key)
        if existing is not None:
            skipped_count += 1
            continue

        # ── Build projection for this pitcher ────────────────────────
        # Look up season stats (both years)
        stat_26 = mlb_stats_current.get(pitcher_name_lower, {})
        stat_25 = mlb_stats_previous.get(pitcher_name_lower, {})

        gs_26 = int(stat_26.get("gamesStarted", 0))
        gs_25 = int(stat_25.get("gamesStarted", 0))

        ip_26 = _parse_ip(stat_26.get("inningsPitched", "0.0"))
        this_year_weight = min(1.0, ip_26 / IP_THRESHOLD_SP)
        last_year_weight = 1.0 - this_year_weight

        # Per-game averages
        def _avgs(stat, games):
            if games < MIN_STARTS_SP:
                return None
            ip = _parse_ip(stat.get("inningsPitched", "0.0")) / games
            h = int(stat.get("hits", 0)) / games
            bb = int(stat.get("baseOnBalls", 0)) / games
            hb = int(stat.get("hitBatsmen", 0)) / games
            return {
                "ip": ip, "so": int(stat.get("strikeOuts", 0)) / games,
                "h": h, "bb": bb, "er": int(stat.get("earnedRuns", 0)) / games,
                "hb": hb, "w": int(stat.get("wins", 0)) / games,
                "l": int(stat.get("losses", 0)) / games,
                "sv": int(stat.get("saves", 0)) / games,
                "batters_faced": ip * 3 + h + bb + hb,
            }

        avgs_26 = _avgs(stat_26, gs_26)
        avgs_25 = _avgs(stat_25, gs_25)

        if avgs_26 is None and avgs_25 is None:
            skipped_count += 1
            continue
        elif avgs_26 is None:
            this_year_weight = 0.0
            last_year_weight = 1.0
        elif avgs_25 is None:
            this_year_weight = 1.0
            last_year_weight = 0.0

        # Savant adjustments
        savant_26 = savant_current.get(pitcher_name_lower, {})
        savant_25 = savant_previous.get(pitcher_name_lower, {})
        used_savant = False

        if avgs_26 is not None and savant_26.get("xera", 0) > 0:
            adjusted = dict(avgs_26)
            xba = savant_26.get("xba", 0)
            xera = savant_26.get("xera", 0)
            if xba > 0 and adjusted["batters_faced"] > 0:
                adjusted["h"] = xba * adjusted["batters_faced"]
            if xera > 0 and adjusted["ip"] > 0:
                adjusted["er"] = xera * (adjusted["ip"] / 9)
            avgs_26 = adjusted
            used_savant = True

        if avgs_25 is not None and savant_25.get("xera", 0) > 0:
            adjusted = dict(avgs_25)
            xba = savant_25.get("xba", 0)
            xera = savant_25.get("xera", 0)
            if xba > 0 and adjusted["batters_faced"] > 0:
                adjusted["h"] = xba * adjusted["batters_faced"]
            if xera > 0 and adjusted["ip"] > 0:
                adjusted["er"] = xera * (adjusted["ip"] / 9)
            avgs_25 = adjusted
            used_savant = True

        # Blend years
        if avgs_26 is not None and avgs_25 is not None:
            blended = {s: avgs_26[s] * this_year_weight + avgs_25[s] * last_year_weight for s in avgs_26}
        elif avgs_26 is not None:
            blended = avgs_26
        else:
            blended = avgs_25

        model_label = "savant" if used_savant else "stats"
        season_base = sum(blended[s] * SCORING[s] for s in SCORING)

        # Recent form
        recent_form_fpts = None
        pitcher_games = game_logs_current.get(pitcher_name_lower, [])
        if pitcher_games:
            recent_form_fpts = compute_recent_form_fpts(pitcher_games, n_starts=4)

        if recent_form_fpts is not None:
            fpts_per_game = season_base * 0.6 + recent_form_fpts * 0.4
        else:
            fpts_per_game = season_base

        adjusted_base = round(fpts_per_game, 1)

        # ── Per-start matchup adjustments ────────────────────────────
        # Find this pitcher's team from the schedule
        # The scoreboard probables are keyed by full name lowercase
        # We need to figure out which team this pitcher is on
        day_schedule = schedule.get(today_str, {})
        pitcher_team = None
        opp_team = None
        is_home = True
        win_prob_from_schedule = None

        # Search schedule for a team whose game matches this pitcher
        for team_abbrev, game_info in day_schedule.items():
            # We can't directly match pitcher to team from scoreboard alone
            # But we can check the probables data — ESPN probables include team info
            # For now, try to find team via MLB Stats current year stats
            pass

        # Use the start date's info if available (from build_pitcher_starts enrichment)
        # Actually, build_pitcher_starts doesn't have team info since it only has names
        # We need to look up the pitcher's team from MLB Stats API data
        # The stat entry has a team field we can use
        team_name_26 = stat_26.get("team", {}).get("name", "") if isinstance(stat_26.get("team"), dict) else ""

        # Simpler approach: scan the schedule for which team has this game
        # and check the confirmed field in today_start
        opp = today_start.get("opponent", "")
        confirmed = today_start.get("confirmed", False)

        # Look up win probability and matchup factors
        vegas_wp = None
        for team_abbrev, game_info in day_schedule.items():
            win_prob_val = game_info.get("win_prob")
            if win_prob_val:
                vegas_wp = win_prob_val
                break  # just checking if odds exist today

        # For the all-MLB model, use a simplified matchup:
        # We don't have the pitcher→team mapping here, so use DEFAULT_WIN_PROB
        # unless we can resolve the team. This is the main limitation.
        # The accuracy tracking still works because we compare projected vs actual FPTS.
        win_prob = DEFAULT_WIN_PROB
        wp_source = "default"

        # Compute FPTS with W/L scaling
        base_no_wl = (
            blended["ip"] * 3 + blended["so"] * 1 + blended["h"] * -1 +
            blended["bb"] * -1 + blended["er"] * -2 + blended["hb"] * -1 +
            blended["sv"] * 5
        )
        w_contrib = blended["w"] * win_prob * STARTER_WIN_SHARE * 5
        l_contrib = blended["l"] * (1 - win_prob) * STARTER_WIN_SHARE * (-5)
        start_proj = base_no_wl + w_contrib + l_contrib

        # Lock the projection
        breakdown = {
            "fpts": round(start_proj, 1),
            "stats": {
                "ip": round(blended["ip"], 2),
                "so": round(blended["so"], 2),
                "h":  round(blended["h"], 2),
                "bb": round(blended["bb"], 2),
                "er": round(blended["er"], 2),
                "hb": round(blended["hb"], 2),
                "w":  round(blended["w"] * win_prob * STARTER_WIN_SHARE, 3),
                "l":  round(blended["l"] * (1 - win_prob) * STARTER_WIN_SHARE, 3),
                "sv": round(blended["sv"], 3),
            },
            "matchup": {
                "winProb": round(win_prob, 3),
                "wpSource": wp_source,
            },
            "model": {
                "type":         model_label,
                "blendWeight":  round(this_year_weight, 2),
                "recentForm":   round(recent_form_fpts, 1) if recent_form_fpts is not None else None,
                "seasonBase":   round(season_base, 1),
                "adjustedBase": adjusted_base,
            },
        }

        try:
            val = json.dumps(breakdown)
            _redis.set(lock_key, val, nx=True)
            locked_count += 1
            results.append({
                "pitcher": pitcher_name_lower,
                "proj": round(start_proj, 1),
                "model": model_label,
            })
        except Exception as e:
            print(f"[cron.py] Failed to lock {pitcher_name_lower}: {e}")

    # ── Store actual FPTS from game logs for completed past dates ─────
    # Game logs contain actual per-game stats for ALL pitchers.
    # We compute FPTS using our scoring formula and store keyed by date.
    actuals_stored = 0
    if game_logs_current:
        # Group game log entries by date, only for starts (gs=1)
        actuals_by_date = {}
        for pitcher_name, games in game_logs_current.items():
            for g in games:
                if g.get("gs", 0) < 1:
                    continue  # skip relief appearances
                game_date = g.get("date", "")
                if not game_date or game_date >= today_str:
                    continue  # skip today and future
                fpts = (
                    g["ip"] * 3 + g["so"] * 1 + g["h"] * -1 +
                    g["bb"] * -1 + g["er"] * -2 + g["hb"] * -1 +
                    g["w"] * 5 + g["l"] * -5 + g["sv"] * 5
                )
                if game_date not in actuals_by_date:
                    actuals_by_date[game_date] = {}
                actuals_by_date[game_date][pitcher_name] = {
                    "fpts": round(fpts, 1),
                    "stats": {
                        "ip": g["ip"], "so": g["so"], "h": g["h"],
                        "bb": g["bb"], "er": g["er"], "hb": g["hb"],
                        "w": g["w"], "l": g["l"], "sv": g["sv"],
                    },
                }

        # Store each date's actuals if not already cached
        for date_str, pitchers in actuals_by_date.items():
            cache_key = f"actual-all:{date_str}"
            existing = cache_get(cache_key)
            if existing is None:
                try:
                    cache_set(cache_key, pitchers)
                    actuals_stored += 1
                except Exception:
                    pass

    summary = {
        "ok": True,
        "date": today_str,
        "period": period_num,
        "probableStarters": len(pitcher_starts),
        "locked": locked_count,
        "skipped": skipped_count,
        "actualsStored": actuals_stored,
        "topProjections": sorted(results, key=lambda x: -x["proj"])[:10],
    }

    print(f"[cron.py] Done: {locked_count} locked, {skipped_count} skipped, "
          f"{actuals_stored} actual dates stored")

    return summary


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # ── Verify CRON_SECRET ────────────────────────────────────────
        cron_secret = os.environ.get("CRON_SECRET", "")
        auth_header = self.headers.get("Authorization", "")

        if cron_secret:
            expected = f"Bearer {cron_secret}"
            if auth_header != expected:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
                return

        try:
            result = lock_all_mlb_projections()
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            print(f"[cron.py] Error: {e}")

        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
