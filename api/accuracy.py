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


def _fetch_espn_lookup(season: int, period=None) -> dict:
    """
    Read all ESPN-locked projection keys and return a {"slug:date" → fpts}
    lookup, skipping placeholder entries.

    period=None (default) aggregates across all periods (`projection-espn:
    {season}:*`). period=N scans a single period (legacy path, still used
    if an external caller passes an explicit period).

    Returns {} if KV is unavailable or no keys exist. Used by both the
    normal accuracy path and the early-return path so ESPN data is always
    surfaced when scope=="all", even when Skipper has no proj2all: keys.
    """
    if not KV_AVAILABLE or _redis is None:
        return {}
    pattern = (
        f"projection-espn:{season}:{period}:*"
        if period is not None
        else f"projection-espn:{season}:*"
    )
    keys = _redis.keys(pattern)
    lookup = {}
    for key in keys or []:
        parts = key.split(":")
        if len(parts) != 5:
            continue
        _, _, _, slug, date = parts
        val = _redis.get(key)
        if val is None:
            continue
        try:
            data = json.loads(val)
            if data.get("is_placeholder"):
                continue
            fpts = data.get("fpts")
            if fpts is None:
                continue
            lookup[f"{slug}:{date}"] = fpts
        except (json.JSONDecodeError, TypeError):
            continue
    return lookup


def _compute_espn_summary(espn_lookup: dict, starts: list) -> dict:
    """
    Build the espnSummary block by intersecting the ESPN lookup with the
    matched starts list. Mutates each matched start in place to attach
    espnFpts/espnError so the frontend's optional ESPN column can render.

    When the intersection is empty (no overlap yet), returns a summary with
    mae=None and the espnKeysFound count populated so the frontend can
    render an informative empty state.
    """
    intersection = []
    for s in starts:
        lookup_key = f"{s['slug']}:{s['date']}"
        espn_fpts = espn_lookup.get(lookup_key)
        if espn_fpts is not None:
            s["espnFpts"] = espn_fpts
            s["espnError"] = round(espn_fpts - s["actualFpts"], 1)
            intersection.append(s)

    if intersection:
        espn_errors = [abs(s["espnError"]) for s in intersection]
        skipper_errors = [abs(s["fptsError"]) for s in intersection]
        return {
            "totalStarts":               len(intersection),
            "mae":                       round(sum(espn_errors) / len(espn_errors), 2),
            "skipperMaeOnIntersection":  round(sum(skipper_errors) / len(skipper_errors), 2),
            "espnKeysFound":             len(espn_lookup),
        }
    return {
        "totalStarts":               0,
        "mae":                       None,
        "skipperMaeOnIntersection":  None,
        "espnKeysFound":             len(espn_lookup),
    }


def get_accuracy_data(season: int, period=None, scope: str = "roster") -> dict:
    """
    Match v2 locked projections against actual stats.

    scope="roster" — proj2: keys + cache:daily: actuals. Starts are filtered
                     to those made while the pitcher was actually on my roster
                     (using cache:daily `my_team` membership) — without this
                     filter, proj2: leaks Free Agents that were locked the
                     moment anyone viewed the Free Agents page, polluting the
                     "My Roster" scope with pitchers who were never on my team.
    scope="all"    — proj2all: keys + actual-all: actuals. Always whole-MLB;
                     no roster filter applies.

    period=None (default) aggregates across all 22 matchup periods — the
    "all-time" view. period=N (1–22) retains the legacy single-period scan
    for backward compatibility with any external caller still passing one.

    Returns comparison data for every start where both projected and actual
    exist (and, for roster scope, the pitcher was on my team that day).
    """
    if not KV_AVAILABLE or _redis is None:
        return {"starts": [], "summary": {}, "error": "KV not available"}

    # ── Determine key prefixes based on scope + period ───────────────────
    proj_prefix = "proj2all" if scope == "all" else "proj2"
    period_glob = f"{period}" if period is not None else "*"

    # ── Fetch all v2 locked projections ───────────────────────────────────
    proj_keys = _redis.keys(f"{proj_prefix}:{season}:{period_glob}:*")
    if not proj_keys:
        # No Skipper projections, but ESPN data may still exist for this
        # period — surface it so the All MLB scope's head-to-head block
        # can render its informative empty state instead of vanishing.
        empty_response = {
            "starts": [],
            "summary": {},
            "message": "No v2 projections found",
        }
        if scope == "all":
            empty_response["espnSummary"] = _compute_espn_summary(_fetch_espn_lookup(season, period), [])
        return empty_response

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

    # Roster-membership index — only populated for scope="roster". Maps each
    # date to the SET of full player names that were on my team that day,
    # using the `my_team` block that `get_actual_fpts()` writes into each
    # `cache:daily:{date}` entry. Used below to filter out proj2: locks for
    # free agents who were viewed through the FA page but never rostered.
    my_team_by_date: dict = {}

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
                # Capture roster membership for this date (may be {} if the
                # cache entry predates my_team tracking — treat as no-roster
                # and fall through to the safe-drop path in the match loop).
                my_team_members = daily_data.get("my_team") or {}
                my_team_by_date[date] = set(my_team_members.keys())
        except (json.JSONDecodeError, TypeError):
            continue

    print(f"[accuracy.py] Found actual stats for {len(actuals_by_date)} dates"
          + (f", roster membership for {len(my_team_by_date)} dates" if scope == "roster" else ""))

    # ── Match projections to actuals ─────────────────────────────────────
    def make_slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")

    starts = []
    matched = 0
    unmatched = 0
    filtered_non_roster = 0  # scope="roster" only: dropped because pitcher
                             # was not on my team that day (FA leak fix)

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

        # ── Roster-scope FA leak filter ──────────────────────────────────
        # proj2: keys accumulate locks for any pitcher viewed through the
        # Free Agents or My Team surfaces — so a pitcher never actually
        # rostered can appear in the proj2 namespace. cache:daily `my_team`
        # is the source of truth for who was on the roster on a given day
        # (session 19 PR #81 uses the same dict for dropped-streamer
        # intersection). If the player wasn't on my team that day, skip.
        # Conservative behavior: if no my_team data exists for the date
        # (pre-my_team cache entry), drop the start rather than risk
        # re-polluting the roster view.
        if scope == "roster":
            rostered_that_day = my_team_by_date.get(date)
            if rostered_that_day is None or matched_name not in rostered_that_day:
                filtered_non_roster += 1
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

    print(
        f"[accuracy.py] Matched {matched} starts, "
        f"{unmatched} unmatched (no actual stats)"
        + (f", {filtered_non_roster} filtered (not on roster that day)" if scope == "roster" else "")
    )

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

    # ── ESPN projection overlay (scope="all" only) ───────────────────────
    # _compute_espn_summary mutates each matched start in place to attach
    # espnFpts/espnError, then returns the head-to-head summary (or a
    # "no overlap yet" summary when the intersection is empty).
    espn_summary = None
    if scope == "all":
        espn_lookup = _fetch_espn_lookup(season, period)
        print(f"[accuracy.py] Found {len(espn_lookup)} ESPN-locked projections (scope=all)")
        espn_summary = _compute_espn_summary(espn_lookup, starts)
        if espn_summary["mae"] is not None:
            print(f"[accuracy.py] ESPN head-to-head on {espn_summary['totalStarts']} starts: "
                  f"ESPN MAE={espn_summary['mae']}, Skipper MAE={espn_summary['skipperMaeOnIntersection']}")
        else:
            print(f"[accuracy.py] ESPN head-to-head: no completed overlap yet "
                  f"(espn_keys={len(espn_lookup)}, matched_starts={len(starts)})")

    # Sort starts by date descending
    starts.sort(key=lambda s: s["date"], reverse=True)

    return {
        "starts":             starts,
        "summary":            summary,
        "factorAnalysis":     factor_analysis,
        "unmatchedCount":     unmatched,
        "filteredNonRoster":  filtered_non_roster,  # scope="roster" only
        "espnSummary":        espn_summary,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        season = int(qs.get("season", ["2026"])[0])
        # period is now optional — omit or pass empty string for the all-time
        # view (aggregates across all 22 periods). An explicit integer still
        # scopes to a single period for backward compat with any external caller.
        period_raw = qs.get("period", [""])[0]
        try:
            period = int(period_raw) if period_raw else None
        except ValueError:
            period = None
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
