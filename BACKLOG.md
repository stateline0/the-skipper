# The Skipper — Backlog

Last updated: April 12, 2026

---

## 🔜 Next session priorities

### Weekly planner / decision automation MVP
- [ ] AI-powered weekly optimization: recommend add/drop sequence and start/sit decisions
- [ ] Teach Anthropic API about ESPN transaction rules (daily locks, waiver priority)
- [ ] Hybrid mode: AI suggests plan, user picks A/B for key decisions, AI outputs full sequence
- [ ] Uses projection model data as input

### Vegas odds for W/L projection
- [ ] Integrate free betting odds API (The Odds API or ESPN scoreboard lines)
- [ ] Use implied win probability to improve W/L projections (currently discounted 50%)
- [ ] Could replace flat 50% discount with game-specific probabilities

### espn.py full rewrite
- [ ] File has accumulated many patches and is ~1150 lines
- [ ] Clean separation of data fetching, projection model, and API response building
- [ ] Should be done when a significant change touches multiple sections

### Color Scheme Refresh
- [ ] Color scheme refresh — assess and update the site's color palette

---

## 📋 Backlog (lower priority)

### Projection model — Layer 4: Platoon splits
- [ ] Pitcher performance vs left-heavy vs right-heavy lineups
- [ ] Team handedness composition from MLB Stats API

### Projection model — Layer 5: Rest & workload
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

- [ ] Free agent actual FPTS only available for players who were rostered at time of start — ESPN API limitation (affects accuracy dashboard too)
- [ ] `vercel dev` does not serve Python API routes locally (Vercel CLI v50+ known issue)
- [ ] Dropped players show projFpts 0.0 — could pull locked projections from KV

---

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
