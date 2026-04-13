# The Skipper — Backlog

Last updated: April 12, 2026

---

## 🔜 Next session priorities

### Accuracy page redesign
- [ ] Remove matchup period dropdown — show all-time data across all periods
- [ ] Fix "My Roster" scope leaking FA projections (filter proj2: keys to actual roster players)
- [ ] MAE timeline chart with model milestone markers (e.g., "Added park factors", "Vegas W/L")
- [ ] Rolling MAE over time to visualize model improvement

### Weekly planner / decision automation MVP
- [ ] AI-powered weekly optimization: recommend add/drop sequence and start/sit decisions
- [ ] Teach Anthropic API about ESPN transaction rules (daily locks, waiver priority)
- [ ] Hybrid mode: AI suggests plan, user picks A/B for key decisions, AI outputs full sequence
- [ ] Uses projection model data as input

### Model Improvements
- [ ] Recent form for opposing lineup (blend season wOBA with last 7-14 day team hitting)
- [ ] Weather impact layer (temperature + wind direction via Open-Meteo API, map parks to lat/lng)
- [ ] Cache team wOBA factors with 24hr TTL (same pattern as team_win_data)

---

## 📋 Backlog (lower priority)

### Projection model — Layer 5: Platoon splits
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

### Hitter nudge engine
- [ ] Lighter-weight than pitcher optimizer — "this waiver wire guy is outperforming your current 2B"
- [ ] Not a full streamer optimizer, more of a watchlist with performance alerts

### Dropped streamers refinement
- [ ] Pull locked projections from KV for dropped players' past starts
- [ ] Show proj FPTS for the starts they made while rostered

### Additional caching opportunities
- [ ] Team wOBA factors (24hr TTL — single API call, low priority)
- [ ] Pro team map (permanent — barely changes)

### Dashboard at-a-glance component
- [ ] Projected starts vs limit, current period dates, quick links

---

## 🐛 Known bugs

- [ ] Suspended players (SSPD) not appearing in roster — Reynaldo Lopez added but missing from mRoster response. Likely ESPN uses different eligibleSlots or lineupSlotId for suspended players.
- [ ] "My Roster" accuracy scope shows non-roster pitchers — FA projections leak into proj2: keys
- [ ] Free agent actual FPTS only available for players who were rostered at time of start — ESPN API limitation (affects accuracy dashboard too)
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue)
- [ ] Dropped players show projFpts 0.0 — could pull locked projections from KV

---

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

- Trade analyzer with forward-looking schedule context
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
