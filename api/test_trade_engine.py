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
    _trade_weights, _fit_log_curve, _perceived_value, _perceived_components,
    _pos_group, _classify_trade, _finder_rank, _sp_remaining_starts,
    _percentile, _replacement_rates, _net_values, TRADE_EDGE_MIN,
)


def test_percentile_interpolates():
    assert _percentile([10, 20, 30, 40], 0.25) == 17.5
    assert _percentile([5], 0.25) == 5
    assert _percentile([], 0.5) is None


def test_replacement_netting_widens_elite_vs_streamer():
    curve = _fit_log_curve([(1, 600), (10, 480), (50, 300), (100, 210), (200, 150)])
    w = _trade_weights(0.44)
    pool = [{"pos": "OF", "seasonBaseRos": r * 100, "horizon": 100, "fullHorizon": 162,
             "surfaceRate": r, "draftPick": dp, "recentHeat": 0}
            for r, dp in [(4.0, 5), (2.0, 80), (1.5, 150), (1.0, 250)]]
    rep = _replacement_rates(pool, pctile=0.25)
    assert "OF" in rep
    elite_net, _, elite_raw, *_ = _net_values(pool[0], curve, w, rep)
    streamer_net, _, streamer_raw, *_ = _net_values(pool[2], curve, w, rep)
    # Over replacement, the elite player towers far more than raw FPTS suggests.
    assert (elite_raw / streamer_raw) < (elite_net / streamer_net)


def test_sp_remaining_starts_caps_late_starters():
    # Healthy mid-season starter: limited by starts-to-full, not the calendar.
    assert _sp_remaining_starts(gs=14, team_games_remaining=90) == round(90 / 5.1, 1)
    # Late starter (e.g. returnee, gs=6): 32-6=26 is impossible with 90 games left
    # → capped to the calendar-feasible ~17.6, NOT 26.
    capped = _sp_remaining_starts(gs=6, team_games_remaining=90)
    assert capped < 26 and capped == round(90 / 5.1, 1)
    # Late season: starts-to-full is the binding limit.
    assert _sp_remaining_starts(gs=30, team_games_remaining=20) == 2.0
    # No team data → fall back to starts-to-full.
    assert _sp_remaining_starts(gs=6, team_games_remaining=None) == 26.0


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
    # Early-pick player slumping: low surface rate but elite draft pedigree (#8).
    # Perceived ROS should sit above the pure-surface ROS (surfaceRate × horizon).
    cold_early = {"pos": "OF", "surfaceRate": 1.0, "horizon": 80, "fullHorizon": 162,
                  "draftPick": 8, "adp": None}
    pv = _perceived_value(cold_early, curve, w, 0.0, {"draft": 250})
    assert pv is not None and pv > 1.0 * 80, pv


def test_perceived_handles_missing_components():
    w = _trade_weights(0.5)
    # No curve and no draft pick → leans entirely on surface rate, never crashes.
    only_surface = {"pos": "1B", "surfaceRate": 3.0, "horizon": 90, "fullHorizon": 162,
                    "draftPick": None, "adp": None}
    assert _perceived_value(only_surface, None, w) is not None
    # No horizon → can't scale to ROS → None (rather than a bogus number).
    no_horizon = {"pos": "1B", "surfaceRate": 3.0, "draftPick": None, "adp": None}
    assert _perceived_value(no_horizon, None, w) is None


def test_perceived_recency_overreaction():
    w = _trade_weights(0.5)
    base = {"pos": "OF", "surfaceRate": 3.0, "horizon": 80, "fullHorizon": 162,
            "draftPick": None, "adp": None}
    hot = {**base, "recentHeat": 0.3}
    cold = {**base, "recentHeat": -0.3}
    pv_hot = _perceived_value(hot, None, w)
    pv_base = _perceived_value(base, None, w)
    pv_cold = _perceived_value(cold, None, w)
    assert pv_hot > pv_base > pv_cold, (pv_hot, pv_base, pv_cold)


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


def test_perceived_components_breakdown():
    curve = _fit_log_curve([(1, 600), (10, 480), (50, 300), (100, 210), (200, 150)])
    w = _trade_weights(0.5)
    row = {"pos": "SP", "horizon": 18, "fullHorizon": 32, "surfaceRate": 12.0,
           "recentHeat": 0.2, "draftPick": 10, "adp": None}
    b = _perceived_components(row, curve, w, 0.0, {"draft": 250})
    assert b and b["perceived"] > 0
    labels = [c["label"] for c in b["components"]]
    assert "Recent & season form" in labels and "Draft pedigree" in labels
    # component ROS contributions should reconstruct the perceived total
    assert abs(sum(c["ros"] for c in b["components"]) - b["perceived"]) < 1.0


def test_market_anchor_lifts_hyped_low_draft_player():
    curve = _fit_log_curve([(1, 600), (10, 480), (50, 300), (100, 210), (200, 150)])
    w = _trade_weights(0.6)  # mid-late season: market anchor carries real weight
    # Late-drafted but widely owned (hyped prospect): ownership rank lifts perceived
    # above what the tiny draft anchor alone would give.
    hyped = {"pos": "SP", "horizon": 18, "fullHorizon": 32, "surfaceRate": 10.0,
             "recentHeat": 0.0, "draftPick": 210, "adp": None, "ownershipRank": 5}
    no_market = {**hyped, "ownershipRank": None}
    floors = {"draft": 250, "own": 250, "adp": None}
    assert _perceived_value(hyped, curve, w, 0.0, floors) > _perceived_value(no_market, curve, w, 0.0, floors)


def test_weights_include_market_and_sum_to_one():
    for p in (0.0, 0.5, 1.0):
        w = _trade_weights(p)
        assert "market" in w and abs(sum(w.values()) - 1.0) < 1e-9, (p, w)
    assert _trade_weights(1.0)["market"] > _trade_weights(0.0)["market"]  # migrates up


def test_undrafted_draft_floor_drags_perceived_down():
    curve = _fit_log_curve([(1, 600), (10, 480), (50, 300), (100, 210), (200, 150)])
    w = _trade_weights(0.44)
    base = {"pos": "SP", "horizon": 18, "fullHorizon": 32, "surfaceRate": 12.0,
            "recentHeat": 0.3, "adp": None, "ownershipRank": 150, "ownPct": 40}
    drafted = {**base, "draftPick": 20}
    undrafted = {**base, "draftFloor": 300}  # no draftPick → uses the floor
    floors = {"draft": 300, "own": 300, "adp": None}
    # Undrafted still gets a Draft pedigree component (not dropped), labeled as such,
    # but scored at the floor it nets to ~0.
    comp = _perceived_components(undrafted, curve, w, 0.0, floors)
    draft_part = next((c for c in comp["components"] if c["label"] == "Draft pedigree"), None)
    assert draft_part is not None and draft_part["detail"] == "undrafted — waiver add"
    assert draft_part["ros"] == 0.0
    # And being undrafted drags perceived BELOW a well-drafted version of the player.
    assert _perceived_value(undrafted, curve, w, 0.0, floors) < _perceived_value(drafted, curve, w, 0.0, floors)


def test_finder_rank_keeps_steals_and_wins():
    keep, score, cls = _finder_rank(edge=30, perc_give=320, perc_get=295)  # steal
    assert keep and cls["verdict"] == "steal" and score == 35.0
    keep2, score2, _ = _finder_rank(edge=30, perc_give=300, perc_get=300)  # fair win
    assert keep2 and score2 == 30.0
    keep3, _, _ = _finder_rank(edge=30, perc_give=200, perc_get=320)       # lopsided → drop
    assert not keep3
    keep4, _, _ = _finder_rank(edge=-5, perc_give=300, perc_get=300)       # losing → drop
    assert not keep4


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
