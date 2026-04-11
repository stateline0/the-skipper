# The Skipper — Backlog

Last updated: April 11, 2026

---

## 🔜 Next session priorities

### Projection model — Layer 2: Recent form weighting
- [ ] Fetch per-start game logs from MLB Stats API
- [ ] Compute rolling weighted average: last start 40%, second 30%, third 20%, fourth 10%
- [ ] Blend with season base rate: 60% season + 40% recent form
- [ ] Captures hot/cold streaks without overreacting to single outings

### Projection model — Layer 3: Park factors
- [ ] Source park factor data (Baseball Savant has park factors endpoint)
- [ ] Adjust per-start projection by park: Coors +25%, Oracle Park -10%, etc.
- [ ] Simple multiplier: projection × park_factor

### Model accuracy tracking
- [ ] Dashboard showing projected vs actual FPTS per start
- [ ] Mean absolute error (MAE) per pitcher and overall
- [ ] Directional accuracy (did we correctly predict above/below average?)
- [ ] Factor contribution analysis
- [ ] Uses locked projections in KV as ground truth

### Store actual FPTS in Upstash KV for accuracy analysis
- [ ] Store actual FPTS per pitcher per start date in KV alongside locked projections
- [ ] Key schema: `actual:{season}:{period}:{player-slug}:{date}` → float
- [ ] Required foundation for model accuracy dashboard

### espn.py full rewrite
- [ ] File has accumulated many patches and is ~900 lines
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

- Hitter optimizer
- Trade analyzer
- Push notifications when probable pitchers change
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
