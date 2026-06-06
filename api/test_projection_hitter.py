"""
Unit tests for api/projection_hitter.py — the baseline (Phase 0–1) hitter
projection math. Pure-Python, no network: run with `python api/test_projection_hitter.py`.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from projection_hitter import (
    DEFAULT_HITTER_SCORING, ESPN_HITTING_STAT_IDS,
    parse_hitter_scoring, apply_hitter_formula, per_game_vector,
    blend_vectors, pa_blend_weight, apply_factors,
    get_projected_hitter_fpts,
)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# A realistic full-season hitting stat line (≈ a strong everyday bat).
SEASON_2026 = {
    "gamesPlayed": 150, "plateAppearances": 650, "atBats": 580,
    "hits": 174, "doubles": 32, "triples": 3, "homeRuns": 30,
    "runs": 95, "rbi": 92, "baseOnBalls": 60, "hitByPitch": 6,
    "stolenBases": 12, "caughtStealing": 4, "strikeOuts": 120,
}


def test_per_game_vector_singles_and_division():
    v = per_game_vector(SEASON_2026, 150)
    # singles = hits - 2b - 3b - hr = 174 - 32 - 3 - 30 = 109
    assert approx(v["1b"], 109 / 150), v["1b"]
    assert approx(v["hr"], 30 / 150), v["hr"]
    assert approx(v["h"], 174 / 150), v["h"]
    # hit types reconstruct total hits
    assert approx(v["1b"] + v["2b"] + v["3b"] + v["hr"], v["h"])
    print("✓ per_game_vector: singles derivation + per-game division")


def test_total_bases():
    v = per_game_vector(SEASON_2026, 150)
    # TB = 1B + 2*2B + 3*3B + 4*HR = 109 + 64 + 9 + 120 = 302
    assert approx(v["tb"], 302 / 150), v["tb"]
    print("✓ per_game_vector: total bases = 1B + 2·2B + 3·3B + 4·HR")


def test_per_game_vector_min_games():
    assert per_game_vector(SEASON_2026, 5) is None  # below MIN_GAMES
    print("✓ per_game_vector: returns None below MIN_GAMES")


def test_apply_formula_dot_product():
    v = per_game_vector(SEASON_2026, 150)
    fpts = apply_hitter_formula(v, DEFAULT_HITTER_SCORING)
    # Hand-compute with the verified league scoring (TB/BB/R/RBI/SB/HBP/-K):
    # TB = 302
    expected = (
        (302 * 1)                  # total bases
        + (60 * 1) + (6 * 1)       # bb, hbp
        + (95 * 1) + (92 * 1)      # r, rbi
        + (12 * 1)                 # sb
        + (120 * -1)               # so
    ) / 150
    assert approx(fpts, expected), (fpts, expected)
    # Hit types live in the vector but are NOT scored — TB carries that value,
    # so scoring them too would double count. CS isn't scored in this league.
    for k in ("1b", "2b", "3b", "hr", "h", "cs"):
        assert k not in DEFAULT_HITTER_SCORING
    print(f"✓ apply_hitter_formula: {fpts:.3f} pts/game matches hand calc (TB-based)")


def test_scoring_does_not_double_count_with_h():
    # A league that scores total hits + extra for 2b/3b/hr.
    scoring = {"h": 1, "2b": 1, "3b": 2, "hr": 3, "r": 1, "rbi": 1}
    v = {"h": 2.0, "2b": 1.0, "3b": 0.0, "hr": 1.0, "r": 1.0, "rbi": 1.0}
    # 2*1 + 1*1 + 0 + 1*3 + 1 + 1 = 8
    assert approx(apply_hitter_formula(v, scoring), 8.0)
    print("✓ apply_hitter_formula: 'h'-based scoring style works on same vector")


def test_pa_blend_weight_ramp():
    assert pa_blend_weight(0) == 0.0
    assert approx(pa_blend_weight(100), 0.5)   # 100 / 200
    assert pa_blend_weight(200) == 1.0
    assert pa_blend_weight(500) == 1.0         # capped
    print("✓ pa_blend_weight: linear ramp capped at 1.0")


def test_blend_vectors_weighting_and_fallback():
    a = {k: 2.0 for k in ("pa", "ab", "h", "1b", "2b", "3b", "hr",
                          "r", "rbi", "bb", "hbp", "sb", "cs", "so")}
    b = {k: 4.0 for k in a}
    blended = blend_vectors(a, b, 0.25)   # 0.25*2 + 0.75*4 = 3.5
    assert approx(blended["hr"], 3.5)
    # fallback when one side missing
    assert blend_vectors(None, b, 0.25)["hr"] == 4.0
    assert blend_vectors(a, None, 0.25)["hr"] == 2.0
    print("✓ blend_vectors: weighting + None fallback")


def test_apply_factors_identity_and_scaling():
    v = {"hr": 1.0, "h": 2.0, "r": 1.0}
    assert apply_factors(v) == v                       # identity default
    scaled = apply_factors(v, per_stat={"hr": 1.5}, scalar=2.0)
    assert approx(scaled["hr"], 1.0 * 1.5 * 2.0)       # 3.0
    assert approx(scaled["h"], 2.0 * 1.0 * 2.0)        # 4.0
    print("✓ apply_factors: identity default + per-stat × scalar")


def test_parse_scoring_from_msettings():
    msettings = {"settings": {"scoringSettings": {"scoringItems": [
        {"statId": 5, "points": 4},      # HR
        {"statId": 17, "points": 1},     # R
        {"statId": 27, "points": -0.5},  # SO
        {"statId": 999, "points": 7},    # unknown → skipped
        {"statId": 34, "pointsOverrides": {"16": 2}},  # mapped via overrides? id 34 unknown
    ]}}}
    scoring = parse_hitter_scoring(msettings)
    assert scoring["hr"] == 4 and scoring["r"] == 1 and scoring["so"] == -0.5
    assert 999 not in scoring.values()
    print("✓ parse_hitter_scoring: maps known statIds, skips unknown")


def test_parse_scoring_fallback():
    assert parse_hitter_scoring({}) == DEFAULT_HITTER_SCORING
    assert parse_hitter_scoring({"settings": {}}) == DEFAULT_HITTER_SCORING
    print("✓ parse_hitter_scoring: falls back to default when empty")


def test_end_to_end_projection():
    hitters = [{
        "name": "Test Slugger", "team": "BAL",
        "gameDates": ["2026-06-01", "2026-06-02", "2026-06-03",
                      "2026-06-05", "2026-06-06", "2026-06-07"],  # 6 games
    }]
    stat_current = {"test slugger": SEASON_2026}
    proj, details = get_projected_hitter_fpts(
        hitters, scoring=DEFAULT_HITTER_SCORING, stat_current=stat_current,
    )
    p = proj["Test Slugger"]
    per_game = apply_hitter_formula(per_game_vector(SEASON_2026, 150), DEFAULT_HITTER_SCORING)
    assert p["games"] == 6
    assert approx(p["projPerGame"], round(per_game, 2))
    assert approx(p["projFpts"], round(per_game * 6, 1))
    assert p["blendWeight"] == 1.0   # 650 PA >> threshold
    print(f"✓ get_projected_hitter_fpts: {p['projPerGame']}/g × 6 = {p['projFpts']} (blend {p['blendWeight']})")


def test_year_blend_in_projection():
    # Rookie-ish current year (few PA) leans on previous season.
    cur = dict(SEASON_2026); cur.update(gamesPlayed=20, plateAppearances=80, homeRuns=2)
    prev = SEASON_2026
    hitters = [{"name": "Sophomore", "team": "NYM", "gameDates": ["2026-06-01"]}]
    proj, _ = get_projected_hitter_fpts(
        hitters, stat_current={"sophomore": cur}, stat_previous={"sophomore": prev},
    )
    # 80 PA → weight 0.4 toward current year
    assert approx(proj["Sophomore"]["blendWeight"], 0.4)
    print(f"✓ year blend: 80 PA → {proj['Sophomore']['blendWeight']} current-year weight")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} tests passed.")
