"""
/api/savant.py — Baseball Savant / Statcast data fetcher
Pulls advanced pitching metrics from baseballsavant.mlb.com CSV endpoints.
No auth required — public data.

Data sources:
  - Expected Statistics: xwOBA, xBA, xSLG, xERA, barrel %, hard hit %
  - Statcast Leaderboard: EV, barrel rate, sweet spot %
  - Pitch Arsenal Stats: whiff %, CSW %, run value per pitch type

These feed the projection model with quality-of-contact and stuff metrics
that are far more predictive than traditional counting stats (ERA, WHIP).

CSV format note:
  Baseball Savant CSVs use a combined name column: "last_name, first_name"
  with values like "Alcantara, Sandy". We parse this into full lowercase names.
"""
import csv
import io
import requests
import unicodedata
from concurrent.futures import ThreadPoolExecutor


SAVANT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/csv,application/csv,text/plain,*/*",
}


def _strip_accents(s: str) -> str:
    """Normalize accented characters for cross-source name matching."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    ).lower()


def _parse_savant_name(row: dict) -> str:
    """
    Extract full name from Savant CSV row.
    Savant uses a single column "last_name, first_name" with values like "Alcantara, Sandy".
    Returns lowercase full name: "sandy alcantara"
    """
    combined = row.get("last_name, first_name", "")
    if not combined:
        # Fallback: try separate columns
        last = row.get("last_name", "").strip()
        first = row.get("first_name", "").strip()
        if last and first:
            return _strip_accents(f"{first} {last}")
        return ""
    # Split "Last, First" into "first last"
    parts = combined.split(",", 1)
    if len(parts) == 2:
        last = parts[0].strip()
        first = parts[1].strip()
        return _strip_accents(f"{first} {last}")
    return _strip_accents(combined.strip())


def _safe_float(val) -> float:
    """Safely convert a value to float, returning 0.0 on failure."""
    try:
        if val is None or val == "":
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(val) -> int:
    """Safely convert a value to int, returning 0 on failure."""
    try:
        if val is None or val == "":
            return 0
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def _parse_csv(text: str) -> list:
    """Parse CSV text, handling the BOM that Savant includes."""
    # Remove BOM if present
    if text.startswith('\ufeff'):
        text = text[1:]
    return list(csv.DictReader(io.StringIO(text)))


def fetch_expected_stats(year: int, min_pa: int = 25) -> dict:
    """
    Fetch expected statistics leaderboard from Baseball Savant.
    Returns { "player_name_lower": { "xwoba": 0.285, ... }, ... }

    Key metrics for projection model:
      - xwoba (est_woba): single best predictor of pitcher quality
      - xba (est_ba): expected batting average allowed
      - xslg (est_slg): expected slugging allowed
      - xera: expected ERA based on quality of contact
      - woba_diff (est_woba - woba): positive = unlucky, negative = lucky
    """
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/expected_statistics"
        f"?type=pitcher&year={year}&position=&team="
        f"&filterType=pa&min={min_pa}&csv=true"
    )
    try:
        r = requests.get(url, headers=SAVANT_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[savant.py] Expected stats returned HTTP {r.status_code}")
            return {}

        rows = _parse_csv(r.text)
        result = {}
        for row in rows:
            name = _parse_savant_name(row)
            if not name:
                continue
            result[name] = {
                "pa":        _safe_int(row.get("pa", 0)),
                "xwoba":     _safe_float(row.get("est_woba", 0)),
                "xba":       _safe_float(row.get("est_ba", 0)),
                "xslg":      _safe_float(row.get("est_slg", 0)),
                "woba":      _safe_float(row.get("woba", 0)),
                "ba":        _safe_float(row.get("ba", 0)),
                "slg":       _safe_float(row.get("slg", 0)),
                "xera":      _safe_float(row.get("xera", 0)),
                "era":       _safe_float(row.get("era", 0)),
                "woba_diff": _safe_float(row.get("est_woba_minus_woba_diff", 0)),
            }
        print(f"[savant.py] Fetched expected stats for {len(result)} pitchers ({year})")
        return result
    except Exception as e:
        print(f"[savant.py] Failed to fetch expected stats: {e}")
        return {}


def fetch_statcast_stats(year: int, min_bbe: int = 25) -> dict:
    """
    Fetch Statcast leaderboard from Baseball Savant.
    Returns { "player_name_lower": { "avg_ev": 88.2, ... }, ... }

    Key metrics:
      - avg_ev (avg_hit_speed): average exit velocity allowed — lower = better
      - ev50: avg of softest 50% of batted balls — lower = better
      - brl_pct (brl_percent): barrel rate — lower = better
      - brl_pa: barrels per PA — lower = better
      - hard_hit_pct: percentage of hard-hit balls — lower = better
      - sweet_spot_pct: launch angle sweet spot % — lower = better for pitchers
    """
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/statcast"
        f"?type=pitcher&year={year}&position=&team="
        f"&min={min_bbe}&csv=true"
    )
    try:
        r = requests.get(url, headers=SAVANT_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[savant.py] Statcast stats returned HTTP {r.status_code}")
            return {}

        rows = _parse_csv(r.text)
        result = {}
        for row in rows:
            name = _parse_savant_name(row)
            if not name:
                continue
            result[name] = {
                "avg_ev":        _safe_float(row.get("avg_hit_speed", 0)),
                "max_ev":        _safe_float(row.get("max_hit_speed", 0)),
                "ev50":          _safe_float(row.get("ev50", 0)),
                "brl_pct":       _safe_float(row.get("brl_percent", 0)),
                "brl_pa":        _safe_float(row.get("brl_pa", 0)),
                "hard_hit_pct":  _safe_float(row.get("hard_hit_percent", 0)),
                "sweet_spot_pct": _safe_float(row.get("anglesweetspotpercent", 0)),
            }
        print(f"[savant.py] Fetched statcast stats for {len(result)} pitchers ({year})")
        return result
    except Exception as e:
        print(f"[savant.py] Failed to fetch statcast stats: {e}")
        return {}


def fetch_pitch_arsenal(year: int, min_pa: int = 25) -> dict:
    """
    Fetch pitch arsenal stats from Baseball Savant.
    Returns { "player_name_lower": [ { pitch_type data }, ... ], ... }

    Note: arsenal data has one row per pitcher per pitch type.
    We return a list of pitch entries per pitcher for detailed analysis.
    Aggregate stats (total whiff %, K %) come from the statcast endpoint.
    """
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
        f"?type=pitcher&pitchType=&year={year}&team="
        f"&min={min_pa}&csv=true"
    )
    try:
        r = requests.get(url, headers=SAVANT_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[savant.py] Pitch arsenal returned HTTP {r.status_code}")
            return {}

        rows = _parse_csv(r.text)
        result = {}
        for row in rows:
            name = _parse_savant_name(row)
            if not name:
                continue
            pitch_entry = {
                "pitch_type":    row.get("pitch_name", row.get("pitch_type", "")),
                "usage_pct":     _safe_float(row.get("pitch_usage", 0)),
                "run_value":     _safe_float(row.get("run_value_per_100", 0)),
                "whiff_pct":     _safe_float(row.get("whiff_percent", 0)),
                "put_away":      _safe_float(row.get("put_away", 0)),
                "ba":            _safe_float(row.get("ba", 0)),
                "slg":           _safe_float(row.get("slg", 0)),
                "xwoba":         _safe_float(row.get("est_woba", 0)),
                "hard_hit_pct":  _safe_float(row.get("hard_hit_percent", 0)),
            }
            if name not in result:
                result[name] = []
            result[name].append(pitch_entry)
        print(f"[savant.py] Fetched pitch arsenal for {len(result)} pitchers ({year})")
        return result
    except Exception as e:
        print(f"[savant.py] Failed to fetch pitch arsenal: {e}")
        return {}


def fetch_all_savant_data(year: int) -> dict:
    """
    Fetch all Savant data in parallel. Returns combined dict keyed by lowercase name.
    Each pitcher gets: { "expected": {...}, "statcast": {...}, "arsenal": [...] }
    """
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_exp = executor.submit(fetch_expected_stats, year)
        f_sc  = executor.submit(fetch_statcast_stats, year)
        f_ars = executor.submit(fetch_pitch_arsenal, year)
        expected = f_exp.result()
        statcast = f_sc.result()
        arsenal  = f_ars.result()

    # Merge all data sources by player name
    all_names = set(expected.keys()) | set(statcast.keys()) | set(arsenal.keys())
    combined = {}
    for name in all_names:
        combined[name] = {
            "expected": expected.get(name, {}),
            "statcast": statcast.get(name, {}),
            "arsenal":  arsenal.get(name, []),
        }

    print(f"[savant.py] Combined Savant data: {len(combined)} unique pitchers")
    return combined