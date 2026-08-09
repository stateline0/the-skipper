"""
api/test_probables.py — unit tests for the three-source probables merge.

Covers the Forecaster reducer + cached fetch wrapper, the Forecaster union
inside get_starts_for_players (projected starts, confirmed-date precedence,
failure fallback), and the hardened ESPN scoreboard fetch (Safari UA,
non-200 logging, zero-event-day diagnostics).
No network — sources are stubbed at the module boundary.

Run:  python3 api/test_probables.py
"""
import io
import os
import sys
import types
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(__file__))

import mlb  # noqa: E402
from mlb import (  # noqa: E402
    _forecaster_entries_to_probables,
    fetch_forecaster_probables,
    fetch_espn_probables,
    get_starts_for_players,
    FORECASTER_STARTS_CACHE_KEY,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────
# Matchup period 18 is 2026-08-03 → 2026-08-09.

def _stub_sources(mlb_data, fp_data, schedule, fc_data):
    """Replace the three source fetchers on the mlb module; return originals."""
    originals = (mlb.fetch_mlb_probables_and_schedule,
                 mlb.fetch_espn_probables,
                 mlb.fetch_forecaster_probables)
    mlb.fetch_mlb_probables_and_schedule = lambda s, e: (mlb_data, {})
    mlb.fetch_espn_probables = lambda s, e: (fp_data, schedule)
    mlb.fetch_forecaster_probables = lambda: fc_data
    return originals


def _restore_sources(originals):
    (mlb.fetch_mlb_probables_and_schedule,
     mlb.fetch_espn_probables,
     mlb.fetch_forecaster_probables) = originals


def _inject_module(name, **attrs):
    """Install a stub module into sys.modules; return the previous entry."""
    prev = sys.modules.get(name)
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return prev


def _restore_module(name, prev):
    if prev is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = prev


# ─── Reducer ────────────────────────────────────────────────────────────────

def test_reducer_dedupes_and_normalizes():
    entries = [
        {"date": "2026-08-08", "pitcher": "Merrill Kelly", "fpts": 8.9},
        {"date": "2026-08-08", "pitcher": "Merrill Kelly", "fpts": 8.9},
        {"date": "2026-08-12", "pitcher": " Merrill Kelly ", "fpts": 8.9},
        {"date": "2026-08-13", "pitcher": "Noah Schultz", "fpts": 1.0,
         "is_placeholder": True},   # placeholder FPTS still names a real start
        {"date": "2026-08-17", "pitcher": None},
        {"date": "", "pitcher": "Ghost Entry"},
    ]
    out = _forecaster_entries_to_probables(entries)
    assert out == {
        "merrill kelly": ["2026-08-08", "2026-08-12"],
        "noah schultz":  ["2026-08-13"],
    }, out


# ─── Cached fetch wrapper ───────────────────────────────────────────────────

def test_wrapper_cache_hit_skips_scrape():
    def _boom():
        raise AssertionError("fetch_forecaster must not be called on cache hit")
    cached_val = {"cached guy": ["2026-08-08"]}
    prev_kv = _inject_module("kv",
                             cache_get=lambda key: cached_val,
                             cache_set=lambda *a, **k: None)
    prev_fc = _inject_module("forecaster", fetch_forecaster=_boom)
    try:
        assert fetch_forecaster_probables() == cached_val
    finally:
        _restore_module("kv", prev_kv)
        _restore_module("forecaster", prev_fc)


def test_wrapper_scrape_error_returns_empty_and_skips_cache():
    writes = []
    prev_kv = _inject_module("kv",
                             cache_get=lambda key: None,
                             cache_set=lambda *a, **k: writes.append(a))
    prev_fc = _inject_module("forecaster",
                             fetch_forecaster=lambda: {"error": "all UAs blocked"})
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert fetch_forecaster_probables() == {}
        assert "all UAs blocked" in buf.getvalue()
        assert writes == []
    finally:
        _restore_module("kv", prev_kv)
        _restore_module("forecaster", prev_fc)


def test_wrapper_success_reduces_and_caches():
    writes = []
    entries = [{"date": "2026-08-08", "pitcher": "Gage Jump", "fpts": 5.5}]
    prev_kv = _inject_module("kv",
                             cache_get=lambda key: None,
                             cache_set=lambda key, data, ttl_seconds=None:
                                 writes.append((key, data, ttl_seconds)))
    prev_fc = _inject_module("forecaster",
                             fetch_forecaster=lambda: {"entries": entries,
                                                       "fetch_note": "ok via safari UA"})
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = fetch_forecaster_probables()
        assert out == {"gage jump": ["2026-08-08"]}
        assert writes == [(FORECASTER_STARTS_CACHE_KEY, out, 3600)]
    finally:
        _restore_module("kv", prev_kv)
        _restore_module("forecaster", prev_fc)


# ─── Three-source merge in get_starts_for_players ──────────────────────────

def test_forecaster_only_pitcher_gets_projected_start():
    originals = _stub_sources(
        mlb_data={},
        fp_data={},
        schedule={"2026-08-08": {"ARI": {"opponent": "LAD", "is_home": True,
                                         "status": "scheduled", "win_prob": None}}},
        # 2026-08-12 is outside period 18 — must be clamped away.
        fc_data={"merrill kelly": ["2026-08-08", "2026-08-12"]},
    )
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            starts, _ = get_starts_for_players(
                ["Merrill Kelly"], 18, team_map={"Merrill Kelly": "ARI"})
    finally:
        _restore_sources(originals)
    entry = starts["Merrill Kelly"]
    assert entry["starts"] == 1
    sd = entry["startDates"][0]
    assert sd["date"] == "2026-08-08"
    assert sd["confirmed"] is False
    assert sd["opponent"] == "LAD"


def test_mlb_confirmed_wins_over_forecaster_same_date():
    originals = _stub_sources(
        mlb_data={"zac thornton": ["2026-08-07"]},
        fp_data={},
        schedule={},
        fc_data={"zac thornton": ["2026-08-07"]},
    )
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            starts, _ = get_starts_for_players(["Zac Thornton"], 18)
    finally:
        _restore_sources(originals)
    entry = starts["Zac Thornton"]
    # Same date from both sources → one entry, confirmed.
    assert entry["starts"] == 1
    assert entry["startDates"] == [
        {"date": "2026-08-07", "confirmed": True, "opponent": ""}]


def test_forecaster_failure_leaves_other_sources_intact():
    originals = _stub_sources(
        mlb_data={"zac thornton": ["2026-08-07"]},
        fp_data={"sean manaea": ["2026-08-09"]},
        schedule={},
        fc_data={},   # wrapper's failure contract: empty dict
    )
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            starts, _ = get_starts_for_players(
                ["Zac Thornton", "Sean Manaea", "Merrill Kelly"], 18)
    finally:
        _restore_sources(originals)
    assert starts["Zac Thornton"]["starts"] == 1
    assert starts["Zac Thornton"]["startDates"][0]["confirmed"] is True
    assert starts["Sean Manaea"]["starts"] == 1
    assert starts["Sean Manaea"]["startDates"][0]["confirmed"] is False
    assert starts["Merrill Kelly"] == {"starts": 0, "startDates": []}


# ─── Hardened scoreboard fetch ─────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code, payload=None, body=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = body

    def json(self):
        return self._payload


class _FakeRequests:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        return self.resp


def test_scoreboard_zero_event_days_logged_with_browser_ua():
    fake = _FakeRequests(_FakeResp(200, {"events": []}))
    orig = mlb.requests
    mlb.requests = fake
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            pitchers, schedule = fetch_espn_probables("2026-08-06", "2026-08-07")
    finally:
        mlb.requests = orig
    assert pitchers == {}
    assert set(schedule.keys()) == {"2026-08-06", "2026-08-07"}
    # Every request carried the Safari UA, not the bare "Mozilla/5.0".
    for call in fake.calls:
        assert "Safari" in call["headers"]["User-Agent"]
    out = buf.getvalue()
    assert "zero events on 2 day(s)" in out
    assert "2026-08-06, 2026-08-07" in out


def test_scoreboard_non_200_logged_and_day_skipped():
    fake = _FakeRequests(_FakeResp(403, body=b"x" * 42))
    orig = mlb.requests
    mlb.requests = fake
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            pitchers, schedule = fetch_espn_probables("2026-08-06", "2026-08-06")
    finally:
        mlb.requests = orig
    assert pitchers == {}
    # Day never enters the schedule dict, so _merge_schedules can fill it.
    assert schedule == {}
    out = buf.getvalue()
    assert "HTTP 403" in out and "42 bytes" in out


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
