"""
api/test_trade_engine.py — unit tests for the deterministic trade-engine core.

Covers the pure valuation math (no ESPN / network): time-varying weights, the
draft-value curve fit, the perceived-value blend, and the verdict classifier.
The ESPN-dependent paths (build_trade_eval, build_league_rosters) are exercised
in prod, not here.

Run:  python3 api/test_trade_engine.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from hitters import (  # noqa: E402
    _trade_weights, _fit_log_curve, _perceived_value, _pos_group,
    _classify_trade, TRADE_EDGE_MIN,
)


def test_weights_sum_to_one():
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        w = _trade_weights(p)
        assert abs(sum(w.values()) - 1.0) < 1e-9, (p, w)


def test_weights_migrate_to_production():
    early, late = _trade_weights(0.0), _trade_weights(1.0)
    assert late["prod"] > early["prod"], (early, late)
    assert early["draft"] > late["draft"], (early, late)


def test_curve_monotone_decreasing():
    curve = _fit_log_curve([(1, 600), (10, 480), (25, 380), (50, 300), (100, 210), (200, 150)])
    assert curve is not None
    vals = [curve(pk) for pk in (1, 10, 50, 150)]
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)), vals


def test_curve_none_on_sparse():
    assert _fit_log_curve([(1, 100), (2, 90)]) is None


def test_perceived_blend_draft_anchor_props_up_cold_player():
    curve = _fit_log_curve([(1, 600), (10, 480), (50, 300), (100, 210), (200, 150)])
    w = _trade_weights(0.5)
    # Early-pick player slumping: draft anchor should keep perceived value above
    # the raw cold production.
    cold_early = {"pos": "OF", "fullSeasonPace": 180, "draftPick": 8, "adp": None}
    pv = _perceived_value(cold_early, curve, w)
    assert pv is not None and pv > 180, pv


def test_perceived_handles_missing_components():
    w = _trade_weights(0.5)
    # No curve and no draft pick → leans entirely on production, never crashes.
    only_prod = {"pos": "1B", "fullSeasonPace": 300, "draftPick": None, "adp": None}
    assert _perceived_value(only_prod, None, w) is not None
    empty = {"pos": "1B", "fullSeasonPace": None, "draftPick": None, "adp": None}
    assert _perceived_value(empty, None, w) is None


def test_pos_group():
    assert _pos_group({"pos": "2B/SS"}) in ("SS", "2B")
    assert _pos_group({"posEligible": "SP"}) == "SP"
    assert _pos_group({"pos": "C"}) == "C"


def test_classify_steal_win_lopsided_avoid_marginal():
    # The dream: you hand over MORE perceived value (they think they won) yet
    # still gain ROS FPTS → steal.
    steal = _classify_trade(edge=30, perc_give=320, perc_get=295)
    assert steal["verdict"] == "steal" and steal["fairToThem"] and steal["sweetened"]
    # Big edge, fair-ish but not sweetened → win.
    win = _classify_trade(edge=30, perc_give=300, perc_get=300)
    assert win["verdict"] == "win" and win["fairToThem"]
    # Big edge but you're visibly hogging value → lopsided (they balk).
    lop = _classify_trade(edge=30, perc_give=200, perc_get=320)
    assert lop["verdict"] == "lopsided" and not lop["fairToThem"]
    # You lose ROS points → avoid.
    avoid = _classify_trade(edge=-20, perc_give=300, perc_get=295)
    assert avoid["verdict"] == "avoid"
    # Tiny edge → marginal.
    marg = _classify_trade(edge=TRADE_EDGE_MIN - 1, perc_give=300, perc_get=300)
    assert marg["verdict"] == "marginal"


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
