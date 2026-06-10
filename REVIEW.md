# The Skipper — Full Repo Review (June 10, 2026)

Complete review of the codebase: bugs, gaps, and improvement areas, with fixes
shipped or proposed; plus the rationale behind the backlog prioritization in
`BACKLOG.md` → **🎯 Prioritization** and the new feature proposals in
**💡 Future ideas → Promoted proposals**.

---

## 1. Findings

Severity: **H** = breaks or silently corrupts something, **M** = degrades
reliability/debuggability, **L** = hygiene. Status: ✅ fixed this session,
📋 proposed (documented here, not yet implemented).

| # | Sev | Status | Location | Finding & fix |
|---|-----|--------|----------|---------------|
| 1 | H | ✅ | `api/analyze.py:79` | Hardcoded `claude-sonnet-4-20250514` — **deprecated, retires June 15, 2026**; Recommendations would hard-break in days. Now reads `CLAUDE_MODEL` env var, default `claude-sonnet-4-6` (the drop-in replacement). |
| 2 | H | ✅ | `requirements.txt` | `anthropic==0.25.0` was ~2 years stale. Bumped to `0.109.1`; verified `messages.create(model, max_tokens, system, messages)` call shape unchanged. |
| 3 | H | ✅ | `api/espn.py`, `api/fetcher.py`, `api/espn_proj.py`, `api/hitters.py` (×2) | `os.environ["ESPN_LEAGUE_ID"]` raised a bare `KeyError` when unset. All 5 sites now raise a clear "Missing env var ESPN_LEAGUE_ID — set it in Vercel…" error. |
| 4 | H | ✅ | `api/espn.py` (roster fetch) | ESPN 401/403 surfaced as a cryptic `ESPN returned HTTP 401`. Now explains the likely cause (expired `ESPN_S2`/`ESPN_SWID`) and the remedy (re-copy cookies from fantasy.espn.com). |
| 5 | M | ✅ | `api/mlb.py:579` | `datetime.utcnow()` (deprecated in Py3.12+, inconsistent with the rest of the codebase) → `datetime.now(timezone.utc)`. |
| 6 | M | ✅ | `api/projection.py`, `api/cron.py` | `parse_ip()`/`_parse_ip()` silently returned `0.0` on unparseable input (e.g. MLB's `"-.--"` early-season placeholder), hiding data-quality issues. Now logs the bad value. Consistent with the project's "silent failures are the enemy" KV-diagnostics philosophy. |
| 7 | M | ✅ | `api/kv.py` (`get_all_locked_projections_v2`, `…_hitter_projections`) | Corrupted JSON blobs were skipped silently. Now logs the affected key. |
| 8 | M | ✅ | `api/projection.py::per_game_avgs` | Implicit division-by-zero protection relied on `MIN_*` constants being ≥1. Added explicit `games <= 0` guard. |
| 9 | M | 📋 | all external HTTP callers | No retry/backoff for ESPN / MLB Stats / Savant / FantasyPros. A transient 429/5xx silently under-populates the warm cache. Proposal: a small shared retry wrapper (2–3 attempts, exponential backoff) per file, following the repo's no-shared-utils convention. |
| 10 | M | 📋 | `vercel.json` cron auth | Cron endpoints validate only the `CRON_SECRET` header. Proposal: additionally validate Vercel's `x-vercel-signature` where available. |
| 11 | M | 📋 | `api/mlb.py` (`fetch_game_logs_hitting`) | Docstring says "call with a SUBSET" but nothing enforces it; 10-thread pool × full-MLB input would hammer the MLB Stats API. Proposal: guard/log when input exceeds ~150 players. |
| 12 | M | 📋 | `next.config.js` | `ignoreBuildErrors: true` + `ignoreDuringBuilds: true` means TS/ESLint regressions ship silently. Proposal: run `tsc --noEmit` once, fix the existing errors, then drop the flags. |
| 13 | L | 📋 | `api/mlb.py` `PARK_FACTORS` | Hardcoded, "last updated April 2026," no documented refresh process. Proposal: document an update cadence (monthly) or fetch from Savant's park-factors CSV. |
| 14 | L | 📋 | `requirements.txt` | Exact pins with no update process; consider a periodic bump cadence (security patches for `requests`, `beautifulsoup4`). |
| 15 | L | 📋 | 6 files | `strip_accents()` duplicated in 6 files. Deliberate (serverless isolation per `config.py` comment), but worth a comment at each site pointing at the canonical copy so they don't drift. |
| 16 | L | 📋 | `api/hitters.py` handler | No tests for the HTTP handler / scoring-parse integration (the model itself has 22 tests). Proposal: `api/test_hitters.py` with a canned `mSettings` fixture. |
| 17 | L | 📋 | `api/hitters.py`, `api/espn.py` | `?week=`/`?period=` query params aren't validated against `MATCHUP_PERIODS`; out-of-range values fall through silently. |
| 18 | L | 📋 | `middleware.ts` | `/api/forecaster`, `/api/forecaster_probe`, `/api/espn_proj` are intentionally unauthenticated (commented as read-only diagnostics) — but `espn_proj` returns roster data. Worth re-checking that's acceptable. |

**Findings investigated and rejected** (so they don't resurface later):
- `config.py::get_current_period` correctly returns the **last** period after
  season end — an earlier review pass claimed it falls back to period 1; false.
- `parse_ip` exists only in `projection.py` and `cron.py` (not `fetcher.py`).
- The `_cache_executor.shutdown(wait=False)` in `espn.py` is safe as written:
  `cached_future.result()` is resolved before the projection step consumes it.

---

## 2. Architecture strengths (preserve these)

- **Projection locking (NX, write-once)** — frozen at game start, enabling honest
  model evaluation. This accuracy archive is the project's moat; no mainstream
  fantasy tool shows its own MAE.
- **KV-as-debugger** (`cache:cron-summary:{date}`) — outlives Vercel's 1-hour log
  retention; the right pattern for once-daily jobs.
- **Rostered-window invariant** — consistently enforced across four PRs; documented
  in KNOWLEDGE.md.
- **Stat-vector hitter model** — per-stat factors fall out naturally, and category
  leagues become a scoring-dot-product swap (cheap future productization).
- **Year-blend by volume** (IP/PA thresholds) — principled small-sample handling.

## 3. Risk register (single points of failure)

| Risk | Impact | Mitigation |
|---|---|---|
| ESPN cookie expiry | Every page breaks at once, silently | #4 above (better error) shipped; **cookie health-check cron** proposed (Future ideas #8) |
| Forecaster / FantasyPros scrapers | Probables & ESPN-comparison data loss (already broke once via AWS WAF) | Loud errors in cron-summary exist; keep the probe endpoint |
| Park factors going stale | Slow projection drift over the season | Finding #13 |
| Anthropic model retirement | Recommendations hard-break | Fixed (#1) — `CLAUDE_MODEL` env var makes the next migration a config change |
| Vercel 1-hr logs | Undiagnosable transient failures | KV diagnostics pattern; extend to more paths (findings #6–7 shipped) |

## 4. Prioritization rationale (summary — tiers live in BACKLOG.md)

Goal: *most indispensable fantasy baseball companion*, personal-tool-first.
Indispensable decomposes into **trust** (projections demonstrably good, and shown
to be good) and **loop completeness** (every daily/weekly decision answerable in
the app). Hence:

- **P0** = accuracy-data correctness (actuals unification, exact counterfactuals,
  starts-only rates) — everything downstream is built on this data.
- **P1** = decision automation: get hitters into the AI recommendations (today
  `analyze.py` sees only pitchers — the single biggest functional gap found in
  this review), then the planner MVP, nudges, and the morning check.
- **P2** = model depth, in expected-MAE-impact order.
- **P3** = polish/ops. **Horizon** = productization, deferred deliberately.

## 5. New feature proposals

Ranked list with implementation notes lives in `BACKLOG.md` → **💡 Future ideas →
Promoted proposals** (hitters-in-recommendations, regret tracker, morning
lineup check, confidence bands, streamer lookahead, factor auto-tuning,
conversational analyst, cookie health check).
