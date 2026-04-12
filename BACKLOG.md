# The Skipper — Backlog

Last updated: April 11, 2026

---

## 🔜 Next session priorities

### Implement ESPN stat ID mapping + store actual per-stat results
- [ ] Add `ESPN_PITCHING_STAT_IDS` constant to `espn.py`: {34: outs, 48: so, 37: h, 42: bb, 45: er, 46: hb, 32: w, 33: l, 57: sv}
- [ ] Extract individual stats from ESPN `raw_stats` dict in `get_actual_fpts()`
- [ ] Store actual per-stat results in KV: `actual:{season}:{period}:{player-slug}:{date}` → JSON
- [ ] Only store for completed games (not today/in-progress)
- [ ] Pairs with `proj2:` keys for direct projected-vs-actual comparison

### Model accuracy tracking dashboard
- [ ] Dashboard showing projected vs actual FPTS per start
- [ ] Per-stat accuracy: projected K vs actual K, projected ER vs actual ER, etc.
- [ ] Mean absolute error (MAE) per pitcher and overall
- [ ] Directional accuracy (did we correctly predict above/below average?)
- [ ] Factor contribution analysis (how much did wOBA/park adjustments help?)
- [ ] Uses v2 locked projections (`proj2:`) + actual stats (`actual:`) from KV as ground truth

### espn.py full rewrite
- [ ] File has accumulated many patches and is ~1150 lines
- [ ] Clean separation of data fetching, projection model, and API response building
- [ ] Should be done when a significant change touches multiple sections

---

## 📋 Backlog (lower priority)

### Projection model — Layer 4: Platoon splits
- [ ] Pitcher performance vs left-heavy vs right-heavy lineups
- [ ] Team handedness composition from MLB Stats API

### Projection model — Layer 5: Rest & workload
- [ ] Days since last start (4 vs 5+ day rest performance)
- [ ] Season pitch count trajectory (fatigue effects)
- [ ] Most meaningful mid-to-late season

### Vegas odds for W/L projection
- [ ] Integrate free betting odds API (The Odds API or ESPN scoreboard lines)
- [ ] Use implied win probability to improve W/L projections (currently discounted 50%)
- [ ] Could replace flat 50% discount with game-specific probabilities

### Weekly planner / decision automation
- [ ] AI-powered weekly optimization: recommend add/drop sequence and start/sit decisions
- [ ] Teach Anthropic API about ESPN transaction rules (daily locks, waiver priority)
- [ ] Hybrid mode: AI suggests plan, user picks A/B for key decisions, AI outputs full sequence
- [ ] Prerequisite: accuracy tracking (need to trust projections before automating decisions)

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

- [ ] Free agent actual FPTS only available for players who were rostered at time of start — ESPN API limitation
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue)
- [ ] Dropped players show projFpts 0.0 — could pull locked projections from KV

---

## ✅ Completed (session 14 — April 11, 2026)

- [x] V2 projection locking — `set_locked_projection_v2()` stores full JSON breakdown per start (PR #64)
- [x] V2 key schema: `proj2:{season}:{period}:{player-slug}:{date}` → JSON (PR #64)
- [x] V2 stores per-stat projections, matchup context, and model metadata (PR #64)
- [x] V1 float locking preserved for frontend compatibility (PR #64)
- [x] ESPN stat ID mapping discovered and verified: 34=outs, 48=K, 37=H, 42=BB, 45=ER, 46=HBP, 32=W, 33=L, 57=SV

## ✅ Completed (session 13 — April 11, 2026)

- [x] Layer 2: Recent form weighting — `fetch_game_logs()`, `compute_recent_form_fpts()`, 60/40 season+recent blend (PR #60)
- [x] Layer 3: Park factors — `PARK_FACTORS` dict (30 teams), `get_park_factor()` dampened 50%, per-start multiplier (PR #60)
- [x] `is_home` field added to startDates for correct home/away park identification (PR #60)
- [x] Game log caching — 24hr TTL (`cache:game-logs:YYYY`) (PR #60)
- [x] Projection tooltip — `ProjectionTooltip` component with total + per-start breakdown modes (PR #60)
- [x] Tooltip wired into both My Team and Free Agents pages (PR #60)
- [x] Renamed `option_b_inputs` → `projection_inputs` throughout (PR #60)
- [x] Bumped CACHE_VERSION on both pages (PR #60)

## ✅ Completed (session 12 — April 11, 2026)

- [x] Projection sequencing fix — option_b_inputs after transaction lag re-fetch (PR #49)
- [x] Bench/IL normalization — all pitchers treated identically for projections (PR #49)
- [x] KNOWLEDGE.md created with confidence-rated API reference (PR #49)
- [x] Tile redesign — actual starts, projected starts, SP-only count (PR #51)
- [x] Dropped streamer detection — EX badge, sort order fix (PRs #52, #53)
- [x] Baseball Savant data fetcher — `api/savant.py` verified (PR #54)
- [x] Savant-powered hybrid projection model — xBA/xERA replace luck-influenced stats (PR #56)
- [x] Savant data caching — 2025 permanent, 2026 24hr TTL (PR #57)
- [x] MLB Stats API caching — same pattern (PR #58)
- [x] Daily actual FPTS caching — completed days permanent (PR #59)
- [x] Response time reduced from ~4.8s to ~2.1s (56% improvement)

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
