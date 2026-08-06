"""
api/test_mlb_schedule.py — unit tests for the MLB Stats API schedule fallback.

Covers the pure schedule builder (_build_mlb_schedule) and the per-date merge
that fills days the ESPN scoreboard came back empty for (_merge_schedules).
No network — fixtures mimic the statsapi /api/v1/schedule response shape.

Run:  python3 api/test_mlb_schedule.py
"""
import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(__file__))

from mlb import _build_mlb_schedule, _merge_schedules  # noqa: E402


def _game(home_id, away_id, state="Preview"):
    return {
        "status": {"abstractGameState": state},
        "teams": {
            "home": {"team": {"id": home_id}},
            "away": {"team": {"id": away_id}},
        },
    }


# Fixture: two days — Aug 6 has BOS(111) @ CLE(114) live and LAD(119) home vs
# ATL(144) not started; Aug 7 has a final NYY(147) @ TOR(141) game plus one
# game with an unknown team id (exhibition) that must be skipped.
MLB_FIXTURE = {
    "dates": [
        {
            "date": "2026-08-06",
            "games": [
                _game(home_id=114, away_id=111, state="Live"),
                _game(home_id=119, away_id=144, state="Preview"),
            ],
        },
        {
            "date": "2026-08-07",
            "games": [
                _game(home_id=141, away_id=147, state="Final"),
                _game(home_id=999, away_id=111, state="Preview"),  # unknown id
            ],
        },
    ]
}


def test_builder_shape_and_status_mapping():
    sched = _build_mlb_schedule(MLB_FIXTURE)
    assert set(sched.keys()) == {"2026-08-06", "2026-08-07"}

    cle = sched["2026-08-06"]["CLE"]
    bos = sched["2026-08-06"]["BOS"]
    assert cle == {"opponent": "BOS", "is_home": True,  "status": "in_progress", "win_prob": None}
    assert bos == {"opponent": "CLE", "is_home": False, "status": "in_progress", "win_prob": None}

    assert sched["2026-08-06"]["LAD"]["status"] == "scheduled"
    assert sched["2026-08-07"]["TOR"]["status"] == "final"
    assert sched["2026-08-07"]["NYY"]["is_home"] is False


def test_builder_skips_unknown_team_ids():
    sched = _build_mlb_schedule(MLB_FIXTURE)
    # The 999 game is dropped entirely — neither side gets an entry.
    day = sched["2026-08-07"]
    assert set(day.keys()) == {"TOR", "NYY"}


def test_builder_empty_input():
    assert _build_mlb_schedule({}) == {}
    assert _build_mlb_schedule({"dates": []}) == {}


def test_merge_fills_only_espn_empty_days():
    espn_entry = {
        "opponent": "CIN", "is_home": True, "status": "in_progress",
        "win_prob": 0.61, "opp_starter": "hunter greene",
        "game_detail": "Bot 5th", "score": "3-2",
    }
    espn = {
        "2026-08-06": {"BOS": espn_entry, "CIN": {"opponent": "BOS", "is_home": False,
                                                 "status": "in_progress", "win_prob": 0.39}},
        "2026-08-07": {},   # scoreboard fetch returned no events this day
        # 2026-08-08 missing entirely (per-day exception path)
    }
    mlb = {
        "2026-08-06": {"BOS": {"opponent": "NYY", "is_home": False,
                               "status": "scheduled", "win_prob": None}},
        "2026-08-07": {"TOR": {"opponent": "NYY", "is_home": True,
                               "status": "final", "win_prob": None}},
        "2026-08-08": {"LAD": {"opponent": "ATL", "is_home": True,
                               "status": "scheduled", "win_prob": None}},
    }
    buf = io.StringIO()
    with redirect_stdout(buf):
        merged = _merge_schedules(espn, mlb)

    # ESPN day preserved verbatim — odds, opp_starter, live detail intact.
    assert merged["2026-08-06"]["BOS"] is espn_entry
    assert "NYY" != merged["2026-08-06"]["BOS"]["opponent"]
    # Empty and missing days filled from MLB.
    assert merged["2026-08-07"]["TOR"]["status"] == "final"
    assert merged["2026-08-08"]["LAD"]["opponent"] == "ATL"
    # One diagnostic naming the fallback and how many days were filled.
    out = buf.getvalue()
    assert "2 day(s)" in out and "MLB Stats API" in out


def test_merge_no_fallback_needed_is_silent():
    espn = {"2026-08-06": {"BOS": {"opponent": "CIN", "is_home": True,
                                   "status": "scheduled", "win_prob": None}}}
    buf = io.StringIO()
    with redirect_stdout(buf):
        merged = _merge_schedules(espn, {"2026-08-06": {"BOS": {"opponent": "XXX",
                                        "is_home": False, "status": "scheduled",
                                        "win_prob": None}}})
    assert merged["2026-08-06"]["BOS"]["opponent"] == "CIN"
    assert buf.getvalue() == ""


def test_merge_both_empty():
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert _merge_schedules({}, {}) == {}
    assert buf.getvalue() == ""


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
