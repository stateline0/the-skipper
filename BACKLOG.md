# The Skipper — Backlog

Last updated: June 13, 2026 (session 44 — shipped end-to-end: IL grades + injury pills on every page (roster + FA, pitchers + batters), Phase B Est-Return-aware projections, and the League rosters viewer / trade-engine Phase 1. Also fixed `/api/injury_probe` (the probe that validated the injuries feed). P1 #2 and P1 #3 both closed. New infra gotcha recorded: Vercel doesn't bundle sibling modules for *newly-added* Python endpoint files — route new endpoints through an existing one. See sections below.)

---

## 🎯 Prioritization (June 10, 2026 review)

**Principle:** *Indispensable = trusted projections + a complete daily decision loop.* Trust comes from accuracy transparency (the locking/MAE infrastructure is the moat — keep investing in it). Completeness means the user never needs another tab open to decide. Strategy frame: personal tool first; productization (multi-user, other platforms) is an explicit later horizon.

Each tier references the detailed items below — no items were removed, only ranked.

### P0 — Now: trust & correctness
1. **Verify all-MLB cron** (→ *Next session priorities*) — **mostly closed June 13.** Session 40 found the whole cron module had been crashing at import since PR #154 (June 7). The fix is shipped and the **June 13 17:00-UTC run is verified clean** (`mlb`/`espn`/`hitter` all ok, 595 locked, 1271 actuals — confirmed via the new `scripts/check_cron.py` read-only diagnostic). One sub-item remains: observing a live proj2h `baseline → upgraded` transition (needs a post-first-pitch Hitters-page load, then re-run the script) — see *Next session priorities*.
2. ~~Urgent code fixes from the June 10 review~~ — shipped session 39 (Claude model retirement, env-var validation, silent-failure logging; full list in REVIEW.md).
3. ~~**Pitcher-actuals unification**~~ — **shipped session 40.** Accuracy roster scope now reads game-log `actual-all:` actuals (validated against ESPN's applied total, ESPN-box fallback for pre-cron dates); FA Act FPTS gaps filled from game logs on the My Team/FA payload.
4. ~~**Exact accuracy counterfactuals**~~ — **shipped session 40.** Locks store `baseNoWl` + `recentRatio`; accuracy rebuilds counterfactuals from the real per-start formula (incl. W/L + weather) for new locks, legacy approximation for old ones.
5. ~~**v1 lock stores Proj/G, not per-start proj**~~ — **shipped session 42** (see *Model Improvements*).
6. ~~**Starts-only per-start pitcher rates**~~ — **shipped session 40.** `per_start_avgs_from_logs()` (gs≥1 rows) in `projection.py` + `cron.py`; capped season-total path remains the fallback (no logs / prior year).

### P1 — Next: decision automation (the indispensability layer)
1. ~~**Hitters in AI recommendations**~~ — **shipped session 43.** `build_prompt` gains roster-hitter + FA-batter sections and hitter-aware TASK instructions (same four output sections, so the frontend parser is untouched); the recommendations page fetches `/api/hitters` directly and selects **top 10 FA pitchers by proj FPTS** (replacing the checked-set handoff) and **top 4 FA batters per position** (Conner's spec, June 13). Also fixed in passing: the page was still reading PR #127's dead sessionStorage keys, so its data handoff had been silently broken since session 30 — now reads the current localStorage shapes. Unblocks the trade evaluator/finder and planner MVP. **Verify in prod:** load Recommendations (no amber pitcher-only banner) and generate once.
2. ~~**IL-aware FA projections + Est Return**~~ — **shipped session 44 (Phases A + B).** Real typed IL grades (IL10/IL15/IL60/DTD) on every page incl. rostered players, sourced from the public ESPN injuries feed (joined by ESPN id); est-return-aware projections (IL hitters zero only through the return date, then resume); tap-to-open IL tooltip with est. return + injury detail. (→ *IL-aware projections & Est Return* section for the phase detail.)
3. ~~**League rosters viewer — trade engine Phase 1**~~ — **shipped session 44.** Every team's roster with the same Stats payloads + a season-long ROS column, served via `/api/hitters?view=league`. Unblocks the Phase 2 evaluator. (→ *Trade engine* section.)
4. **Trade evaluator + finder — trade engine Phases 2–3** (→ *Trade engine* section; spec approved June 12 with amendments). Sequenced after #1.
5. **Weekly planner / decision automation MVP** (→ section below) — the roadmap centerpiece.
6. **Hitter nudge engine** (→ *Hitters* section) — watchlist/alert, buildable today on FA actuals.
7. **Morning lineup check / scratch alerts** (new — see *Promoted proposals*) — closes the daily loop.
8. **Live freshness for hitter projections** (→ *Hitters* section).
9. ~~**Unify roster-page vs cron proj2h scoring**~~ — **shipped session 42** (→ *Hitters* follow-up; all-MLB matchup factors remain a future consideration).

### P2 — Model depth
- Phases 8–10 (BvP, lineup-spot volume, per-stat park + wind-for-HR) — in MAE-impact order, lineup-spot volume likely first.
- **New pitcher factors** (→ *Model Improvements*): Tier A expected-IP modeling, opponent K% by handedness, handedness-split opponent wOBA; Tier B team defense (OAA/DER), Vegas game total as a calibration anchor. Each gated on out-of-sample MAE improvement via the counterfactual harness.
- Role-aware RP appearances + leverage-based saves (→ *Model Improvements*).
- Pitcher platoon (Layer 5), rest & workload (Layer 6), wind direction (Phase 3 weather).
- Projection confidence bands (new — see *Promoted proposals*).
- Prior-year Savant fallback; SSPD roster bug. (~~Dropped-player projDetails merge~~ — shipped session 42.)

### P3 — Polish & ops
- Title-case/accents preservation, ProjectionTooltip wOBA split, dashboard at-a-glance, pro-team-map caching.
- Ops hardening from REVIEW.md: retry/backoff on external APIs, structured logging, re-enable TS build errors, park-factor refresh process, ESPN cookie health check (new).

### Horizon — productization (deferred by strategy)
Multi-user / multi-league, category-league support (the stat-vector hitter model already enables it), Yahoo/other platforms, mobile app, paid probables source. Revisit when P0–P1 are done and the tool is winning leagues.

### Infra notes (learned the hard way)
- **Vercel doesn't bundle sibling modules for *newly-added* Python endpoint
  files.** A brand-new `api/foo.py` that does `from kv import …` /
  `from fetcher import …` crashes at cold start with `ModuleNotFoundError`
  (the function bundle ships without the siblings), even though existing
  endpoints import the same modules fine. Confirmed session 44 on both
  `api/injury_probe.py` and `api/league.py`; deferring imports, leaf-only
  imports, `vercel.json` `includeFiles`, and a no-cache redeploy all FAILED.
  **Workaround that works:** add the logic to an *existing* endpoint module
  (whose bundle already resolves) behind a query-param branch — e.g. the
  League viewer ships as `/api/hitters?view=league`. Do this for any new
  backend endpoint until the root cause (Vercel build config / tracer) is
  understood. `api/injury_probe.py`'s kona path is still broken for the same
  reason (its `injuries_feed` path works because it needs no siblings).

---

## 🔜 Next session priorities

### ⏳ Verify next — all-MLB cron (now includes the session-40 import fix)
- [ ] **Verify the session-42 proj2h baseline→factor-adjusted upgrade.** The noon cron writes the all-MLB BASELINE lock (`model.allMlb`) first; the Hitters page should UPGRADE it to the factor-adjusted value on the first load after a game starts. **Partially confirmed June 13** via `scripts/check_cron.py`: the cron's baseline-write path works (595 baseline locks on `06-13`) and the page's factor-adjusted-lock path works (the `06-07`→`06-12` `native` locks — page-only locks written while the cron was dead). **Still to observe: an actual `baseline → upgraded` transition** — `06-13` showed `upgraded=0` only because no Hitters-page load had happened post-first-pitch yet. To close: after an MLB game starts today, load the Hitters page, then `python scripts/check_cron.py --days 1` and confirm `upgraded > 0` on the current date. (The diagnostic buckets every `proj2h:` lock as baseline/upgraded/native and only flags a *past*-date baseline as a problem — today's pre-game baselines are expected.) Equivalent manual check: read a roster hitter's `proj2h:{2026}:{period}:{slug}:{date}` key — it should carry `model.upgradedFrom: "allMlb"` plus a non-empty `factors` stack.
- [x] ~~**Confirm the daily cron runs clean on the next scheduled tick** (17:00 UTC).~~ — **VERIFIED June 13, 2026** via `scripts/check_cron.py` (new read-only Upstash diagnostic). The `cache:cron-summary:2026-06-13` blob is clean across all three passes: `mlb.ok`, `espn.ok`, **and `hitter.ok: true`** with `hittersToday: 595`, `locked: 595`, `actualsStored: 1271` across 5 dates — the first healthy hitter run since June 7, confirming the session-40 import fix in production. The `06-08`→`06-12` gap shows **no `cache:cron-summary` writes at all** (the import-crash signature: the handler dies before it can write the summary) and `06-07` has `hitter: null` (the day PR #154 landed) — exactly as predicted. Actuals backfilled (the 1271). **Original session-40 context:** PR #154 imported `fetch_game_logs_hitting` from `fetcher` but the function lives in `mlb` — `api/cron.py` raised `ImportError` at module load from June 7, so every run failed entirely (py_compile can't catch ImportError, which is why "logic + compile" validation missed it); fixed session 40 by moving the import to `mlb`. The missed June 7–12 projection locks are unrecoverable by design (locking is the point).

### Flagged during review (next up)
- [x] ~~**W/L impact sign should track win prob, not the pitcher's record.**~~ — **fixed session 33 (PR #146).** Both `w_contrib`/`l_contrib` (live) and `w_adj`/`l_adj` (lock) now scale by the total decision rate `(raw_w + raw_l)` split by win prob instead of the separate historical W/L rates, so net = `decision_rate × STARTER_WIN_SHARE × 5 × (2·win_prob − 1)` → **positive when favored, 0 at a coin flip, negative as an underdog**, magnitude still pitcher-specific. Verified the backlog's 56%-win-prob case flips from −0.1 to +0.19. The net decomposes exactly into the existing `w×5 + l×−5` shape, so the locked breakdown's `stats.w`/`stats.l` (read by `accuracy.py`) keep their shape and become a cleaner expected-W/L estimate; the tooltip's `wlContrib` sign is now correct. Added a `MaeTimelineChart` milestone marker (2026-06-07); **forward-only** for locked values.
- [x] ~~**ESPN Forecaster scraper broken since ~mid-May**~~ — **fixed session 32 (PR #145).** External break, as suspected: ESPN now fronts the Forecaster article with **AWS WAF (CloudFront)**, which serves a ~2KB HTTP-202 challenge stub (`window.awsWafCookieDomainList` / `window.gokuProps`, no table) to **Chrome-fingerprinted** requests. The `/api/forecaster_probe` strategy matrix (rewritten this session to test multiple UAs/cookie-warmup in one request) showed legacy Chrome/123, a modern Chrome+client-hints fingerprint, and a cookie-warmed session all get the stub, while a **plain Safari UA and Googlebot UA both pass straight through** to the real 156KB article — so it's a UA-based rule, not a JS challenge, and a header swap is the whole fix. `fetch_forecaster()` now sends Safari (primary) → Googlebot (fallback) and returns a loud, specific error (`all UAs blocked — safari: HTTP 202 … [AWS WAF stub]`) on failure. The missed mid-May→Jun weeks remain **unrecoverable** (rolling 10-day window); data resumes going forward. **Note:** the cron already writes the full `espn` result (counters *or* error) into `cache:cron-summary:{date}`, so the "add ESPN-lock counters to cron-summary" sub-item was already covered — a future WAF change will show up there verbatim.

### IL-aware projections & Est Return — ✅ SHIPPED (sessions 43–44)
**Done.** Phase A (session 43, PR #170: typed IL pill + zero-while-IL for FAs)
and Phase B (session 44, PRs #171–#174: pills rendered on every page incl.
rostered players, real grades + est. return from the public ESPN injuries feed
joined by ESPN id, return-date-aware projection resumption, tap-to-open IL
tooltip). Roster grades — the original blocker (mRoster `injuryStatus` is empty
for rostered players) — are solved because the public injuries feed needs no
auth and covers all of MLB. Phase history retained below for reference:

- [x] **Phase A1 — IL pill (with type) on the Name subline.** ✅ Shipped (rendered on every page — roster + FA, pitchers + batters; roster grades from the injuries feed, not kona). *Buildable
  today for FAs, no new external calls.* The kona `player.injuryStatus`
  field works for free agents (KNOWLEDGE.md, 10/10): `FIFTEEN_DAY_DL`,
  `SIXTY_DAY_DL`, `DAY_TO_DAY`, `SUSPENSION`. `api/espn.py`'s FA pitcher
  loop already maps these to `IL15`/`IL60`/`DTD`/`SUSP` (`inj_label_map`)
  and ships `injuryStatus` — the pill just isn't rendered. FA hitters:
  `_fetch_fa_hitters` in `api/hitters.py` parses the same flat `player`
  dict but doesn't capture `injuryStatus` — one field to add + a pill in
  `HitterTables` (reuse the existing compact position-pill pattern).
  Add `TEN_DAY_DL → IL10` to the map (not yet observed but the obvious MLB
  value). **Rostered players:** mRoster `injuryStatus` is empty for all
  rostered players (KNOWLEDGE.md) — only the `player.injured` boolean, so
  rostered pills say "IL" without type for now. Worth one log line in the
  existing `kona_player_info` ownership-parse loop (PR #117) to check
  whether that view carries granular status for rostered players — zero new
  HTTP calls either way.
- [x] **Phase A2 — zero daily projections while on IL.** ✅ Shipped, then
  superseded by Phase B's return-date awareness. Hitters: zero the per-day `proj` in `_build_days` (shared by
  roster + FA paths — one change point) whenever status is IL10/IL15/IL60;
  status clears when ESPN activates the player and data refreshes daily, so
  projections resume automatically. **DTD keeps projections** (day-to-day
  players usually play; consistent with the trade-engine spec's "DTD small
  haircut"). Pitchers: IL FAs rarely have probable starts so per-start proj
  is mostly already 0; apply the same zero-while-IL rule to `projFpts`.
  Knock-on win: the AI payload's top-10/top-4 selection self-corrects with
  no `analyze.py` change. Accuracy impact: nil — an IL hitter's locked proj
  becomes 0 instead of stale-nonzero, and DNP games were already excluded
  from MAE (unmatched). Forward-only.
- [x] **Phase B — ESPN "Est Return" date + zero-until-return.** ✅ Shipped
  session 44 (PRs #173–#174). **Source = candidate (2), the public ESPN
  injuries feed** (`site.api.espn.com/.../mlb/injuries`) — `/api/injury_probe`
  confirmed it carries `details.returnDate` AND the typed grade for every MLB
  player, no auth, so it works for rostered players too. New `api/injuries.py`
  fetches/caches it (`cache:injuries-feed:v1`, 6h), joined to roster/FA by ESPN
  id. Projections zero only days before the return date, then resume; the date
  shows in the IL tooltip. Still TODO: feed the real dates into **trade engine
  Phase 2's IL discounting** (replacing the IL15 ≈ −2.5wk / IL60 ≈ −9wk
  assumptions). Original probe plan retained below:
  Probe candidates, in order: (1) the kona `player` object itself (cheapest
  if present — same call we already make); (2) ESPN's public injuries feed
  `site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries` (the NFL
  variant carries `details.returnDate`; moderate confidence MLB's does
  too); (3) the athlete card/overview service
  (`site.web.api.espn.com/.../athletes/{id}/overview`). ESPN fantasy player
  IDs are MLB athlete IDs (the Forecaster scraper already extracts them),
  so the join is free. **Couldn't probe from the session-43 dev container
  (network egress allowlist)** — follow the `/api/forecaster_probe`
  pattern: ship a tiny `/api/injury_probe` diagnostic, inspect raw shapes
  for 2–3 known-IL players in prod, then wire. Cache under
  `cache:injuries:{date}` (24h TTL). Once landed: refine Phase A2's blanket
  zero to **zero until Est Return** (a returning IL15 player's last week of
  the window projects normally), show the date next to the pill, and feed
  it to **trade engine Phase 2's IL discounting** (replacing the IL15 ≈
  −2.5wk / IL60 ≈ −9wk assumptions with real dates).

Sizing: Phase A ≈ half a session (A1+A2 together — same files, one verify
cycle); Phase B ≈ half–1 session including the probe round-trip. Suggested
sequencing: Phase A next session (it's the trust/correctness fix), Phase B
with or just before trade engine Phase 2.

### Stats view tab — follow-ups
✅ **All six shipped in session 30** (PRs #121–#123) — Whiff% plumbing, Cease Brl% (self-resolved), Free Agents Stats tab, Luck indicator (rendered as a colored trend line), full-season Pace column, and the relievers Stats tab. Also added a Form sparkline, mobile tap popovers, and the FPTS/G → Proj/G rename. See **Completed (session 30)** below for details.

### Weekly planner / decision automation MVP
The big-picture feature still on the roadmap but not next-up:
- [ ] AI-powered weekly optimization: recommend add/drop sequence and start/sit decisions
- [ ] Teach Anthropic API about ESPN transaction rules (daily locks, waiver priority)
- [ ] Hybrid mode: AI suggests plan, user picks A/B for key decisions, AI outputs full sequence
- [ ] Uses projection model data as input

### Trade engine (3 phases — spec reviewed & approved by Conner, June 12, 2026)
Supersedes the unranked "Trade analyzer" idea. Everything stays **read-only**
(proposals are advisory; trades get clicked on ESPN). Key feasibility fact: the
`mRoster`+`mTeam` call `get_league_data` already makes returns **all 12 teams'
rosters** — opposing rosters are downloaded today and discarded.

- [x] **Phase 1 — League rosters viewer** — ✅ **shipped session 44** (PR #175).
  All 12 teams' rosters with the same Stats payloads (reusing the existing
  builders) + a season-long **ROS FPTS** column (SP: Proj/G × `32 − GS` Pace
  horizon; RP: appearance-prorated; hitters: projPerGame × `162 − games played`
  from cached `team_win_data`). Team meta (name/owner/record) from `mTeam`;
  cache `cache:league-roster:{year}` 30-min; behind auth; no opponent schedule
  grid. Frontend: `pages/league.tsx` ("League" in sidebar) — team selector → two
  `StatsTable`/`HitterStatsTable` sections. **Served as `/api/hitters?view=league`,
  NOT a standalone `api/league.py`** — see the Vercel-bundling note in *Infra
  notes* below. Follow-ups deferred: preselect the user's own team in the
  selector (needs an `/api/config` fetch).
- [~] **Phase 2 — Trade evaluator — v1 shipped (perceived-value arbitrage).**
  Served as **`/api/hitters?view=trade`** (GET for testing + POST `{give, get,
  withTeamId, rationale}`), NOT a standalone `api/trade.py` (Vercel-bundling
  note). Two axes per player: **model ROS** (`seasonBaseRos` = de-lucked rate ×
  remaining horizon, no 60/40 blend) and **perceived value** (`PVI`,
  FPTS-equivalent). **PVI = time-varying blend** (`p = season progress`,
  draft→production migration) of **league draft slot** (via an OLS log-log
  draft-value curve fit from `mDraftDetail` picks × full-season pace),
  **in-season production**, **ADP** (best-effort), with a light positional-
  scarcity tilt. Deterministic verdict (steal / win / lopsided / avoid /
  marginal) with a **5% acceptance cushion** biasing perceived balance to the
  counterparty (draft endowment effect); optional Claude pitch (analyze.py
  pattern). Per-player `valueRatio` (ROS FPTS per perceived point) flags buy/
  sell. Unit tests in `api/test_trade_engine.py` (8/8). **The FantasySP scrape
  idea is dead** (Cloudflare-walled — confirmed via `scripts/fsp_probe.py`); our
  own draft-anchored perceived-value model replaces it and matches the league's
  points scoring. **v1.1 follow-ups:** FA replacement-level netting; numeric IL
  haircut (injured players flagged, not yet discounted); starts-cap awareness.
  **v2:** preseason proj FPTS (FanGraphs CSV → reach/fall anchor); League-page
  checkbox → "Evaluate trade" drawer (frontend). **Verify in prod:** POST a
  give/get to `/api/hitters?view=trade` and confirm `draftCurveFit: true`.
  - *Original spec (remaining items fold into v1.1/v2 above):*
  - **Trade value = de-lucked ROS minus per-position replacement.** The skill
    base is already Savant-de-lucked (xBA/xERA for pitchers, xwOBA for
    hitters); for the ROS horizon, use the **season-skill base WITHOUT the
    60/40 recent-form blend** (recent form re-injects short-term luck — right
    for start/sit, wrong for a rest-of-season valuation; show it as context
    instead). Replacement level computed **per position from the live FA
    pool** (best available C vs best available OF, …) so positional scarcity
    falls out naturally with no hand-tuned weights — and 2-for-1
    consolidation prices correctly (the vacated slot refills from waivers).
  - **Luck-arbitrage score per player** (Conner's buy-low/sell-high
    requirement, explicit): *perceived value* = ROS from actual surface stats
    (real ERA/wOBA — what the other manager sees) vs *model value* =
    de-lucked ROS. Positive gap = unlucky/buy-low target; negative =
    overperforming/sell-high candidate. Surfaced per player in the evaluator.
  - **Starts-cap awareness:** projected weekly starts before/after vs the
    12-start cap; surplus starts discounted (the league's real scarcity axis).
  - **IL discounting** (not naive — v1 simplification removed per Conner):
    DTD small haircut, IL15 ≈ −2.5 weeks, IL60 ≈ −9 weeks of remaining games,
    assumptions displayed on the player.
  - Output: per-side raw ROS / replacement-adjusted net / weekly-starts delta
    / slot-group deltas, deterministic verdict, optional Claude rationale
    (analyze.py pattern, both rosters in prompt, pitchers + batters).
  - Frontend: row checkboxes on the League page → "Evaluate trade" drawer.
- [ ] **Phase 3 — Trade finder** (~1–2 sessions after Phase 2).
  `api/trade.py?mode=find`: per-team needs model (ROS Proj/G by slot group vs
  league median → surplus/need lists); deterministic scan of 1-for-1 and
  2-for-1 swaps kept only where **both sides net positive** after replacement
  adjustment (the acceptance filter), **optimizing the luck-arbitrage term**
  (send negative-gap players, receive positive-gap ones — which also boosts
  acceptance plausibility, since outgoing players' surface stats flatter
  them). ~50 candidates → Claude ranks top 5–10 with talking points for the
  pitch. Every proposal surfaces its underlying numbers — a bad suggestion
  must be visibly bad, not oracle-flavored. Frontend: "Trade Finder" tab on
  the League page; cards expand into the Phase 2 evaluator view.

### Model Improvements
- [ ] **Reliever projection is heuristic** (session 38, PR #157). RP weeks = FPTS/appearance × a flat **3 appearances/week** (`RP_APPEARANCES_PER_WEEK`), with small-sample regression toward a league-average reliever (`RP_BASELINE_FPTS_PER_APP`, `RP_FULL_SAMPLE`) and a 0 floor — this tamed the old `×4` blow-ups (e.g. −17) and inflated highs (~20). Possible refinements: role-aware appearance counts (closers/setup pitch more than mop-up), and projecting saves from leverage/role rather than the season save rate. Also note the year-blend leans fully on the prior season when current-year IP is tiny (why a cratered-2026 closer can still project high).
- [ ] Weather impact — Phase 3: wind direction model (add `PARK_OUTFIELD_BEARING` per park, compute out-to-outfield wind component, combine with temp into single weather multiplier)
- [ ] ProjectionTooltip: split opponent wOBA display into season + last-14-day components (currently shows only the blended factor; show `seasonFactor`, `recentFactor`, and `blendedFactor` with weights). Note: the tooltip was otherwise rebuilt to reconcile in session 30 (PR #125).
- [ ] **New pitcher factors — from the June 19, 2026 factor/variance review.** Five candidate layers ranked by leverage. **Process discipline:** add each as a bounded/dampened multiplier (the park/weather pattern via `env_to_pitcher_mult`) and **validate it through the accuracy counterfactual harness — out-of-sample MAE must actually improve — before trusting it.** Every new factor adds estimation noise + overfitting surface against the irreducible per-start luck floor (W/L outcome, BABIP, sequencing), so the bar is "earns its place on held-out data," not "is plausible baseball." The high-leverage three are *missing signal* (the K term, outing length, platoon), not refinements of layers we already have (xERA de-luck, opponent wOBA, park, weather, Vegas win prob).
  - [ ] **Tier A — Expected-IP modeling** *(highest leverage)*. IP is weighted ×3 and is the single biggest FPTS driver — a 5-IP vs 7-IP start is ~6 pts before the K/ER that ride along. The model currently uses a flat historical per-start IP average (`projection.per_start_avgs_from_logs`). Make expected IP matchup-/role-aware: tougher opponent → earlier hook, recent pitch-count / times-through-the-order trend, opener/bulk-role detection. Highest leverage *and* highest noise (early hooks, blowups) — handle with care and validate hard.
  - [ ] **Tier A — Opponent K% by handedness.** wOBA is essentially an H/ER proxy and is blind to strikeouts, which are a separate FPTS term (×1); a lineup can be high-wOBA *and* high-K (three-true-outcomes offenses). Add opponent team K% split vs LHP/RHP (MLB Stats API / Savant) as a K-specific adjustment to the projected SO line. Clean, reliably available pre-game.
  - [ ] **Tier A — Handedness-split opponent wOBA.** Use opponent wOBA *vs the pitcher's hand* instead of the blended team wOBA (a LHP facing a righty-stacked lineup is mis-served today). Refinement of the existing `mlb._compute_team_woba_factors` fetch — split by batter hand and select on the starter's throwing hand. **Supersedes _Backlog → Projection model — Layer 5: Platoon splits_** and pairs with the _ProjectionTooltip wOBA split_ item above (the tooltip should then show the hand-specific factor).
  - [ ] **Tier B — Team defense behind the pitcher** *(Conner's suggestion)*. Not redundant with the xERA de-luck (`projection.apply_savant_adjustments`): xERA assumes *league-average* defense, so a team-fielding factor (Savant team **OAA**, or DER) nudges the projection back toward the actual glovework supporting the start, affecting ER and BABIP/H. Honest magnitude: full-season team OAA spans ≈ ±40 runs → only ~±0.3–0.6 FPTS per start at the extremes. Real but low-leverage → a dampened factor like park, not a headline; cheap if Savant team OAA is fetchable.
  - [ ] **Tier B — Vegas game total / opponent implied runs.** The over/under is a market-aggregated run-environment estimate, and the odds feed is already parsed for moneylines (Vegas win prob, `mlb.py`). Best used as a **cross-check / calibration anchor** on the stacked factors — *not* an independent multiplier, since it bundles park + weather + opponent offense + pitching and would double-count the existing layers.
- [x] ~~**Accuracy `factorAnalysis` reconstruction is approximate**~~ — **fixed session 40.** Locks now store `model.baseNoWl` (the recent-form-scaled per-start skill base) + `model.recentRatio`; `api/accuracy.py` rebuilds counterfactuals from the exact formula `(baseNoWl + (w−l)×5) × woba × park × weather` for new locks (incl. a new weather counterfactual + Weather factor card), keeping the legacy `adjustedBase` approximation for pre-June-10 locks. Per-start `exactCounterfactuals` + `factorAnalysis.exactStarts` expose the mix.
- [x] ~~**Cron W/L contributions still use the pre-PR-#146 formula**~~ — **fixed session 42.** `cron.py` now uses the same decision-rate-split-by-win-prob form as `projection.py` (`decision_rate = w + l`, split by win prob × `STARTER_WIN_SHARE`), so with the cron's default 0.5 win prob the net W/L is exactly 0 instead of reflecting the pitcher's record. `stats.w`/`stats.l` in the `proj2all:` breakdown mirror the same form; `fpts = baseNoWl + (w−l)×5` still decomposes exactly. Forward-only.
- [x] ~~**v1 locked value stores Proj/G, not the per-start projection.**~~ — **fixed session 42.** `projection.py`'s v1 `set_locked_projection` call moved below the per-start computation and now stores the factor-adjusted `start_proj` (same value as the v2 lock's `fpts`), so locked past cells and live future cells render on the same basis. Forward-only — existing v1 locks keep their Proj/G value (NX).

### Pre-acquisition follow-ups (deferred from session 26 PR #111)
PR #111 fixed the user-visible aggregates for mid-week pickups but deliberately punted on three downstream concerns. Two remain; the third closed as PR #115 in session 27. None are user-blocking; all forward-only.
- [ ] **`projection.py` lock-skip for pre-acquisition starts.** PR #111 tags `preAcquisition` post-hoc in `espn.py` after `get_projected_fpts` has already run, so per-start `proj2:` locks may be written for starts the user never benefited from. Forward-fix requires moving the actuals fetch above projection (so tagging precedes locking) — a substantial reorder of `get_league_data`. Practical impact today is low because most pre-acq starts already have `proj2:` locks from the cron all-MLB path or from prior owners' roster fetches.
- [ ] **Accuracy dashboard "My Roster" scope filter for pre-acq starts.** Even after the lock-skip above, legacy `proj2:` locks from before pre-acq tagging existed will still match the current owner's roster slug and surface in the accuracy view. Symmetric fix to PR #104's FA-leak filter: drop matched starts where the matched date falls outside the rostered window (use the same `my_team_by_date` index already in scope).
- [x] ~~**Dropped player post-drop `actualFpts` pruning.**~~ (`info["player_fpts"]` now intersected with `days_on_team_set` in the dropped-player branch of `api/espn.py`. Symmetric closure of the rostered-window invariant — see KNOWLEDGE.md. **Note:** session 27's PR #115 was written but never merged — the fix was absent from `main` until re-landed in session 29 after a project review caught the discrepancy. The original PR #115 has since been closed as superseded.)

### Dropped-player per-start projection display
- [x] ~~Schedule grid reads `projectionDetails?.[pitcher.name]` from a global map populated only from `roster_sps`; dropped players' details never reach it~~ — **fixed session 42** via option (1): `api/espn.py` merges `dropped_proj_details` into `proj_details_roster` before returning (dropped names are disjoint from the roster by construction, so no clobbering). The per-player `projDetails` field stays on the dropped-player object for backward compatibility. Frontend untouched.

### Display polish (low priority)
- [ ] **Advanced (Savant) stats are current-season only** (session 38). xERA/xwOBA/Brl%/Whiff% render an em-dash for pitchers with no current-year batted-ball footprint (small sample / hasn't pitched), even when the projection leans on last season — e.g. Estévez (great 2025, tiny ugly 2026). Optional: fall back to prior-year Savant values (labelled by year) so the columns populate for these arms. Deferred to avoid mixing a 2025 Savant line with a 2026 ERA in the same row; the Proj FPTS tooltip now surfaces the season-basis instead.
- [ ] Title-case edge cases on accuracy page: store original `fullName` (case + accents preserved) in `mlb_stats_current` and `actual-all:` entries so the dashboard renders "Lance McCullers Jr." (not "Mccullers"), "Eury Pérez" (not "Perez"), "JT Brubaker" (not "Jt"). PR #109's `\b\w` regex client-side `titleCase()` is the v1 fallback; proper fix is server-side preservation of original case + accents

---

## 📋 Backlog (lower priority)

### Projection model — Layer 5: Platoon splits
> **Folded into _Model Improvements → New pitcher factors_ (Tier A: handedness-split opponent wOBA, June 19, 2026).** Track there.
- [ ] Pitcher performance vs left-heavy vs right-heavy lineups
- [ ] Team handedness composition from MLB Stats API

### Projection model — Layer 6: Rest & workload
- [ ] Days since last start (4 vs 5+ day rest performance)
- [ ] Season pitch count trajectory (fatigue effects)
- [ ] Most meaningful mid-to-late season

### Prospect monitor
- [ ] Track top MLB prospects approaching call-up
- [ ] MLB Stats API minor league rosters + prospect rankings
- [ ] Alert when top-50 prospect + 40-man roster + corresponding MLB spot opening
- [ ] 12-24 hour edge over league competitors

### Hitters (session 31 — PRs #132–#143)
- [x] ~~Full matchup-aware hitter projection model + live Hitters page~~ — see
  `HITTERS_MODEL.md` (Phases 0–7 shipped: baseline, Savant de-luck, recent form,
  platoon, opp-SP quality, park, weather; per-day popover; actual/live tracking
  for roster + FA).
- [x] ~~**Hitter accuracy**~~ — **done (session 34, PRs #147–#150).** lock
  `proj2h:` per game, `kind=hitter` MAE series + Pitchers/Hitters toggle on the
  Accuracy page, DNP games excluded. End to end; data fills in from Hitters-page
  loads.
  - [x] **PR 1 — lock `proj2h:` per game (PR #147).** `kv.py` hitter-lock
    helpers (`set_locked_hitter_projection`, `get_all_locked_hitter_projections`,
    key `proj2h:{season}:{period}:{slug}:{date}`, NX). `hitters.py` freezes each
    roster hitter's per-game projection once the game starts (`status !=
    "scheduled"`), storing fpts + base + factor stack + matchup + model. Locks
    on Hitters-page loads (the warm cron only covers pitchers); pre-fetches the
    period's locks once so reloads don't re-write. No user-visible change.
  - [x] **PR 2 — per-game hitter actuals queryable by date (PR #148).**
    `actuals_with_stats_from_logs()` (game-log-scored, DNP-clean: a log entry =
    played) → `acth:{date}` → `{slug: {fpts, stats}}`, written read-merge-write
    from the Hitters page. `cache:daily.actual_stats` is pitcher-shaped, so
    hitters need this dedicated source.
  - [x] **PR 3 — `kind=hitter` in `/api/accuracy` (PR #149).**
    `get_hitter_accuracy_data()` matches `proj2h:` ↔ `acth:` by slug+date →
    FPTS MAE/max/min/bias/directional; no `acth:` entry = DNP → excluded
    (`unmatchedCount`). No roster filter / factor analysis / ESPN overlay.
    `?kind=` dispatch; pitcher path untouched. Added `name` to the proj2h lock.
  - [x] **PR 4 — Pitchers/Hitters toggle + hitter MAE series (PR #150).**
    `accuracy.tsx` `?kind=` toggle, hitter-shaped table + `HitterBreakdown`
    (base × factors = proj + actual line), Skipper-only hitter MAE timeline
    (`MaeTimelineChart kind="hitter"`). Pitcher path untouched.
  - [x] **All-MLB hitter coverage (PR #154, session 36).** `cron.py`
    `lock_all_mlb_hitter_projections()` locks baseline `proj2h:` + writes `acth:`
    for every hitter whose team plays today (team resolved via `_teamId` →
    `MLB_TEAM_ID_TO_ABBREV`). Bounded to today's hitters; isolated/last in the
    cron. Forward-only; validated by logic+compile, confirm live via
    `cache:cron-summary:{date}.hitter`.
  - [x] ~~**Follow-up:** unify roster-page vs cron proj2h scoring/value~~ —
    **fixed session 42.** The noon cron always beat the at-game-start page
    write to the NX lock, so roster hitters' accuracy locks stayed
    baseline-only. `_lock_started_days` now UPGRADES a cron all-MLB baseline
    lock (`model.allMlb`, no factor stack) to the page's factor-adjusted value
    at game start (`set_locked_hitter_projection(..., overwrite=True)`, the
    only sanctioned overwrite; `model.upgradedFrom: "allMlb"` for
    traceability). A factor-adjusted lock is frozen for good. Still open:
    all-MLB matchup factors in the cron pass + a starts-only follow-up.
- [x] ~~**Starts-only per-start pitcher rates (follow-up to the IP cap, session 35).**~~ — **shipped session 40.** `per_start_avgs_from_logs()` averages the `gs>=1` game-log rows (current year, SP only); the capped season-total path remains the fallback for pitchers without enough logged starts and for the previous season (no prior-year logs fetched). `model.ratesBasis` in the lock + the `[model/logs]` log tag record which path fired. Verified on a synthetic swingman: 25 relief IP + 3×3-IP starts → 6.6 FPTS/start from logs vs 17.0 from the capped season-total path.
- [x] ~~**Pitcher-actuals unification (follow-up to hitter accuracy).**~~ —
  **shipped session 40.** Accuracy roster scope reads game-log `actual-all:`
  actuals first (slug-keyed, collision-proof), validates FPTS against ESPN's
  applied total when both exist (`actualsValidation` counters + per-start
  `actualsSource`), and falls back to ESPN-box only for pre-cron dates. FA
  pitcher Act FPTS gaps on the My Team/FA payload are filled from game logs
  (league formula, doubleheader rows summed, today excluded). The page-display
  Ohtani collision (`cache:daily` `fpts` keyed by full name) is unaddressed but
  cosmetic — accuracy data no longer flows through it. `MaeTimelineChart`
  marker added 2026-06-10.
- [ ] **Phase 8–10** — regressed BvP, PA/lineup-spot volume, per-stat park +
  wind-for-HR.
- [ ] **Hitter nudge engine** — "this waiver guy is outperforming your current
  2B." Now buildable on the hitter model + FA actuals: a watchlist/alert, not a
  full optimizer.
- [ ] **Live freshness** — hitter live totals are ~30-min cached; add a
  fresh-on-gameday refresh like the pitcher page.

### Dropped streamers refinement
- [x] ~~Pull locked projections from KV for dropped players' past starts~~
- [x] ~~Show proj FPTS for the starts they made while rostered~~
- (Both resolved in session 19 PR #81 — dropped players now route through `get_projected_fpts`)

### Additional caching opportunities
- [ ] Pro team map (permanent — barely changes)

### Dashboard at-a-glance component
- [ ] Projected starts vs limit, current period dates, quick links

---

## 🐛 Known bugs

- [x] ~~**`cache:daily` permanently froze mid-game box scores (wrong/missing Act FPTS since ~June 6)**~~ — fixed session 41. `get_actual_fpts` cached any date `< today (UTC)` as complete, and the 15-min warm cron's first tick after UTC midnight (7-8pm ET, games in progress) made the corruption deterministic nightly: Cease locked at +10.0 (real 23), Wrobleski +9.0 (real −1), Detmers' 27-FPTS West Coast start missing entirely. Now a date caches only once `now − 8h` has passed it, entries carry `finalized: true`, and unstamped entries refetch + overwrite — the corrupted June 6–12 window self-heals on the first load/warm tick after deploy. (Jun 6–7 fall outside the current matchup window so their `cache:daily` blobs stay stale, but post-#161 accuracy reads game-log actuals for those dates anyway.) See KNOWLEDGE.md → "New surfaces expose old assumptions" #4.
- [x] ~~**Pitcher added mid-day during a locked period renders empty in My Team**~~ — resolved by session 27 PR #113 (`starts_map` rebuild) + PR #114 (period-based trigger). See KNOWLEDGE.md → "Transaction lag behavior" for the full state.
- [ ] Suspended players (SSPD) not appearing in roster — Reynaldo Lopez added but missing from mRoster response. Likely ESPN uses different eligibleSlots or lineupSlotId for suspended players.
- [x] ~~Free agent actual FPTS only available for players who were rostered at time of start — ESPN API limitation (affects accuracy dashboard too)~~ — fixed session 40: FA Act FPTS gaps filled from MLB game logs in `api/espn.py`; accuracy actuals now game-log-sourced end to end
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue)

---

## ✅ Completed (session 30 — June 6, 2026)
- [x] **Load-time overhaul (PRs #127–#130).** My Team / Free Agents went from a 5–10s rebuild on every visit to instant. (1) **Stale-while-revalidate** (PR #127): `sessionStorage → localStorage` so the cache survives tab closes, plus always-background-refresh — the root cause of the "every load is cold" pain. (2) **Backend parallelization** (PR #128, no output change): concurrent probable sources, parallel weather pre-warm, and `load_cached_data` overlapped with the ESPN roster fetch. (3) **Warm-cache precompute** (PRs #129/#130, Pro plan): `api/warm.py` cron every 15 min precomputes the per-team payload into `cache:leaguedata:{year}:{teamId}:{week}`; `/api/espn` serves the warm blob instantly (`?fresh=1` forces live). Frontend renders it instantly, fires a background `?fresh=1` only on days a rostered pitcher starts, and shows an **"Updated Xm ago"** chip. `vercel.json` gained the cron + `maxDuration` 30→120; `middleware.ts` exempts `/api/warm`.
- [x] **Stats-tab follow-ups — all six shipped.** Whiff% plumbing (PR #121 — `aggregate_whiff_pct()` + `cache:savant-arsenal:{year}` 24hr key; `whiffPct` sourced from the pitch-arsenal endpoint, which actually carries it). Cease Brl% (no code fix — he was temporarily under the statcast leaderboard's min-BBE threshold and now populates; a one-shot miss diagnostic stays in `espn.py`). Free Agents Stats tab (PR #122 — Schedule/Stats toggle mirroring My Team). Luck indicator (PR #123 — a colored trend line from wOBAΔ; direction verified against ERA-vs-xERA: green-up = unlucky / due-to-improve). Full-season Pace column (PR #123 — backend `seasonFptsToDate` from season totals via the league scoring; pace = season-to-date + Proj/G × est. remaining starts, blank for non-starters). Relievers Stats tab (PR #123).
- [x] **Form sparkline (PR #123).** New column plotting actual FPTS over each pitcher's last ~10 starts (backend `_build_fpts_history()` from game logs). Colored by last-5-start average vs the actual season FPTS/start (`seasonFptsToDate ÷ gs`): green hotter / red colder / grey within a ±1.0-FPTS dead-band (`FORM_DEADBAND`).
- [x] **Mobile tap popovers (PR #123).** Native hover `title` / SVG `<title>` tooltips never fire on touch, so the Form sparkline, Luck line, and Pace value are now tappable to show the same detail (dismiss by tapping elsewhere). `StatsTableContext` gained an optional `openInfo(content, event)`.
- [x] **`FPTS/G` → `Proj/G` rename (PR #124).** The column is the model's projected per-start, not a season average; renamed + a tap/hover note saying so. The internal `fptsPerStart` field name is unchanged.
- [x] **Projection model correctness fix (PR #125).** Three issues found reviewing the Start-breakdown tooltip:
  1. **Run-environment factors were applied backwards.** Opponent wOBA, park, and weather are run-environment factors (>1.0 = more offense = worse for the pitcher), but the engine multiplied the net projection by them directly, so tough conditions *raised* it. `get_park_factor`'s own docstring said Coors should make a pitcher score "~15% worse" while the code (×1.075) made it better. New `env_to_pitcher_mult()` (`2 − factor`) converts each to a pitcher multiplier (>1.0 helps); applied in the live + locked per-start paths and stored in `per_start_details` / the v2 breakdown.
  2. **Recent form didn't feed SP per-start projections** — only Proj/G and relievers used the 60/40 blend. Now the per-start skill base is scaled by the recent-vs-season ratio (live + lock), so the per-start total lines up with Proj/G.
  3. **The Start-breakdown tooltip didn't reconcile** — showed `adjustedBase` as the base while the math used `base_no_wl`, and W/L as an end add-on when it's inside the product. Rebuilt to: skill base → W/L (win prob) → adjusted base → ×lineup ×park ×weather = projected. `FactorLabel` colors pitcher multipliers (>1 green / <1 red); dead `inverse` flag removed.
  - Added a `MaeTimelineChart` milestone marker (2026-06-06) for the projection-output shift. **Forward-only** for locked values — existing locks keep their old numbers until they cycle out of the rolling window, so the MAE timeline has a discontinuity.
- [x] **Lost PR #115 re-land + stale-PR cleanup (PR #120, session 29).** A project review found PR #115's dropped-player Act-FPTS pruning was marked merged but never landed; re-landed fresh and closed stale PRs #115 + #42. (See the dropped-player pruning item above.)

## ✅ Completed (session 28 — April 27, 2026)
- [x] **PR #117 — Stats tab scaffolding on My Team + latent `percentOwned` backend bug fix.** Tab toggle (Schedule / Stats) on the My Team SP card. New `<StatsTable>` component with config-driven `PITCHER_COLUMNS` array — table is renderer-only, all data shaping in column defs. v1 columns from data already on the API response: Pitcher, Team, Slot, Own%, Starts, FPTS/G, Proj FPTS, Act FPTS. Sortable by any column, IL pitchers always sink to the bottom. Act FPTS total excludes pre-acquisition dates (rostered-window invariant). The new Own% column surfaced a latent backend bug: `pool_entry.get("percentOwned", 100)` was reading from `mRoster` (which doesn't carry ownership data) and silently defaulting to 100 for every rostered player. Fix folded into the same PR — extended the existing `kona_player_info` parsing loop to capture `player.ownership.percentOwned` per player_id (no extra HTTP call, same path the FA loop reads from), then sourced rostered ownership from that dict. Single PR, single verify cycle, no broken-UI window.
- [x] **PR #118 (combined PR 2 + PR 3) — Stats tab season + Savant columns with header tooltips.** Nine new columns inserted between Starts and FPTS/G: W-L (combined cell), ERA, K/9, BB/9, xERA, xwOBA, wOBAΔ, Brl%, Whiff%. Backend (`api/fetcher.py`): new `cache:savant-statcast:{year}` 24hr-TTL cache populated from `savant.fetch_statcast_stats()`; isolated key so a Statcast outage can't poison the projection-driving Savant cache. Backend (`api/espn.py`): two new helpers `_build_season_stats()` and `_build_savant_expected()` produce compact frontend-friendly sub-dicts; K/9 and BB/9 precomputed server-side. Each rosterSPs / freeAgentSPs / droppedPlayers entry now carries `seasonStats` and `savantExpected` (returns null when there's nothing to display, so the frontend renders an em-dash without per-field null checks). Frontend (`components/StatsTable.tsx`): added `preferredDir?: 'asc' | 'desc'` to the `PitcherColumn` interface so columns where lower is better (ERA, BB/9, xERA, xwOBA, Brl%) sort the right way on first click; sort comparator now sinks NaN sortValues to the bottom regardless of direction so pitchers without season stats stay at the bottom whether asc or desc. Added `tooltip?: string` field on `PitcherColumn` rendered as the native HTML `title` attribute on each header — tooltips on every meaningful column, skipped Pitcher and Team. New formatting helpers `fmtBaseballDecimal()` (".285" not "0.285") and `fmtWobaDiff()` (explicit + sign for unlucky deltas). wOBAΔ cell colors positive values green and negative red. PR ended up combined because the tooltip changes overlapped in the same file as the column additions — splitting would have required `git add -p` interactive staging.
- [x] **Backlog item closed:** "Stats view tab on My Team / Free Agents" — scaffolding, season, Savant, and tooltip pieces all shipped. Remaining sub-items (Whiff% plumbing, Cease name match, FA tab, luck badge, projected pace, relievers tab) re-filed under "Stats view tab — follow-ups" above.
- [x] **Workflow lesson: `vercel --prod` deploys from the local working tree without a `git push`.** Session 28 hit this: PR 2's code was deployed to production via `vercel --prod` but never pushed to a feature branch, then PR 3's tooltip work piled on top of the same uncommitted working tree. Recovery was bundling PR 2 + PR 3 into a single PR. Rule going forward: always push the branch before running `vercel --prod`, or treat `--prod` deploys without a corresponding git commit as ephemeral. KNOWLEDGE.md → Development Workflow now documents this.
- [x] **Workflow lesson: bundle PRs when their changes overlap in the same file.** Splitting `components/StatsTable.tsx` changes between PR 2 (columns) and PR 3 (tooltips) would have required `git add -p` interactive staging — too error-prone for a beginner workflow. Cleaner rule: when two pieces of work touch the same file, ship them in one PR even if they're conceptually separate. Conceptual separation is preserved in the PR description, not the commit boundary.
- [x] **Workflow lesson: when a new UI surface exposes a latent backend bug, fold the fix into the same PR.** PR #117's Own% column made the rostered `percentOwned` default-to-100 bug visible. The fix was small (~5 lines, no new HTTP call) and fit cleanly inside the same PR's verification surface. Folding meant one verify cycle, no broken-UI window, no separate follow-up PR. Rule: if the originating PR's diff has a clean place for the fix and the fix is small, fold; if either fails, ship broken UI and patch.
- [x] **Architecture pattern: new surfaces expose old assumptions.** Session 28's `percentOwned` bug is the same shape as session 27's UTC-vs-ET trigger bug — old code that's been silently wrong for a while because nothing was reading the value. KNOWLEDGE.md now articulates this as a checklist item: when adding any new UI surface that displays a previously-unsurfaced field, audit the upstream extraction once before shipping.

## ✅ Completed (session 27 — April 25, 2026)
- [x] **PR #113 — Rebuild `starts_map` after transaction-lag refetch (Montero case).** Inside the existing `if today_has_started(schedule):` branch in `api/espn.py`, after the refetch reassigns `roster_entries` from the next-period mRoster, re-extract `all_player_names` and `roster_team_map` and re-call `get_starts_for_players` to rebuild `starts_map`. Schedule from this call is discarded — original `schedule` is still authoritative. New log line `[espn.py] Lag-fix rebuild: starts_map refreshed for {N} players; new names: [...]` makes future regressions visible in Vercel logs at deploy time. Closes the diagnosed-but-not-fixed bug from session 26.
- [x] **PR #114 — Trigger lag-fix branch off scoring period, not UTC today (Montero EX-slot).** Verification of PR #113 in production surfaced a deeper bug: the lag-fix trigger silently skipped during evening usage. `today_has_started(schedule)` keyed off UTC today; ESPN's scoring-period boundary tracks ET, not UTC; whenever UTC had crossed midnight while ET hadn't (typical CT/PT evening), the check returned False and the lag-fix branch never ran. Replaced `today_has_started(schedule)` with `period_has_started(schedule, current_week)` in `api/fetcher.py` — derives the date from the scoring period ESPN just returned and checks game status on that date. Removes the timezone dependency entirely. Updated comment block in `api/espn.py` to explain the history so the next reader doesn't re-introduce the regression. `today_has_started` removed (single caller; no need to leave a footgun).
- [x] **PR #115 — Prune dropped player Act FPTS to rostered window (PR #81/#111 symmetry).** Closes the third of the three follow-ups from PR #111. `info["player_fpts"]` is now intersected with `days_on_team_set` in the dropped-player branch of `api/espn.py` before being stored into `roster_actual_fpts`. Without this, a dropped pitcher's post-drop relief appearance (or anything else ESPN attributes via the FA actual_fpts path) silently inflated the row total. Added `[espn.py] Dropped Act FPTS pruning: ...` log line, fires only when entries actually got pruned. JSON shape unchanged — frontend reads the same `actualFpts` map; values are now correct.
- [x] **Architecture pattern: rostered-window invariant.** Articulated in KNOWLEDGE.md as a new section with PRs #81, #111, #114, and #115 as the four enforcement points. Reads: "any per-pitcher value the user sees on the My Team page must be scoped to dates that pitcher was actually on the roster within the matchup window." When a future aggregation in `api/espn.py` sums or counts a per-date value, the invariant is the first thing to check.
- [x] **Workflow lesson: verification at the user-action layer surfaces the next bug class.** Three PRs shipped because each PR's verification in production exposed the next problem. PR #113's verification surfaced PR #114 (Montero in EX with no projection). Without running a real-user-action verification flow, both PR #114 and #115 would have stayed invisible. Pre-deploy theorycraft is no substitute for the actual reload-and-look pass.
- [x] **Workflow lesson: don't queue up the next PR's edits while the user is mid-workflow on the previous PR.** Mid-session, Claude proposed PR #114's edits while Conner was still finishing PR #113's git workflow, leaving uncommitted changes on a branch that needed to be checked out. Recovery cost a stash-and-re-branch dance. The rule that crystallized: one PR fully through the workflow (commit → push → PR → deploy → verify → merge → pull → branch off main) before the next edit lands in the working tree.
- [x] **New backlog item logged: dropped-player per-start projection display.** Surfaced during PR #114 verification when Montero (pre-fix) landed in `droppedPlayers`. Schedule grid only reads the global `projectionDetails` map; dropped players' details live on the player object as `pitcher.projDetails` and are never reached. Two fix options sketched in BACKLOG. Low urgency.

## ✅ Completed (session 26 — April 25, 2026)
- [x] **PR #111 — Roster-window bug for mid-week pickups (Wrobleski case).** Generalizes PR #81's `startDates ∩ days_on_team` intersection from dropped streamers to all currently-rostered pitchers. Mid-week pickups whose `startDates` included pre-roster dates were inflating Projected Starts (13/12 → 12/12 once corrected), Actual Starts, per-row `projFpts`, and the per-row Act FPTS column. Approach is "tag, don't drop": pre-acquisition starts stay in the data flow with a `preAcquisition: true` flag so the schedule grid can render them in muted styling (gray opp label, em-dash instead of ✓, gray FPTS, opaque `ProjectionTooltip` variant explaining "this start happened before you picked up this pitcher"). Backend tagging is post-hoc in `api/espn.py` after `my_team_pitchers_by_day` is populated, then recomputes effective `starts` count and subtracts pre-acq per-start projections from `projFpts` and `breakdown.total`. Frontend Act FPTS row total filters out pre-acq dates via the `startDates` flag; `pages/my-team.tsx` `actual` aggregate filters too. JSON shape stays backward-compatible (`preAcquisition` only present when true). Three downstream concerns deliberately deferred to backlog (lock-skip in projection.py, accuracy roster scope filter, dropped-player Act FPTS symmetry).
- [x] **Workflow lesson reinforced: deferred concerns belong in BACKLOG, not in the PR.** PR #111 had three obvious-once-you-look-at-them follow-ups (lock-skip, accuracy filter, dropped-player Act FPTS). Rather than scope-creep PR #111 into a lock-path refactor, all three were captured as backlog items with a one-line "why this is forward-only safe to defer" rationale each. The rule that crystallized: when scope creep tempts, ask "does the user lose anything visible if we ship without this?" — if no, defer with explicit notes; if yes, expand the PR.
- [x] **Diagnosed but not fixed: transaction-lag refetch leaves `starts_map` stale (Montero case).** Surfaced after PR #111 deployed when Conner added Keider Montero mid-day during the locked scoring period. Symptom: Montero appeared in roster_sps but his @CIN start tomorrow rendered with no green ✓ and the row showed `starts=0`, `projFpts=0.0`. Diagnosis: the existing transaction-lag block in `api/espn.py` (lines 154-181, from session 18 PR #73) updates `roster_entries` from the next-period mRoster but does NOT refresh `all_player_names`, `roster_team_map`, or `starts_map` — those were computed from the first fetch's player list, which doesn't include same-day pickups added during the locked window. Newly-added pitchers fall through `starts_map.get(name, {})` to the empty default. Bug has existed since session 18 PR #73; only surfaced now because Conner happened to add a player during the narrow locked-period window. Logged below as a known bug; fix promoted to next session priorities.

## ✅ Completed (session 25 — April 25, 2026)
- [x] **PR #108 — Cron actuals silent-failure hardening.** Long diagnostic detour traced an accuracy-dashboard data gap (Apr 23 showing 2 entries vs ~15 expected) to yesterday's cron run partially failing in `fetch_game_logs` — most per-player MLB Stats API calls returned HTTP 200 with empty splits, the `if games:` filter silently dropped them, the actuals block wrote a 380-byte 2-pitcher blob, and NX-write-once on `actual-all:2026-04-23` permanently locked it in. Three-layer fix: (1) `api/mlb.py` `fetch_game_logs` now returns `(data, stats)` where stats distinguishes 4 outcomes — `with_data`, `empty` (the silent-failure mode that was previously invisible), `http_errors`, `exceptions`. (2) `api/cron.py` invalidates `cache:mlb-stats:{year}` and `cache:game-logs:{year}` at the top of `lock_all_mlb_projections` to break the 24h-TTL/24h-cron race that was reusing stale partial data. (3) `ACTUALS_FLOOR = 4` skips NX-writes for any date with fewer than 4 entries — regular-season MLB days reliably have 10+ starts, so anything below 4 is almost certainly partial. Cron handler also now writes `cache:cron-summary:{date}` with 60-day TTL so post-hoc debugging survives Vercel Hobby's 1hr log retention. Verified in production: `gameLogStats: {requested: 519, with_data: 519, empty: 0, http_errors: 0, exceptions: 0}` — picture-perfect.
- [x] **PR #109 — Accuracy page display polish: lowercase names + missing matchup column.** Two bugs visible on the All MLB scope: player names rendered lowercase (`cade cavalli`) because they came from `actual-all:` keys which are accent-stripped and lowercased per session 24's slug normalization, and every row's matchup column showed `@?` because the `proj2all:` lock value's matchup sub-dict only stored `winProb` and `wpSource` (the projection.py path for `proj2:` already wrote `opponent`/`isHome`, but the cron path didn't). Fixes: `api/cron.py` matchup sub-dict gains `opponent` and `isHome` (now mirrors `projection.py`'s shape). `pages/accuracy.tsx` adds a `titleCase()` helper using `\b\w` regex applied to `s.player` rendering — idempotent for already-cased names so safe to apply universally regardless of scope. Forward-only on matchup: legacy `proj2all:` keys still show `@?` until they cycle out of the rolling window; new locks from the next 17:00 UTC cron onward populate correctly. Known imperfections logged to backlog: internal capitals (Mccullers/Degrom/Dejong) and 2-letter all-caps initials (Jt/Aj) — proper fix needs server-side `fullName` preservation.
- [x] **Diagnostic infrastructure pattern formalized.** `cache:cron-summary:{date}` joins the existing diagnostic surfaces in KV (`cache:daily:`, `proj2all:`, `actual-all:`, `projection-espn:`). Counter granularity in `gameLogStats` (with_data / empty / http_errors / exceptions split out) makes silent-failure modes spike visible in JSON without needing log retention. The "use KV as the debugger" pattern from session 24 is now a routine practice for any once-a-day cron-style write path.
- [x] **Decision: 24h cron cadence stays.** Discussed splitting projections (~9am CT for ESPN-confirmed probables) and actuals (~3am CT, after Pacific games end) into two cron jobs to use Hobby's 2-cron limit. Outcome: deferred. The win is small (slightly fresher actuals), the cost is real (refactor cron handler to accept a mode, update vercel.json), and the brittleness was the actual problem, not the schedule. After PR #108's hardening the case for splitting becomes purely UX-driven and can be revisited when there's a clearer reason.
- [x] **Workflow lesson reinforced: sandbox git operations are off-limits, even read-only.** Running `git status` / `git diff` from the sandbox left a `.git/index.lock` that blocked the user's terminal. Session 24's "Claude edits files; Conner drives git" rule extends to inspection commands, not just writes. Local validation in the sandbox is now restricted to `python3 ast.parse` and similar non-VCS-touching commands.

## ✅ Completed (session 24 — April 19, 2026)
- [x] **PR E — Accuracy page redesign: all-time aggregation + FA-leak fix** (PR #104). `api/accuracy.py` removed the matchup-period dropdown — endpoint now iterates all locked `proj2:` and `actual-all:` keys across the full season instead of a single period. My-Roster scope: pulls the current roster via `get_my_team_pitchers()` and filters projection keys to roster-slug matches, so FA projections no longer leak into the roster view. `pages/accuracy.tsx` dropped the period selector and updated copy to reflect all-time scope. Shipped alongside a UI tightening pass on the summary tiles.
- [x] **PR G — Silent game-logs API bug fix + accent-normalized slugs** (PR #105). Root cause: `/api/v1/people/{id}/stats?stats=gameLog&playerPool=all` silently returns empty (no error, no warning) when used as a bulk fetch. Switched `fetch_game_logs_for_players()` to per-player `/api/v1/people/{id}/stats?stats=gameLog` calls parallelized via `ThreadPoolExecutor` (12 workers). Added `_strip_accents()` helper and applied it inside `_to_slug()` so accented names (Luis García, José Berríos, etc.) now produce matchable slugs across MLB Stats API, ESPN Fantasy, and ESPN Forecaster sources. Diagnostic detour: since Vercel Hobby only retains logs for 1 hour, used KV keys as the observability surface — added `cache:cron-summary:{date}` write so we could inspect after-the-fact what the cron actually locked.
- [x] **PR F — MAE timeline chart with model milestone markers** (PR #106). New `components/MaeTimelineChart.tsx` renders a recharts `LineChart` on the All-MLB tab of the accuracy dashboard: solid lines for daily Skipper vs. ESPN MAE, dashed lines for 7-day trailing rolling averages (calendar-day window, sample-count weighted — not row-count, which would over-smooth on sparse dates), plus vertical `ReferenceLine` markers for model-changing deploys (Vegas W/L + xERA, Blended wOBA + weather, recentForm fix). Zero backend changes — `/api/accuracy` already attaches `espnFpts`/`espnError` to starts when `scope=="all"`, so all computation is client-side off the existing payload. Scoped to `scope === 'all'` only since ESPN projections are whole-MLB and don't map to a single fantasy roster. `recharts@^2` added as a dep (~90kb gz).
- [x] **Ops — CRON_SECRET rotated** after the old value showed up in a tracked `.env.vercel.prod` dump (caught by PR #98's `.gitignore` pattern). New secret written to Vercel prod env; cron verified green on the next tick.

## ✅ Completed (session 23 — April 18, 2026)
- [x] **PR #101 — ESPN empty-state polish on accuracy dashboard.** Two gaps from session 22's PR C closed: (1) `api/accuracy.py` early-return path now computes `espnSummary` when `scope === 'all'` even with no `proj2all:` keys — refactored ESPN lookup + summary math into two module-level helpers (`_fetch_espn_lookup`, `_compute_espn_summary`) shared between the early-return and normal paths. (2) `pages/accuracy.tsx` empty-state branch now wraps in a fragment and renders `EspnHeadToHead` above the empty card when `scope === 'all'` and `espnSummary` is non-null. Empty-state subtext surfaces ESPN lock count so users can see data accumulating before Skipper actuals exist.
- [x] **PR #102 — Weather Phase 2: wire `get_weather_factor()` into projection pipeline.** Session 20's weather module is now a live per-start multiplier alongside wOBA and park factors. Backend (`api/projection.py`): import added, live loop applies `weather_factor` to `start_proj`, `per_start_details` carries `weather`/`tempF`/`weatherSource`, lock path mirrors the same calc so locked FPTS equals live FPTS, and v2 locked breakdowns gain a new `"weather": { factor, tempF, source }` block for accuracy analysis. Frontend (`components/ProjectionTooltip.tsx`): `StartDetail` interface extended, single-start mode renders `Weather (72°F) ×1.012` row when `weatherSource === 'forecast'`, total mode adds a compact weather `FactorLabel` per start. Dome parks and default-fallback states hide the weather UI to avoid noise. All failure paths in `get_weather_factor` return factor=1.0, so Open-Meteo outages cannot break projections; 3hr Redis cache prevents API spam; ±5% cap enforced on the multiplier.
- [x] Direct folder access established via `request_cowork_directory` — Claude can now read/edit files in `~/Developer/the-skipper` without copy/paste. Git commit/push/deploy still run locally (sandbox can't write `.git/` reliably). Two PRs shipped in one session under the new workflow.

## ✅ Completed (session 22 — April 18, 2026)
- [x] **PR B — Daily cron locks ESPN Forecaster projections to KV** (PR #97). `lock_espn_projections()` added to `api/cron.py`: fetches today's MLB-confirmed probables, builds an accent-stripped name lookup, pulls the ESPN Forecaster for today only, reconciles each entry against the MLB set, and SETNX-writes confirmed matches to `projection-espn:{year}:{period}:{slug}:{date}` with a 60-day TTL. Skips placeholder entries (FPTS == 1.0) and orphans (ESPN pitcher not in MLB's confirmed set). First production run locked 29 new keys with 1 skipped_unconfirmed; idempotency verified on second run (locked_new: 0, locked_skipped_existing: 29). Cron handler now calls MLB and ESPN locking independently and returns a merged `{ok, mlb, espn}` summary so one failure doesn't hide the other's counters.
- [x] **PR #98 — Tighten `.gitignore` to prevent Vercel secret dumps** from ever being tracked. Added `.env.vercel*` pattern after `vercel env pull --environment=production` left `.env.vercel.prod` in the working tree during CRON_SECRET debugging. Previous pattern (`.env*.local`) didn't cover it.
- [x] **PR C — Accuracy dashboard ESPN MAE head-to-head** (PR #99). Backend: when `scope == "all"`, `api/accuracy.py` fetches `projection-espn:{season}:{period}:*` keys, attaches `espnFpts` / `espnError` to each matched start, and computes an `espnSummary` with ESPN MAE plus the apples-to-apples `skipperMaeOnIntersection` (Skipper's MAE recomputed on only the starts where ESPN also had a projection). Frontend: new `EspnHeadToHead` component renders three tiles (Skipper MAE, ESPN MAE, Advantage) above the existing summary when scope is All MLB. Winning side gets a soft-green highlight. Optional ESPN column added to the starts table. Roster scope unchanged. Deploy verified — head-to-head block awaits first completed actuals overlap (expected April 19 after 17:00 UTC cron).

## ✅ Completed (session 21 — April 18, 2026)
- [x] Spike: confirmed ESPN Fantasy API `kona_player_info` returns only full-season projections, not per-day (PRs #88, #89, #90, #91) — `statSourceId: 1` entries all have `statSplitTypeId: 0` and `scoringPeriodId: 0`. No per-day projection data in the Fantasy API at any point in the season.
- [x] Diagnostic endpoint probing ESPN Forecaster article (`/api/forecaster_probe`) — confirmed server-rendered HTML, one `<table>`, 60 `<tr>` rows, no JS hydration, all rostered pitchers present (PR #92)
- [x] PR A — `api/forecaster.py` scraper module + `/api/forecaster` diagnostic endpoint: fetches the ESPN Forecaster article, parses the projection table into per-start entries, returns 260 entries across all 30 teams for the 10-day rolling window (PR #93)
  - `_split_br()` / `_split_pitcher_cell()` helpers handle `<td><div>…<br>…</div></td>` wrapper variants
  - `PLACEHOLDER_FPTS_VALUE = 1.0` flagged via **exact-equality** check (not threshold) — Coors pitchers legitimately project negative, a `<= 1.0` check would wrongly flag them
  - `LOGO_TO_TEAM_OVERRIDES` maps non-standard ESPN slugs to canonical abbrevs
  - `beautifulsoup4==4.12.3` added to `requirements.txt`
- [x] Washington team abbreviation normalization — ESPN Forecaster logo filename is `was.png`, everywhere else uses `WSH`. Added `"was": "WSH"` to `LOGO_TO_TEAM_OVERRIDES` so team/opp join keys stay consistent downstream (PR #94)
- [x] `middleware.ts` matcher extended to exempt `/api/auth/*`, `/api/cron/*`, `/api/forecaster`, `/api/forecaster_probe`, `/api/espn_proj` from NextAuth — unblocks Vercel Cron (no session) and plain-curl verification of public endpoints. Protected endpoints (`/api/projection`, `/api/accuracy`, user-specific routes) stay behind the auth gate. (PR #95)

## ✅ Completed (session 20 — April 18, 2026)
- [x] Cache team wOBA factors with 24hr TTL under `cache:team-woba:{year}` (PR #83)
- [x] Refactored `get_team_woba` to use pure helper `_compute_team_woba_factors(splits, min_games, label)` (PR #84)
- [x] Added `get_team_woba_recent(season, days=14)` using MLB Stats API `byDateRange` statsType (PR #84)
- [x] Added `get_team_woba_blended(season, recent_days=14, recent_weight=0.35)` — parallel fetch via ThreadPoolExecutor, 65% season / 35% last-14-day (PR #84)
- [x] Fetcher switched from `get_team_woba` to `get_team_woba_blended` — same cache key, blended value now cached (PR #84)
- [x] New `api/weather.py` module — Open-Meteo client, 30-park `PARK_COORDS`, 8-park `DOME_PARKS`, temperature-only run environment factor (±5% cap, 50% dampened) (PR #85)
- [x] `get_weather_factor(park, date)` — dome override → cache lookup → Open-Meteo fetch → compute → 3hr TTL under `cache:weather:{park}:{date}`, graceful fallback to 1.0 on any failure (PR #85)
- [x] Diagnostic endpoint `/api/weather?park=X&date=Y` for production verification before wiring (PR #85)
- [x] Added `__pycache__/` and `*.pyc` to `.gitignore`

## ✅ Completed (session 19 — April 16, 2026)
- [x] Dropped streamers: count starts that happened while rostered (PR #81)
- [x] Dropped streamers: route through projection pipeline so per-start projections render in schedule grid (PR #81)
- [x] Backend intersects `startDates` with `days_on_team` — only counts rostered-window starts (PR #81)
- [x] Actual Starts and Projected Starts tiles now include dropped streamers in aggregation (PR #81)
- [x] Tile filters changed from `s.confirmed` to `s.date <= today || s.confirmed` — past starts always count (PR #81)
- [x] Rostered SPs tile excludes IL-slot players (PR #81)
- [x] ScheduleGrid past/today indicator shows green ✓ for any start that has happened or is happening (PR #81)

## ✅ Completed (session 18 — April 12, 2026)
- [x] espn.py refactor: split 1220-line monolith into projection.py, fetcher.py, espn.py (PR #73)
- [x] Factor contribution analysis on accuracy dashboard (PR #74)
- [x] Refresh button on accuracy page (PR #74)
- [x] Vegas moneyline win probability from ESPN scoreboard (PR #75)
- [x] Pythagorean win expectation model with Log5 + pitcher xERA adjustment (PR #75)
- [x] Per-start W/L scaling: team_win_prob × 0.57 starter share (PR #75)
- [x] Win probability shown in tooltip with Vegas/Pythagorean source badge (PR #75)
- [x] Daily cron job for all-MLB projection locking at noon CT (PR #76)
- [x] All-MLB actuals from game logs stored under actual-all: keys (PR #76)
- [x] Accuracy page: My Roster / All MLB scope toggle (PR #76)
- [x] CRON_SECRET env var for cron endpoint security (PR #76)
- [x] Cache team_win_data with 24hr TTL (PR #77)
- [x] Opponent starter xERA threaded through schedule → projection model (PR #77)
- [x] Schedule grid shows adjusted per-start projection instead of base rate (PR #77)
- [x] W/L impact shown in projection tooltip (PR #77)
- [x] Free Agents: sortable Act FPTS column (PR #77)
- [x] Free Agents: date column sort uses adjusted projection (PR #77)
- [x] Compact grid cells: indicator inline with opponent label (PR #77)
- [x] My Team: roster sorted by per-start quality (projFpts/starts) (PR #77)

## ✅ Completed (session 17 — April 12, 2026)
- [x] Color scheme refresh — midnight dark theme with Inter + JetBrains Mono (PR #71)

## ✅ Completed (session 16 — April 12, 2026)
- [x] Sidebar collapses on mobile (PR #69)
- [x] Top header gets hamburger menu on small screens (PR #69)

## ✅ Completed (session 15 — April 12, 2026)

- [x] ESPN stat ID mapping verified (10/10 confidence) — W/L corrected to stat 53/54 (PR #66)
- [x] `ESPN_PITCHING_STAT_IDS` constant added to `espn.py` (PR #66)
- [x] Actual per-stat extraction in `get_actual_fpts()` — all 9 scoring stats from ESPN raw_stats (PR #66)
- [x] `actual_stats` stored in daily cache alongside fpts/saves/bench/my_team (PR #66)
- [x] Accuracy dashboard: `api/accuracy.py` endpoint + `pages/accuracy.tsx` page (PR #67/68)
- [x] Summary tiles, per-stat MAE bar chart with bias, expandable per-start comparison table
- [x] Added to sidebar navigation (PR #67/68)
- [x] Old daily caches cleared to re-populate with actual_stats

## ✅ Completed (session 14 — April 11, 2026)

- [x] V2 projection locking — `set_locked_projection_v2()` stores full JSON breakdown per start (PR #64)
- [x] V2 key schema: `proj2:{season}:{period}:{player-slug}:{date}` → JSON (PR #64)
- [x] V1 float locking preserved for frontend compatibility (PR #64)

## ✅ Completed (session 13 — April 11, 2026)

- [x] Layer 2: Recent form weighting (PR #60)
- [x] Layer 3: Park factors (PR #60)
- [x] Projection tooltip with total + per-start breakdown modes (PR #60)
- [x] Renamed `option_b_inputs` → `projection_inputs` throughout (PR #60)

## ✅ Completed (session 12 — April 11, 2026)

- [x] Savant-powered hybrid projection model (PR #56)
- [x] All caching infrastructure — Savant, MLB Stats, daily FPTS (PRs #57-59)
- [x] Dropped streamer detection (PRs #52-53)
- [x] KNOWLEDGE.md, tile redesign, bench/IL normalization (PRs #49-51, 54-55)
- [x] Response time reduced from ~4.8s to ~2.1s

## ✅ Completed (sessions 1-11)

See CHANGELOG.md for full history of PRs #1-#47.

---

## 💡 Future ideas

### Promoted proposals (June 10, 2026 review — ranked, see REVIEW.md for rationale)

1. ~~**Hitters in AI recommendations**~~ *(also P1)* — **shipped session 43** (see P1 #1).
2. **Regret tracker / "points left on bench"** — daily optimal-lineup retrospective:
   compare actual lineup FPTS vs the best possible lineup from locked projections +
   actuals (all already in KV: `proj2:`/`proj2h:`/`acth:`/`actual-all:`). Quantifies
   the tool's value and builds trust; a natural Accuracy-page sibling tab.
3. **Morning lineup check / scratch alerts** *(also P1)* — pre-first-pitch digest:
   benched players with games, starters without games, probable-starter scratches
   (diff today's probables vs yesterday's), weather postponement risk. Start as an
   on-page dashboard digest; push notifications later.
4. **Projection confidence bands** — floor/median/ceiling per start instead of a point
   estimate, derived from historical MAE by factor profile. Directly monetizes the
   accuracy archive no comparable tool has.
5. **Two-start-pitcher / streamer lookahead planner** — 2–3 week scan of FantasyPros
   probables (already plumbed, 12 days out) + schedule to flag stream targets and
   two-start weeks before the league notices. Concretizes "schedule advantage alerts."
6. **Accuracy-driven factor auto-tuning** — periodically refit factor weights (wOBA
   blend, park, recent-form 60/40, weather) against accumulated locked-vs-actual data;
   turns the accuracy dashboard from reporting into model improvement.
7. **"Ask the Skipper" conversational analyst** — chat endpoint that gives Claude the
   full roster/FA/projection payload + league rules for ad-hoc questions ("hold García
   through the @COL series?"). Natural extension of `analyze.py`.
8. **ESPN cookie health check** — daily cron ping of an authed ESPN endpoint; surface
   expiry on the dashboard *before* every page silently breaks (top risk in REVIEW.md).

### Considered and deferred

- **Direct lineup writes to ESPN** (June 10, 2026) — technically feasible (private
  `lm-api-writes` transactions endpoint, same `espn_s2`/`SWID` cookies, slot IDs
  already documented in KNOWLEDGE.md), but **deferred by decision: not worth the
  ESPN ToS risk**. The Skipper stays read-only; recommendations remain advisory.

### Earlier ideas (unranked)

- ~~Trade analyzer with forward-looking schedule context~~ — superseded by the
  3-phase **Trade engine** spec (approved June 12, 2026; see the section above
  and P1 #3–4)
- Waiver wire rankings personalized to roster needs and matchup context
- Live game decision engine (real-time starts limit optimization)
- Schedule advantage alerts (2-3 week lookahead for favorable/unfavorable stretches)
- Opponent scouting report per matchup period
- Push notifications for pitcher changes, injury news, prospect call-ups
- Multi-user support / league sharing
- Mobile app (React Native)
- Pay for a proper probable pitchers data source once serving real users

---

## 🔧 Environment variables

All set in both `.env.local` (local) and Vercel dashboard (production):

| Variable | Purpose |
|---|---|
| `APP_USERNAME` | Login username |
| `APP_PASSWORD` | Login password |
| `NEXTAUTH_SECRET` | JWT encryption key |
| `NEXTAUTH_URL` | `https://the-skipper-iota.vercel.app` |
| `ESPN_LEAGUE_ID` | Fantasy league ID (77651433) |
| `ESPN_SEASON` | `2026` |
| `ESPN_S2` | ESPN auth cookie |
| `ESPN_SWID` | ESPN auth cookie |
| `ESPN_TEAM_ID` | Your team number (6) |
| `ESPN_STARTS_LIMIT` | Weekly pitcher starts limit (12) |
| `ANTHROPIC_API_KEY` | Claude API key |
| `CLAUDE_MODEL` | *(optional)* Claude model for recommendations (default `claude-sonnet-4-6`) |
| `KV_REST_API_URL` | Upstash Redis REST URL |
| `KV_REST_API_TOKEN` | Upstash Redis REST token |

---

## 🛠️ Local dev setup
```bash
cd ~/Developer/the-skipper
git checkout main
git pull origin main
vercel dev   # frontend only — Python routes require production
```

Open `http://localhost:3000`. Python API routes only work at `https://the-skipper-iota.vercel.app`.

**Deploy sequence:** `git add` → `git commit` → `vercel --prod`
**Git workflow:** Feature branches → PR → squash merge. Prefixes: `fix:`, `feat:`, `chore:`, `docs:`

---

## 📚 Reference

All API reference documentation, architecture decisions, league settings, and development workflow are maintained in **[KNOWLEDGE.md](KNOWLEDGE.md)** — the single source of truth for technical reference.
