"""
/api/accuracy.py — Vercel Python serverless function
Compares v2 locked projections (proj2:* keys) against actual per-stat results
from daily caches (cache:daily:* keys) to produce accuracy tracking data.

Returns:
  - starts: list of {player, date, projected, actual, errors} for each matched start
  - summary: overall MAE, per-stat MAE, directional accuracy
  - factorAnalysis: MAE with vs without each adjustment factor (wOBA, park, recent form)
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

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


def get_accuracy_data(season: int, period: int, scope: str = "roster") -> dict:
    """
    Match v2 locked projections against actual stats for a given period.
    
    scope="roster" — original behavior, uses proj2: keys and cache:daily: actuals
    scope="all" — all-MLB starters, uses proj2all: keys and actual-all: actuals
    
    Returns comparison data for every start where both projected and actual exist.
    """
    if not KV_AVAILABLE or _redis is None:
        return {"starts": [], "summary": {}, "error": "KV not available"}

    # ── Determine key prefixes based on scope ────────────────────────────
    proj_prefix = "proj2all" if scope == "all" else "proj2"
    
    # ── Fetch all v2 locked projections for this period ───────────────────
    proj_keys = _redis.keys(f"{proj_prefix}:{season}:{period}:*")
    if not proj_keys:
        return {"starts": [], "summary": {}, "message": "No v2 projections found for this period"}

    projections = {}  # { "player-slug:date": { proj2 data } }
    slug_to_dates = {}  # { "player-slug": ["2026-04-10", ...] }
    for key in proj_keys:
        parts = key.split(":")
        if len(parts) != 5:
            continue
        _, _, _, slug, date = parts
        val = _redis.get(key)
        if val is None:
            continue
        try:
            proj_data = json.loads(val)
            projections[f"{slug}:{date}"] = proj_data
            slug_to_dates.setdefault(slug, []).append(date)
        except (json.JSONDecodeError, TypeError):
            continue

    print(f"[accuracy.py] Found {len(projections)} v2 projections across {len(slug_to_dates)} pitchers")

    # ── Collect unique dates that have projections ────────────────────────
    all_dates = set()
    for dates in slug_to_dates.values():
        all_dates.update(dates)

    # ── Fetch actual stats for those dates ──────────────────────────────
    actuals_by_date = {}  # { "2026-04-10": { "Player Name/key": { actual breakdown } } }
    for date in sorted(all_dates):
        if scope == "all":
            # All-MLB actuals stored by cron.py under actual-all: keys
            # Keyed by lowercase pitcher name (same as proj2all slug source)
            cache_key = f"actual-all:{date}"
        else:
            # Roster actuals from ESPN mRoster daily cache
            cache_key = f"cache:daily:{date}"
        val = _redis.get(cache_key)
        if val is None:
            continue
        try:
            daily_data = json.loads(val)
            if scope == "all":
                # actual-all: stores pitchers directly (no nested actual_stats key)
                if daily_data:
                    actuals_by_date[date] = daily_data
            else:
                actual_stats = daily_data.get("actual_stats", {})
                if actual_stats:
                    actuals_by_date[date] = actual_stats
        except (json.JSONDecodeError, TypeError):
            continue

    print(f"[accuracy.py] Found actual stats for {len(actuals_by_date)} dates")

    # ── Match projections to actuals ─────────────────────────────────────
    def make_slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")

    starts = []
    matched = 0
    unmatched = 0

    for proj_key, proj_data in projections.items():
        slug, date = proj_key.rsplit(":", 1)
        date_actuals = actuals_by_date.get(date, {})

        # Find matching player in actuals by slugifying their name
        actual_data = None
        matched_name = None
        for full_name, a_data in date_actuals.items():
            if make_slug(full_name) == slug:
                actual_data = a_data
                matched_name = full_name
                break

        if actual_data is None:
            unmatched += 1
            continue

        matched += 1
        proj_stats = proj_data.get("stats", {})
        actual_stats = actual_data.get("stats", {})
        proj_fpts = proj_data.get("fpts", 0)
        actual_fpts = actual_data.get("fpts", 0)

        # Per-stat errors (projected - actual)
        stat_errors = {}
        for stat_key in ["ip", "so", "h", "bb", "er", "hb", "w", "l", "sv"]:
            p = proj_stats.get(stat_key, 0)
            a = actual_stats.get(stat_key, 0)
            stat_errors[stat_key] = round(p - a, 2)

        # ── Counterfactual projections (what if we removed each factor?) ──
        # These let us measure whether each adjustment layer is helping.
        matchup = proj_data.get("matchup", {})
        model   = proj_data.get("model", {})
        woba_factor    = matchup.get("woba", 1.0)
        park_factor    = matchup.get("park", 1.0)
        adjusted_base  = model.get("adjustedBase", 0)
        season_base    = model.get("seasonBase", 0)
        recent_form    = model.get("recentForm")

        # What the projection would have been without each factor:
        # Full model:       adjustedBase × woba × park  (= proj_fpts)
        # Without wOBA:     adjustedBase × 1.0  × park
        # Without park:     adjustedBase × woba × 1.0
        # Without either:   adjustedBase × 1.0  × 1.0
        # Without recent form: seasonBase × woba × park
        without_woba = round(adjusted_base * 1.0 * park_factor, 1) if adjusted_base else proj_fpts
        without_park = round(adjusted_base * woba_factor * 1.0, 1) if adjusted_base else proj_fpts
        without_both = round(adjusted_base * 1.0 * 1.0, 1) if adjusted_base else proj_fpts
        without_recent_form = round(season_base * woba_factor * park_factor, 1) if (season_base and recent_form is not None) else proj_fpts

        starts.append({
            "player":      matched_name,
            "slug":        slug,
            "date":        date,
            "projFpts":    proj_fpts,
            "actualFpts":  actual_fpts,
            "fptsError":   round(proj_fpts - actual_fpts, 1),
            "projStats":   proj_stats,
            "actualStats": actual_stats,
            "statErrors":  stat_errors,
            "matchup":     matchup,
            "model":       model,
            # Counterfactual projections for factor analysis
            "counterfactuals": {
                "withoutWoba":       without_woba,
                "withoutPark":       without_park,
                "withoutBoth":       without_both,
                "withoutRecentForm": without_recent_form,
            },
        })

    print(f"[accuracy.py] Matched {matched} starts, {unmatched} unmatched (no actual stats)")

    # ── Compute summary statistics ───────────────────────────────────────
    summary = {}
    if starts:
        fpts_errors = [abs(s["fptsError"]) for s in starts]
        summary["totalStarts"] = len(starts)
        summary["mae"] = round(sum(fpts_errors) / len(fpts_errors), 2)
        summary["maxError"] = round(max(fpts_errors), 1)
        summary["minError"] = round(min(fpts_errors), 1)

        # Directional accuracy: did we predict above/below average correctly?
        if len(starts) >= 2:
            avg_actual = sum(s["actualFpts"] for s in starts) / len(starts)
            correct_direction = sum(
                1 for s in starts
                if (s["projFpts"] >= avg_actual) == (s["actualFpts"] >= avg_actual)
            )
            summary["directionalAccuracy"] = round(correct_direction / len(starts) * 100, 1)

        # Per-stat MAE
        stat_maes = {}
        for stat_key in ["ip", "so", "h", "bb", "er", "hb", "w", "l", "sv"]:
            errors = [abs(s["statErrors"].get(stat_key, 0)) for s in starts]
            stat_maes[stat_key] = round(sum(errors) / len(errors), 2)
        summary["statMAE"] = stat_maes

        # Per-stat bias (are we consistently over or under-projecting?)
        stat_biases = {}
        for stat_key in ["ip", "so", "h", "bb", "er", "hb", "w", "l", "sv"]:
            errors = [s["statErrors"].get(stat_key, 0) for s in starts]
            stat_biases[stat_key] = round(sum(errors) / len(errors), 2)
        summary["statBias"] = stat_biases

    # ── Factor contribution analysis ─────────────────────────────────────
    # Compare MAE of the full model vs MAE when each factor is removed.
    # If removing a factor INCREASES MAE, the factor is helping.
    # If removing a factor DECREASES MAE, the factor is hurting.
    factor_analysis = {}
    if starts:
        full_mae = summary["mae"]

        # MAE without wOBA adjustment
        woba_errors = [abs(s["counterfactuals"]["withoutWoba"] - s["actualFpts"]) for s in starts]
        mae_without_woba = round(sum(woba_errors) / len(woba_errors), 2)

        # MAE without park factor
        park_errors = [abs(s["counterfactuals"]["withoutPark"] - s["actualFpts"]) for s in starts]
        mae_without_park = round(sum(park_errors) / len(park_errors), 2)

        # MAE without either matchup adjustment
        both_errors = [abs(s["counterfactuals"]["withoutBoth"] - s["actualFpts"]) for s in starts]
        mae_without_both = round(sum(both_errors) / len(both_errors), 2)

        # MAE without recent form (only meaningful for starts where recent form was applied)
        starts_with_form = [s for s in starts if s["model"].get("recentForm") is not None]
        mae_without_recent_form = None
        if starts_with_form:
            form_errors = [abs(s["counterfactuals"]["withoutRecentForm"] - s["actualFpts"]) for s in starts_with_form]
            mae_without_recent_form = round(sum(form_errors) / len(form_errors), 2)
            # Also compute full-model MAE for just these starts (apples-to-apples)
            form_full_errors = [abs(s["fptsError"]) for s in starts_with_form]
            form_full_mae = round(sum(form_full_errors) / len(form_full_errors), 2)
        else:
            form_full_mae = None

        factor_analysis = {
            "fullModelMAE":   full_mae,
            "woba": {
                "maeWithout":  mae_without_woba,
                "maeWith":     full_mae,
                "impact":      round(mae_without_woba - full_mae, 2),
                "helping":     mae_without_woba > full_mae,
                "description": "Opponent lineup quality adjustment (team wOBA)",
            },
            "park": {
                "maeWithout":  mae_without_park,
                "maeWith":     full_mae,
                "impact":      round(mae_without_park - full_mae, 2),
                "helping":     mae_without_park > full_mae,
                "description": "Park factor adjustment (dampened 50%)",
            },
            "matchupCombined": {
                "maeWithout":  mae_without_both,
                "maeWith":     full_mae,
                "impact":      round(mae_without_both - full_mae, 2),
                "helping":     mae_without_both > full_mae,
                "description": "Both wOBA + park adjustments combined",
            },
            "recentForm": {
                "maeWithout":    mae_without_recent_form,
                "maeWith":       form_full_mae,
                "impact":        round(mae_without_recent_form - form_full_mae, 2) if (mae_without_recent_form is not None and form_full_mae is not None) else None,
                "helping":       (mae_without_recent_form > form_full_mae) if (mae_without_recent_form is not None and form_full_mae is not None) else None,
                "startsAnalyzed": len(starts_with_form),
                "description":   "Recent form weighting (60% season / 40% last 4 starts)",
            },
        }

        print(f"[accuracy.py] Factor analysis: wOBA impact={factor_analysis['woba']['impact']:+.2f}, "
              f"park impact={factor_analysis['park']['impact']:+.2f}, "
              f"combined impact={factor_analysis['matchupCombined']['impact']:+.2f}")

    # Sort starts by date descending
    starts.sort(key=lambda s: s["date"], reverse=True)

    return {
        "starts":          starts,
        "summary":         summary,
        "factorAnalysis":  factor_analysis,
        "unmatchedCount":  unmatched,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        season = int(qs.get("season", ["2026"])[0])
        period = int(qs.get("period", ["1"])[0])
        scope  = qs.get("scope", ["roster"])[0]  # "roster" or "all"

        try:
            payload = get_accuracy_data(season, period, scope=scope)
            payload["scope"] = scope
        except Exception as e:
            payload = {"starts": [], "summary": {}, "error": str(e)}

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
