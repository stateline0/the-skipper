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