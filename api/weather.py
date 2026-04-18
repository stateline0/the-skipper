"""
/api/weather.py — Weather data fetcher for the projection model.

Phase 1 (this module):
  - PARK_COORDS: lat/lng for all 30 MLB parks
  - DOME_PARKS: indoor/retractable parks that always return neutral (1.0)
  - fetch_weather(): Open-Meteo hourly client, 7pm local game-time
  - compute_temp_factor(): dampened linear temp → run environment multiplier
  - get_weather_factor(): orchestrator with 3hr TTL cache, dome override,
                          safe fallback to 1.0 on any failure
  - BaseHTTPRequestHandler: diagnostic endpoint at /api/weather?park=X&date=Y
                            for verifying forecasts before wiring into projections

Phase 2 (future PR):
  - Wind direction model (requires PARK_OUTFIELD_BEARING per park)
  - Wire weather_factor into get_projected_fpts() as per-start multiplier
  - Surface in ProjectionTooltip and v2 locked projection breakdown

Data source: Open-Meteo (https://open-meteo.com)
  - Free, no auth, public API
  - Hourly forecast 16 days out
"""

import json
import os
import sys
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Park coordinates — home plate lat/lng for 30 MLB parks
# Accuracy within ±0.01° is fine; Open-Meteo resolution is ~1km.
# ---------------------------------------------------------------------------
PARK_COORDS = {
    "BAL": (39.2839, -76.6218),    # Camden Yards
    "BOS": (42.3467, -71.0972),    # Fenway Park
    "LAA": (33.8003, -117.8827),   # Angel Stadium
    "CWS": (41.8299, -87.6338),    # Rate Field
    "CLE": (41.4962, -81.6852),    # Progressive Field
    "DET": (42.3390, -83.0485),    # Comerica Park
    "KC":  (39.0517, -94.4803),    # Kauffman Stadium
    "MIL": (43.0280, -87.9712),    # American Family Field (retractable)
    "MIN": (44.9817, -93.2776),    # Target Field
    "NYY": (40.8296, -73.9262),    # Yankee Stadium
    "ATH": (37.7516, -122.2005),   # Oakland Coliseum
    "SEA": (47.5914, -122.3325),   # T-Mobile Park (retractable)
    "TEX": (32.7473, -97.0847),    # Globe Life Field (retractable)
    "TOR": (43.6414, -79.3894),    # Rogers Centre (retractable)
    "ATL": (33.8908, -84.4678),    # Truist Park
    "CHC": (41.9484, -87.6553),    # Wrigley Field
    "CIN": (39.0975, -84.5077),    # Great American Ball Park
    "HOU": (29.7572, -95.3556),    # Daikin Park (retractable)
    "LAD": (34.0739, -118.2400),   # Dodger Stadium
    "WSH": (38.8730, -77.0074),    # Nationals Park
    "NYM": (40.7571, -73.8458),    # Citi Field
    "PHI": (39.9061, -75.1665),    # Citizens Bank Park
    "PIT": (40.4469, -80.0057),    # PNC Park
    "STL": (38.6226, -90.1928),    # Busch Stadium
    "SD":  (32.7073, -117.1566),   # Petco Park
    "SF":  (37.7786, -122.3893),   # Oracle Park
    "COL": (39.7559, -104.9942),   # Coors Field
    "MIA": (25.7781, -80.2195),    # loanDepot park (retractable, usually closed)
    "ARI": (33.4453, -112.0667),   # Chase Field (retractable, closed in heat)
    "TB":  (27.7683, -82.6534),    # Tropicana Field (permanent dome)
}


# Parks whose roof is reliably closed, so outside weather has no effect.
# Retractables are conservatively included — we'd rather ship a neutral
# factor than apply outside weather to an indoor game.
DOME_PARKS = {
    "TB",    # Tropicana (permanent dome)
    "TOR",   # Rogers Centre (retractable, often closed)
    "MIL",   # American Family (retractable)
    "ARI",   # Chase Field (retractable, closed in summer heat)
    "HOU",   # Daikin Park (retractable)
    "MIA",   # loanDepot park (retractable, usually closed)
    "SEA",   # T-Mobile Park (retractable)
    "TEX",   # Globe Life Field (retractable, closed in summer heat)
}


# ---------------------------------------------------------------------------
# Open-Meteo client
# ---------------------------------------------------------------------------

def fetch_weather(lat: float, lng: float, date_str: str) -> dict:
    """
    Fetch hourly weather from Open-Meteo for the given lat/lng + date.
    Picks the 7pm local hour (typical MLB game start) as representative.
    Falls back to 1pm local if 7pm data is unavailable.

    Returns { temp_f, wind_mph, wind_dir_deg, hour } or None on failure.
    """
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":         lat,
                "longitude":        lng,
                "hourly":           "temperature_2m,wind_speed_10m,wind_direction_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit":  "mph",
                "timezone":         "auto",
                "start_date":       date_str,
                "end_date":         date_str,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[weather.py] Open-Meteo returned {r.status_code} for "
                  f"{date_str} @ {lat},{lng}")
            return None

        data = r.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("wind_speed_10m", [])
        dirs  = hourly.get("wind_direction_10m", [])

        if not times or not temps:
            print(f"[weather.py] Empty hourly data for {date_str} @ {lat},{lng}")
            return None

        # Find the 7pm local hour (games typically start 7-8pm)
        idx = None
        for i, t in enumerate(times):
            if t.endswith("T19:00"):
                idx = i
                break

        # Fallback: 1pm if 7pm not in response, or first available hour
        if idx is None:
            for i, t in enumerate(times):
                if t.endswith("T13:00"):
                    idx = i
                    break
        if idx is None:
            idx = min(len(times) - 1, 0)

        if idx >= len(temps):
            print(f"[weather.py] Index {idx} out of range for {date_str}")
            return None

        return {
            "temp_f":       round(temps[idx], 1),
            "wind_mph":     round(winds[idx], 1) if idx < len(winds) else None,
            "wind_dir_deg": round(dirs[idx], 0) if idx < len(dirs) else None,
            "hour":         times[idx],
        }

    except Exception as e:
        print(f"[weather.py] fetch_weather failed for {date_str} @ "
              f"{lat},{lng}: {e}")
        return None


# ---------------------------------------------------------------------------
# Factor computation
# ---------------------------------------------------------------------------

def compute_temp_factor(temp_f: float) -> float:
    """
    Temperature → run-environment multiplier.

    Baseline: 70°F = 1.0 (neutral).
    Each 10°F off baseline shifts raw run environment ~1%.
    Dampened 50% because only H/ER are temp-sensitive, K/IP are not.
    Capped ±5% to prevent extreme weather from breaking the model.

    Examples:
      40°F (cold)      → raw 0.970, dampened 0.985
      70°F (baseline)  → 1.000
      95°F (hot)       → raw 1.025, dampened 1.0125
    """
    raw = 1.0 + (temp_f - 70.0) / 1000.0
    dampened = 1.0 + (raw - 1.0) * 0.5
    return max(0.95, min(1.05, round(dampened, 4)))


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def get_weather_factor(park_abbrev: str, date_str: str) -> dict:
    """
    Returns {
      "factor": float,               # run-environment factor (1.0 = neutral)
      "temp_f": float | None,
      "wind_mph": float | None,
      "wind_dir_deg": float | None,
      "source": "dome" | "forecast" | "default",
      "park": park_abbrev,
      "date": date_str,
    }

    Caching: 3-hour TTL under cache:weather:{park}:{date}.
    Domes: always return factor=1.0 without hitting Open-Meteo.
    Failure: returns factor=1.0 neutral on any error — never breaks caller.
    """
    # Import here so this module can be loaded/tested without Redis set up
    try:
        from kv import cache_get, cache_set
    except Exception:
        cache_get = lambda k: None
        cache_set = lambda k, v, ttl_seconds=None: None

    # Dome override — skip API call, always neutral
    if park_abbrev in DOME_PARKS:
        return {
            "factor":       1.0,
            "temp_f":       None,
            "wind_mph":     None,
            "wind_dir_deg": None,
            "source":       "dome",
            "park":         park_abbrev,
            "date":         date_str,
        }

    coords = PARK_COORDS.get(park_abbrev)
    if not coords:
        print(f"[weather.py] Unknown park abbrev '{park_abbrev}' — "
              f"returning neutral factor")
        return {
            "factor":       1.0,
            "temp_f":       None,
            "wind_mph":     None,
            "wind_dir_deg": None,
            "source":       "default",
            "park":         park_abbrev,
            "date":         date_str,
        }

    # Cache lookup
    cache_key = f"cache:weather:{park_abbrev}:{date_str}"
    try:
        cached = cache_get(cache_key)
        if cached:
            return cached
    except Exception:
        pass

    # Fetch fresh forecast
    lat, lng = coords
    wx = fetch_weather(lat, lng, date_str)
    if not wx:
        return {
            "factor":       1.0,
            "temp_f":       None,
            "wind_mph":     None,
            "wind_dir_deg": None,
            "source":       "default",
            "park":         park_abbrev,
            "date":         date_str,
        }

    factor = compute_temp_factor(wx["temp_f"])
    result = {
        "factor":       factor,
        "temp_f":       wx["temp_f"],
        "wind_mph":     wx["wind_mph"],
        "wind_dir_deg": wx["wind_dir_deg"],
        "source":       "forecast",
        "park":         park_abbrev,
        "date":         date_str,
    }

    try:
        cache_set(cache_key, result, ttl_seconds=10800)  # 3 hours
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Diagnostic endpoint — /api/weather?park=NYY&date=2026-04-18
#
# Purpose: verify Open-Meteo + caching works in production before wiring
# weather_factor into the projection model. Returns the same dict as
# get_weather_factor() for inspection.
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        park = (qs.get("park", [""])[0] or "").upper()
        date_str = qs.get("date", [""])[0] or datetime.utcnow().date().isoformat()

        if not park:
            self._respond(400, {
                "ok": False,
                "error": "Missing required query param 'park' (e.g. ?park=NYY)",
            })
            return

        result = get_weather_factor(park, date_str)
        self._respond(200, {"ok": True, **result})

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass
