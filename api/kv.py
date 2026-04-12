"""
api/kv.py — Upstash Redis helpers for locked projection storage.

A "locked projection" is the model's FPTS estimate for a pitcher's start,
frozen at the moment the game begins. Once locked, it never changes — giving
us a permanent record to compare against actual FPTS for model accuracy tracking.

Key schema:
  proj:{season}:{period}:{player_name_slug}:{date}  →  float (e.g. 14.2)

Example:
  proj:2026:2:garrett-crochet:2026-04-07  →  18.4

Why this schema?
  - Prefix queries let us fetch all projections for a period at once
  - Player name slug is lowercase + hyphens — safe for Redis keys
  - Date is ISO format for easy sorting
"""

import os
import re

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
except Exception as e:
    print(f"[kv.py] Redis init failed: {e}")
    _redis = None
    KV_AVAILABLE = False


def _make_key(season: int, period: int, player_name: str, date: str) -> str:
    """
    Build a Redis key for a locked projection.
    'Garrett Crochet', date '2026-04-07', period 2, season 2026
    → 'proj:2026:2:garrett-crochet:2026-04-07'
    """
    slug = re.sub(r"[^a-z0-9]+", "-", player_name.lower().strip()).strip("-")
    return f"proj:{season}:{period}:{slug}:{date}"


def get_locked_projection(season: int, period: int, player_name: str, date: str):
    """
    Returns the locked projection float for this player+date, or None if
    no projection has been locked yet.
    """
    if not KV_AVAILABLE or _redis is None:
        return None
    try:
        key = _make_key(season, period, player_name, date)
        val = _redis.get(key)
        return float(val) if val is not None else None
    except Exception as e:
        print(f"[kv.py] get failed for {player_name} {date}: {e}")
        return None


def set_locked_projection(season: int, period: int, player_name: str, date: str, fpts: float):
    """
    Locks a projection into Redis. Safe to call multiple times —
    will not overwrite an existing locked value.
    """
    if not KV_AVAILABLE or _redis is None:
        return
    try:
        key = _make_key(season, period, player_name, date)
        # NX = only set if key does Not eXist — never overwrite a locked value
        _redis.set(key, str(round(fpts, 1)), nx=True)
        print(f"[kv.py] Locked projection: {key} = {fpts}")
    except Exception as e:
        print(f"[kv.py] set failed for {player_name} {date}: {e}")


def get_all_locked_projections(season: int, period: int) -> dict:
    """
    Returns all locked projections for a given season + period as a nested dict:
    { "Garrett Crochet": { "2026-04-07": 18.4, "2026-04-12": 16.1 }, ... }

    Used by the frontend to display locked projections in past/today cells
    and for model accuracy analysis.
    """
    if not KV_AVAILABLE or _redis is None:
        return {}
    try:
        pattern = f"proj:{season}:{period}:*"
        keys = _redis.keys(pattern)
        if not keys:
            return {}

        result = {}
        for key in keys:
            # key format: proj:{season}:{period}:{slug}:{date}
            parts = key.split(":")
            if len(parts) != 5:
                continue
            _, _, _, slug, date = parts
            val = _redis.get(key)
            if val is None:
                continue

            # Convert slug back to display name isn't possible — we store
            # the original name separately. Instead we key by slug and let
            # espn.py match by building the slug from the player's full name.
            result.setdefault(slug, {})[date] = float(val)

        return result
    except Exception as e:
        print(f"[kv.py] get_all failed for {season}/{period}: {e}")
        return {}
        
def cache_get(key: str) -> dict:
    """
    Retrieve a cached JSON value from Redis.
    Returns the parsed dict, or None if not found or expired.
    Redis handles TTL expiry automatically — if the key expired, get() returns None.
    """
    if not KV_AVAILABLE or _redis is None:
        return None
    try:
        val = _redis.get(key)
        if val is None:
            return None
        import json
        return json.loads(val)
    except Exception as e:
        print(f"[kv.py] cache_get failed for {key}: {e}")
        return None

def cache_set(key: str, data: dict, ttl_seconds: int = None):
    """
    Store a JSON value in Redis with optional TTL.
    ttl_seconds=None means permanent (no expiry) — use for historical data.
    ttl_seconds=86400 means 24 hours — use for current-season data.
    """
    if not KV_AVAILABLE or _redis is None:
        return
    try:
        import json
        val = json.dumps(data)
        if ttl_seconds:
            _redis.set(key, val, ex=ttl_seconds)
        else:
            _redis.set(key, val)
        print(f"[kv.py] Cached {key} ({len(val)} bytes, TTL={ttl_seconds or 'permanent'})")
    except Exception as e:
        print(f"[kv.py] cache_set failed for {key}: {e}")


# ── V2: Rich projection locking (stat-level breakdown) ───────────────
#
# The v1 functions above store a single float (total FPTS per start).
# V2 stores a full JSON object per start with individual stat projections,
# matchup context, and model metadata. This enables:
#   - Per-stat accuracy tracking (projected K vs actual K, etc.)
#   - Model debugging (which component is causing errors?)
#   - Factor contribution analysis (how much did park factor help/hurt?)
#
# Key schema:
#   proj2:{season}:{period}:{player-slug}:{date} → JSON


def _make_key_v2(season: int, period: int, player_name: str, date: str) -> str:
    """Build a Redis key for a v2 locked projection (JSON breakdown)."""
    slug = re.sub(r"[^a-z0-9]+", "-", player_name.lower().strip()).strip("-")
    return f"proj2:{season}:{period}:{slug}:{date}"


def set_locked_projection_v2(season: int, period: int, player_name: str, date: str, breakdown: dict):
    """
    Lock a full projection breakdown into Redis as JSON.
    Uses NX flag — will not overwrite an existing locked value.

    breakdown should contain:
      - fpts: float — the final per-start FPTS projection
      - stats: dict — per-stat projections {ip, so, h, bb, er, hb, w, l, sv}
      - matchup: dict — {opponent, woba, park, parkTeam, isHome}
      - model: dict — {type, blendWeight, recentForm, seasonBase, adjustedBase}
    """
    if not KV_AVAILABLE or _redis is None:
        return
    try:
        import json
        key = _make_key_v2(season, period, player_name, date)
        val = json.dumps(breakdown)
        _redis.set(key, val, nx=True)
        print(f"[kv.py] Locked v2 projection: {key} ({len(val)} bytes)")
    except Exception as e:
        print(f"[kv.py] set_v2 failed for {player_name} {date}: {e}")


def get_locked_projection_v2(season: int, period: int, player_name: str, date: str) -> dict:
    """
    Returns the full locked projection breakdown for this player+date,
    or None if no v2 projection has been locked yet.
    """
    if not KV_AVAILABLE or _redis is None:
        return None
    try:
        import json
        key = _make_key_v2(season, period, player_name, date)
        val = _redis.get(key)
        if val is None:
            return None
        return json.loads(val)
    except Exception as e:
        print(f"[kv.py] get_v2 failed for {player_name} {date}: {e}")
        return None


def get_all_locked_projections_v2(season: int, period: int) -> dict:
    """
    Returns all v2 locked projections for a season + period as a nested dict:
    {
      "garrett-crochet": {
        "2026-04-07": { "fpts": 17.1, "stats": {...}, "matchup": {...}, "model": {...} },
        "2026-04-12": { "fpts": 16.5, "stats": {...}, "matchup": {...}, "model": {...} },
      },
      ...
    }
    """
    if not KV_AVAILABLE or _redis is None:
        return {}
    try:
        import json
        pattern = f"proj2:{season}:{period}:*"
        keys = _redis.keys(pattern)
        if not keys:
            return {}

        result = {}
        for key in keys:
            # key format: proj2:{season}:{period}:{slug}:{date}
            parts = key.split(":")
            if len(parts) != 5:
                continue
            _, _, _, slug, date = parts
            val = _redis.get(key)
            if val is None:
                continue
            try:
                result.setdefault(slug, {})[date] = json.loads(val)
            except json.JSONDecodeError:
                continue

        return result
    except Exception as e:
        print(f"[kv.py] get_all_v2 failed for {season}/{period}: {e}")
        return {}