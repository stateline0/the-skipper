# The Skipper — Knowledge Base

Permanent reference for API behavior, architecture decisions, and league settings.
Read this before writing code that touches any external API or core logic.

### Confidence ratings

Each section includes a confidence level and last-assessed date:
- **10/10** — Verified with hard evidence (API response vs website screenshot, side-by-side)
- **8-9/10** — Confirmed through repeated use in production, no contradictions observed
- **6-7/10** — Believed correct based on limited testing or documentation, should re-verify if building on it
- **≤5/10** — Assumed or inferred, needs investigation before relying on it

---

## ESPN Fantasy API

### Base URL & Auth
`Confidence: 9/10 · Last assessed: April 10, 2026`

```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{year}/segments/0/leagues/{league_id}
```

- Must use `lm-api-reads.fantasy.espn.com` — `fantasy.espn.com` redirects to HTML
- Requires `espn_s2` and `SWID` cookies for authenticated endpoints
- CloudFront blocks requests without a browser-like `User-Agent` header (`Mozilla/5.0`)
- Cannot be called directly from local machine — `espn_s2` and `SWID` are only available server-side via environment variables
- Always test ESPN-dependent changes against production URL after deploy (`vercel --prod`)

### Key views
`Confidence: 8/10 · Last assessed: April 10, 2026`

- `mRoster` — full roster with player entries, lineup slots, and stats
- `mTeam` — team metadata (name, id)
- `mSettings` — league settings
- `mMatchupScore` — matchup scoring data
- `kona_player_info` — player projections and ownership; requires `x-fantasy-filter` JSON header

### Scoring periods
`Confidence: 10/10 · Last assessed: April 10, 2026`

ESPN uses a daily scoring period counter starting from opening day, not matchup week numbers.

- 2026: March 25 = period 1
- Formula: `scoringPeriodId = (date - 2026-03-25).days + 1`
- Passing the wrong `scoringPeriodId` (e.g., the matchup period number instead of the daily counter) returns stale or wrong roster data

### Daily lineup behavior
`Confidence: 10/10 · Last assessed: April 10, 2026`

**Verified April 6–12, 2026: 98 data points across 7 days × 14 players, zero mismatches against ESPN website.**

- **`lineupSlotId` is per-day accurate.** Fetching `mRoster` with a specific `scoringPeriodId` returns the `lineupSlotId` for that exact day's lineup configuration.
- **Daily lineups are independent.** A player can be active (slot 13) on Monday, benched (slot 16) on Tuesday, and active again on Wednesday. Each day's `scoringPeriodId` fetch returns that day's specific slot assignment.
- **Future unset days default to current lineup.** When fetching a future matchup period where no daily lineups have been configured yet, all days return identical slot assignments matching the current lineup state.
- **Roster transactions are per-day accurate.** Dropped players disappear from roster entries on their drop date. Added players appear starting on their add date. (Confirmed: David Peterson dropped Apr 9 → "OFF ROSTER" from Apr 9 onward. Braxton Ashcraft added Apr 9 → appears from Apr 9 onward.)

### Lineup slot IDs
`Confidence: 10/10 · Last assessed: April 10, 2026`

| `lineupSlotId` | Meaning | Notes |
|---|---|---|
| 13 | P (active pitcher) | Used for ALL active pitchers — both SPs and RPs use this slot |
| 14 | SP | Appears in `eligibleSlots` but NOT used as a `lineupSlotId` in this league |
| 15 | RP | Appears in `eligibleSlots` but NOT used as a `lineupSlotId` in this league |
| 16 | Bench | Healthy player sitting out that specific day |
| 17 | IL | Injured list slot |

**Bench is a daily lineup decision, not a player attribute.** It has no impact on projections, start counting, or any Skipper logic. The only use of bench status is the visual strikethrough on actual FPTS for days a pitcher was benched (flagging missed points as a managerial mistake).

### Position eligibility (`eligibleSlots`)
`Confidence: 10/10 · Last assessed: April 10, 2026`

Determines whether a player is an SP, RP, or dual-eligible. This is a player attribute that does not change day to day.

- **SP-eligible**: `eligibleSlots` includes `14` (e.g., `[13, 14, 16, 17]`)
- **RP-only**: `eligibleSlots` includes `15` but NOT `14` (e.g., `[13, 15, 16, 17]`)
- **Dual-eligible (SP/RP)**: includes both `14` and `15` (e.g., `[13, 14, 15, 16, 17]`)
- Slots `16` (bench) and `17` (IL) appear in every player's `eligibleSlots` — they are universal slots, not position indicators

### Injury detection
`Confidence: 10/10 · Last assessed: April 10, 2026`

- **`player.injured` (boolean)** is the reliable signal for IL players. Confirmed: `true` for Pepiot and Kelly (both on IL), `false` for all other players including bench players.
- **`playerPoolEntry.injuryStatus` (string)** returns empty string `""` for ALL players on this roster — it is NOT a usable field for detecting injury status on rostered players.
- **Free agent `injuryStatus`** does work — returns values like `"FIFTEEN_DAY_DL"`, `"SIXTY_DAY_DL"`, `"DAY_TO_DAY"`, `"SUSPENSION"` for free agents. Uses a different data path (`player.injuryStatus` via flat structure) than roster players.

### Per-game stats
`Confidence: 9/10 · Last assessed: April 10, 2026`

- `statSplitTypeId=5` = per-game log entries
- `appliedTotal` = actual fantasy points earned that game
- Stats are keyed by `scoringPeriodId` — each day must be fetched individually
- Stat ID 57 = saves
- No single call returns full history — use parallel fetching via `ThreadPoolExecutor`
- Omitting `scoringPeriodId` returns only the 2 most recent stat entries

### Multiple views in one request
`Confidence: 9/10 · Last assessed: March 28, 2026`

Pass multiple `view` params as repeated tuples: `params=[("view", "mRoster"), ("view", "mTeam")]`

### Free agent filtering
`Confidence: 9/10 · Last assessed: April 9, 2026`

- `filterSlotIds: [14]` must be set in the `x-fantasy-filter` header before `limit`
- Without slot filter: `limit: 100` returns ~29 SPs out of 100 results (rest are other positions)
- With `filterSlotIds: [14]`: all 100 results are SP-eligible

### Player stats nesting
`Confidence: 8/10 · Last assessed: March 29, 2026`

- **Roster players**: stats nested at `entry.playerPoolEntry.player.stats`
- **Free agents**: flat structure via `p.get("player", {})`
- `appliedStatTotal` from `kona_player_info` returns empty/zero early in season — do not rely on it

### Transaction lag behavior
`Confidence: 8/10 · Last assessed: April 10, 2026`

Once any MLB game starts for the day, ESPN locks the current scoring period's roster. Roster transactions (adds/drops) made after lock are reflected in `scoringPeriodId + 1` (tomorrow's period). The Skipper re-fetches with tomorrow's period to pick up same-day transactions.

**Important:** The re-fetched data returns tomorrow's `lineupSlotId` values, not today's. This is correct API behavior — it accurately reflects tomorrow's lineup. Since bench status is irrelevant to The Skipper's projections, this does not affect functionality.

### Known limitations
`Confidence: 8/10 · Last assessed: April 10, 2026`

- `matchupPeriodDates` not returned for this league via any available view → all 22 period dates hardcoded in `api/config.py`
- Free agent actual FPTS only available if player was rostered at time of start — ESPN API limitation, no workaround
- ESPN caches roster data server-side — cache-busting params (`_` timestamp) have no effect on staleness
- ESPN Forecaster projections page: server-side fetch returns stale cached HTML — have user paste raw text directly

### PRO_TEAM_MAP (2026 verified)
`Confidence: 10/10 · Last assessed: March 28, 2026`

```
1=BAL, 2=BOS, 3=LAA, 4=CWS, 5=CLE, 6=DET, 7=KC, 8=MIL, 9=MIN, 10=NYY,
11=ATH, 12=SEA, 13=TEX, 14=TOR, 15=ATL, 16=CHC, 17=CIN, 18=HOU, 19=LAD,
20=WSH, 21=NYM, 22=PHI, 23=PIT, 24=STL, 25=SD, 26=SF, 27=COL, 28=MIA,
29=ARI, 30=TB, 31=FA, 32=FA
```

---

## MLB Stats API
`Confidence: 8/10 · Last assessed: April 10, 2026`

### Base URL & Auth

```
https://statsapi.mlb.com
```

- Free, no auth required
- Public API with no rate limiting observed

### Probable pitchers

- Endpoint: `/api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher`
- Confirms probable pitchers only 1–2 days in advance
- Secondary source (ESPN Scoreboard API) needed for days 3–7+

### Season stats

- Endpoint: `/api/v1/stats?stats=season&playerPool=all&group=pitching&season=YYYY&gameType=R&limit=1000`
- IP stored as string e.g. `"34.2"` meaning 34 innings + 2 outs = 34.667 actual innings
- Player names may use accented characters (e.g., "Edwin Díaz") — normalize with `strip_accents()` before matching against ESPN names

### Name matching
`Confidence: 9/10 · Last assessed: April 10, 2026`

- Full lowercase name matching (`full_name.strip().lower()`) — never last-name-only (causes collisions like Shane Smith / Shane Baz)
- Accent normalization via `unicodedata.normalize('NFD')` required for cross-source matching

### Team abbreviation quirks
`Confidence: 9/10 · Last assessed: April 9, 2026`

- Uses `AZ` for Arizona — normalize to `ARI` when matching against our schedule data

---

## ESPN Scoreboard API
`Confidence: 8/10 · Last assessed: April 10, 2026`

### Base URL

```
https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD
```

- Public, no auth required
- Returns probable starters up to 7 days out (further out than MLB Stats API)

### Team abbreviation quirks

- Uses `CHW` for White Sox — our app uses `CWS`
- Normalization map in `api/mlb.py` bridges mismatches

---

## Baseball Savant (Statcast)
`Confidence: 9/10 · Last assessed: April 11, 2026`

### CSV endpoints

Baseball Savant provides public CSV downloads via `&csv=true` parameter. No auth required.

**Expected Statistics (xwOBA, xBA, xSLG, xERA):**
https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=pitcher&year={year}&position=&team=&filterType=pa&min={min_pa}&csv=true

**Statcast Leaderboard (EV, barrel rate, sweet spot %):**
https://baseballsavant.mlb.com/leaderboard/statcast?type=pitcher&year={year}&position=&team=&min={min_bbe}&csv=true

**Pitch Arsenal Stats (whiff %, run value per pitch type):**
https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?type=pitcher&pitchType=&year={year}&team=&min={min_pa}&csv=true

### CSV format quirks

- CSV begins with a BOM character (`\ufeff`) — strip before parsing
- Player name is a single combined column: `"last_name, first_name"` with values like `"Alcantara, Sandy"`
- Parse by splitting on comma: `"Last, First"` → `"first last"` lowercase
- Accent normalization required for cross-source matching (same `strip_accents()` as MLB Stats API)

### Data availability (verified April 11, 2026)

- Expected stats: 250 pitchers (min 25 PA)
- Statcast leaderboard: 144 pitchers (min 25 BBE)
- Pitch arsenal: 44 pitchers (min 25 PA, one row per pitch type)
- Data available from 2015 onward
- Updates daily during the season

### Key metrics for projection model

| Metric | Source | What it measures | Why it matters |
|---|---|---|---|
| xwOBA | Expected stats | Expected weighted on-base average allowed | Single best predictor of pitcher quality — removes luck and defense |
| xERA | Expected stats | Expected ERA from quality of contact | More stable than actual ERA, especially early season |
| woba_diff | Expected stats | xwOBA minus actual wOBA | Positive = unlucky pitcher (due for improvement), negative = lucky |
| Barrel % | Statcast | Rate of barrels (optimal EV + launch angle) allowed | Hard contact quality — lower = better pitcher |
| EV50 | Statcast | Avg exit velocity of softest 50% of batted balls | Measures weak contact generation — lower = better |
| Whiff % | Arsenal | Swinging strike rate per pitch type | Stuff quality — higher = better |
| CSW % | Arsenal | Called strikes + whiffs rate | Overall pitch deception — higher = better |

### Limitations

- Arsenal data has fewer qualifying pitchers early in season (need enough PAs per pitch type)
- Does NOT provide xFIP or SIERA (those are FanGraphs proprietary) — but xwOBA and xERA are equally or more predictive
- Pitch-level data (via Statcast Search) is available but returns up to 25,000 rows per query — too heavy for real-time use in a serverless function

---

Upstash KV (Redis)
Confidence: 9/10 · Last assessed: April 11, 2026
Connection

Client: upstash-redis Python library
Credentials: KV_REST_API_URL and KV_REST_API_TOKEN environment variables
Vercel removed native KV — Upstash for Redis is the direct replacement

Key schemas
Locked projections (write-once, permanent):
proj:{season}:{period}:{player-slug}:{date} → float
Example: proj:2026:3:garrett-crochet:2026-04-07 → 17.6
Data caching (TTL-based):
cache:savant:{year}      → JSON dict of expected stats by pitcher name
cache:mlb-stats:{year}   → JSON dict of season pitching stats by pitcher name  
cache:daily:{date}       → JSON dict {fpts, saves, bench, my_team} for all league pitchers
Cache TTL strategy
Key patternTTLRationalecache:savant:2025PermanentLast year's data is finalcache:savant:202624 hoursUpdates daily during seasoncache:mlb-stats:2025PermanentLast year's data is finalcache:mlb-stats:202624 hoursUpdates daily during seasoncache:daily:2026-04-06PermanentCompleted day's stats never changecache:daily:{today}Never cachedGames may be in progressproj:*PermanentWrite-once, never overwritten (NX flag)
Performance impact

Uncached request: ~4.5s (fetches Savant, MLB Stats, and daily FPTS from external APIs)
Fully cached request: ~2.1s (only fetches today's data and roster from ESPN)
56% reduction in response time

Write-once pattern (locked projections)

NX flag on set ensures locked values are never overwritten — atomic, safe for concurrent writes
Once a projection is locked at game time, it is frozen permanently

Storage settings

Eviction is OFF — locked projections and daily caches are stored permanently
Free tier: 500,000 commands/month, 256MB storage
Data browser: Vercel → Storage → the-skipper-kv → Open in Upstash

Helper functions (api/kv.py)

get_locked_projection() / set_locked_projection() — per-start projection locks
get_all_locked_projections() — fetch all locks for a period (prefix query)
cache_get(key) → parsed JSON dict or None
cache_set(key, data, ttl_seconds=None) → store JSON with optional TTL
---

## League Settings (Good Season Imanagas)
`Confidence: 10/10 · Last assessed: March 27, 2026`

### Scoring formula

| Stat | Points |
|---|---|
| Innings Pitched (IP) | +3 |
| Strikeouts (K) | +1 |
| Hits Allowed (H) | -1 |
| Earned Runs (ER) | -2 |
| Walks Issued (BB) | -1 |
| Hit Batsmen (HB) | -1 |
| Wins (W) | +5 |
| Losses (L) | -5 |
| Saves (SV) | +5 |

### Starts limits

- Standard: 12 starts per 7-day matchup period
- Period 1 (Mar 25–Apr 5): 21 starts (12-day period)
- Period 15 (Jul 6–19): 19 starts (14-day period)
- Limits scale proportionally with period length

### League identifiers

- League ID: 77651433
- Team ID: 6 (Good Season Imanagas)
- Season: 2026

---

Projection Model (Savant Hybrid)
Confidence: 8/10 · Last assessed: April 11, 2026
Approach
Hybrid model combining Savant expected stats (luck-adjusted) with MLB Stats API counting stats (skill-based), blended across 2025 and 2026 seasons, adjusted for opponent quality.
Per-start component sources
ComponentSourceWhyIP per startMLB Stats APISkill-based — actual IP/game is a reliable talent indicatorK per startMLB Stats APIHighly skill-based — strikeout rate is one of the most stable pitcher statsBB per startMLB Stats APIHighly skill-based — walk rate stabilizes quicklyHBP per startMLB Stats APISkill-basedH per startSavant xBALuck-influenced — actual hits depend on BABIP which has high variance. xBA × batters_faced removes thisER per startSavant xERALuck-influenced — actual ERA depends on sequencing and BABIP. xERA × (IP/9) removes thisW per startMLB Stats API × 0.5Very noisy — wins depend on run support and bullpen. Discounted 50%L per startMLB Stats API × 0.5Very noisy — same reasoning as winsSV per startMLB Stats APISkill-based for closers
Fallback behavior
When Savant data is unavailable for a pitcher (below minimum PA threshold or not in Savant data):

Falls back to pure counting-stat model (H and ER from actual stats, W/L not discounted)
Log shows [stats] vs [savant] for each pitcher to indicate which model was used
RPs always use counting-stat model (Savant data less relevant for relief appearances)

Blend weight (year-over-year)

Ramps from 100% last year to 100% this year as pitcher accumulates innings in 2026
SPs: full trust at 50 IP (~9 starts, ~6 weeks)
RPs: full trust at 20 IP (~20 appearances, ~6 weeks)
Formula: this_year_weight = min(1.0, ip_2026 / threshold)
Both years' stats get Savant adjustments independently before blending

Minimum sample thresholds

SPs: 3 starts minimum before trusting per-game averages
RPs: 5 appearances minimum
Below threshold: falls back to other year's data, or 0.0 if neither year qualifies

Opponent quality adjustment

Team wOBA factors from MLB Stats API, normalized to league average
Applied per-start: each start's projection scaled by opponent's factor
10-game minimum threshold before trusting team wOBA
RPs excluded from matchup adjustment

Projection locking

At game time (today or past), per-start projections locked into Upstash KV
Locked projections never recalculated — frozen at time of the game
Enables future model accuracy analysis: actual - projected per start

Model architecture roadmap

Layer 1 ✅ COMPLETE — Savant xERA/xBA hybrid base rate
Layer 2 PENDING — Recent form weighting (rolling last 3-4 starts)
Layer 3 PENDING — Park factors
Layer 4 PENDING — Platoon splits
Layer 5 PENDING — Rest & workload
Accuracy tracking PENDING — Compare locked projections vs actual FPTS

---

## Architecture Decisions
`Confidence: 9/10 · Last assessed: April 10, 2026`

### Why bench status is ignored for projections

ESPN Fantasy Baseball uses daily lineups — a player can be active Monday, benched Tuesday, and active Wednesday. Being on the bench for a given day is a routine lineup management decision, not an indication of anything about the player's health or ability. The Skipper treats all rostered pitchers identically for projection and start-counting purposes. The only bench-related display is a strikethrough on actual FPTS for days a pitcher was benched, highlighting potential missed points.

### Why we use `eligibleSlots` for position, not `lineupSlotId`

`lineupSlotId` changes daily based on lineup decisions. `eligibleSlots` is a stable player attribute that correctly identifies SP vs RP vs dual-eligible. Rule: `14 in eligibleSlots` → SP-eligible. `15 in eligibleSlots and 14 not in eligibleSlots` → RP-only.

### Why we use `player.injured` for IL detection, not `injuryStatus`

The string field `playerPoolEntry.injuryStatus` returns empty `""` for all rostered players in this league. The boolean `player.injured` reliably returns `true` for IL players and `false` for all others. This was verified across 7 days of data.

### Why `vercel dev` cannot test Python routes

Vercel CLI v50+ does not serve Python serverless functions locally. All Python API testing must be done against production URL after `vercel --prod` deploy.

### Why matchup period dates are hardcoded

ESPN's API does not return `matchupPeriodDates` for this league via any available view. All 22 matchup period date ranges are hardcoded in `api/config.py`.

### Session storage for cross-page state

`sessionStorage` is used to persist data across page navigation (My Team → Free Agents → back). A `CACHE_VERSION` constant ensures stale cache shapes are detected and auto-refreshed when the API response format changes.

---

## Development Workflow
`Confidence: 10/10 · Last assessed: April 10, 2026`

### Local setup

```bash
cd ~/Developer/the-skipper
git checkout main
git pull origin main
vercel dev   # frontend only — Python routes require production
```

### Deploy sequence

```
file save → git add → git commit → vercel --prod
```

Then test at `https://the-skipper-iota.vercel.app`

### Git workflow

- Branch protection on main — all changes via PRs
- Branch naming: `fix/description`, `feature/description`
- Commit prefixes: `fix:`, `feat:`, `chore:`, `docs:`
- Merge: `gh pr create` + `gh pr merge --squash --delete-branch`
- After merge: `git checkout main && git pull origin main`
- If local main diverges: `git reset --hard origin/main` (not `git merge`)

### Environment variables

All set in both `.env.local` (local) and Vercel dashboard (production):

| Variable | Purpose |
|---|---|
| `APP_USERNAME` / `APP_PASSWORD` | Login credentials |
| `NEXTAUTH_SECRET` | JWT encryption key |
| `NEXTAUTH_URL` | `https://the-skipper-iota.vercel.app` |
| `ESPN_LEAGUE_ID` | Fantasy league ID (77651433) |
| `ESPN_SEASON` | `2026` |
| `ESPN_S2` / `ESPN_SWID` | ESPN auth cookies |
| `ESPN_TEAM_ID` | Your team number (6) |
| `ESPN_STARTS_LIMIT` | Default weekly starts limit |
| `ANTHROPIC_API_KEY` | Claude API key |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` | Upstash Redis credentials |
