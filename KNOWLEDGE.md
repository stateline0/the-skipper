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
`Confidence: 10/10 · Last assessed: April 25, 2026`

Once any MLB game starts for the active scoring period, ESPN locks that period's roster. Roster transactions (adds/drops) made after lock are reflected in `scoringPeriodId + 1` (the next period). The Skipper re-fetches with the next period to pick up same-day transactions. The trigger for this branch is `period_has_started(schedule, current_week)` returning true — i.e. any game on the date corresponding to the period ESPN just returned is `in_progress` or `final`.

**Re-fetched data returns the next period's `lineupSlotId` values, not the locked period's.** Correct API behavior. Bench status is irrelevant to The Skipper's projections, so this does not affect functionality.

**Trigger keys off the returned period, not UTC today (PR #114, session 27).** Earlier code used `today_has_started(schedule)` which checked games on UTC today. ESPN's scoring-period boundary tracks ET, not UTC, so any time UTC had crossed midnight while ET hadn't (typical evening usage in CT/PT), the old check returned False even when the active period was very much locked. Concrete repro: a 7–9pm CT roster add on April 25 fired the backend request after UTC midnight (April 26 UTC); `today_has_started` checked April 26 games (none started), the trigger silently skipped, and the locked Apr 25 roster stayed as `roster_entries`. Keying off `current_week` (the period ESPN itself returned) removes the timezone dependency entirely — the question "is the period ESPN just gave us a locked one?" has the same answer regardless of where the user's wall clock has rolled to.

**Derived structures are rebuilt after the refetch (PR #113, session 27).** When the lag-fix branch fires, `all_player_names`, `roster_team_map`, and `starts_map` are all recomputed from the refreshed `roster_entries` — which now reflects same-day pickups. Earlier behavior (session 18 PR #73 → session 27 PR #113) was to update only `roster_entries` and leave the derived structures stale, with the consequence that newly-added pitchers fell through `starts_map.get(name, {})` to the empty default and rendered with `starts=0`, no startDates, all-gray cells. PR #113 fixed the rebuild; PR #114 fixed the trigger that was causing PR #113 to never fire in evening usage.

**The two bugs interacted invisibly.** Either bug alone could mask the other. Without PR #113's rebuild, even a correctly-firing lag-fix branch would have produced the empty-row symptom. Without PR #114's trigger fix, PR #113's rebuild would never run for evening adds and the user would land in the dropped-player branch with slot `EX` instead. The Montero case in session 27 surfaced both because verification of PR #113 happened to fall in the evening, exposing the trigger bug. Lesson recorded in the post-hoc adjustment architecture decision below: verification at the user-action layer surfaces the next bug class; pre-deploy theorycraft cannot.

**Verify post-deploy by:** adding a pitcher mid-day during a locked period (or in the user's evening once UTC has rolled over). Confirm the pitcher appears in the SP rows (not the EX/dropped section), with green ✓ on upcoming starts and a per-start projection in the cell. Vercel logs show `[espn.py] Games in progress — fetching roster at scoringPeriodId={N}` and `[espn.py] Lag-fix rebuild: starts_map refreshed for {N} players; new names: [...]` when the branch fires.

### Known limitations
`Confidence: 8/10 · Last assessed: April 10, 2026`

- `matchupPeriodDates` not returned for this league via any available view → all 22 period dates hardcoded in `api/config.py`
- Free agent actual FPTS only available if player was rostered at time of start — ESPN API limitation, no workaround
- ESPN caches roster data server-side — cache-busting params (`_` timestamp) have no effect on staleness

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

### Team stats — date-range splits
`Confidence: 8/10 · Last assessed: April 18, 2026`

- Endpoint: `/api/v1/teams/stats?stats=byDateRange&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&group=hitting&season=YYYY&sportId=1`
- Same response shape as `stats=season` — `splits[].stat.{hits, doubles, triples, homeRuns, baseOnBalls, hitByPitch, atBats, sacFlies, plateAppearances, gamesPlayed}`
- Used by Layer 7 recent form (last-14-day team wOBA) blended against season factors
- Lower `min_games` threshold appropriate for short windows (3 vs 10 for full season)
- `team.abbreviation` occasionally differs from our canonical abbrev (e.g. `AZ` → `ARI`) — same normalization map as probable pitchers applies

### Name matching
`Confidence: 10/10 · Last assessed: April 19, 2026`

- Full lowercase name matching (`full_name.strip().lower()`) — never last-name-only (causes collisions like Shane Smith / Shane Baz)
- Accent normalization via `unicodedata.normalize('NFD')` required for cross-source matching
- **Slug form (for KV keys) must also strip accents.** The `_to_slug()` helper applies `_strip_accents()` before the `re.sub(r"[^a-z0-9]+", "-", …)` step — otherwise accented names like "Luis García" or "José Berríos" generate different slugs across MLB Stats API (accents preserved in some responses), ESPN Fantasy (often stripped), and ESPN Forecaster (varies). This bit us in session 24 — ESPN-locked keys for accented pitchers didn't join to Skipper-locked keys until the strip was added to the slug pipeline.

### Game logs (per-game stats)
`Confidence: 10/10 · Last assessed: April 19, 2026`

- ⚠️ **Bulk endpoint DOES NOT WORK.** `/api/v1/stats?stats=gameLog&playerPool=all&group=pitching&season=YYYY` silently returns an empty `splits` array — no error, no warning, no 4xx. We assumed it worked through most of session 13–22 because an earlier ad-hoc test happened to succeed in a different season window. It cost a full session of diagnostic work to pin down (session 24). Do not use this URL shape.
- ✅ **Correct endpoint: per-player.** `/api/v1/people/{person_id}/stats?stats=gameLog&group=pitching&season=YYYY&gameType=R` returns the full game log for a single pitcher. Parallelize over a list of pitcher IDs using `ThreadPoolExecutor` (12 workers works well — MLB Stats API tolerates it, `fetch_game_logs_for_players()` is the reference implementation).
- Each split contains: `date`, `stat.inningsPitched`, `stat.hits`, `stat.earnedRuns`, `stat.strikeOuts`, `stat.baseOnBalls`, `stat.hitBatsmen`, `stat.wins`, `stat.losses`, `stat.saves`, `stat.gamesStarted`. `player.fullName` is NOT on the split — you already know whose log you're fetching.
- `gamesStarted` field distinguishes actual starts (gs=1) from relief appearances (gs=0) — still filter on this.
- Used by Layer 2 (recent form weighting) to compute rolling weighted average of last 4 starts, and by `actual-all:` cron locking for accuracy dashboard.
- Cached with 24hr TTL (`cache:game-logs:YYYY`) — cache key is per-season, value is merged across all pitchers fetched.
- **Silent-failure defense:** any new bulk-style fetch against MLB Stats API should log the returned `len(splits)` and compare against an expected floor (e.g., ≥100 for all-pitcher pulls in-season). If the shape is "200 OK with empty splits," that's the failure mode.

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

## ESPN Forecaster (HTML scraping)
`Confidence: 9/10 · Last assessed: April 18, 2026`

### Source URL

```
https://www.espn.com/fantasy/baseball/story/_/id/31165100/fantasy-baseball-forecaster-probable-starting-pitcher-projections-matchups-daily-weekly-leagues
```

- Public article, no auth required
- Requires a browser-like `User-Agent` header (`Mozilla/5.0 … Chrome/…`) — ESPN returns HTML-but-stale content to generic User-Agents
- This is the **only** URL that works for server-side fetches — the Fantasy app page (`fantasy.espn.com/baseball/forecaster`) returns a JS-rendered shell that never resolves server-side
- Scraper lives in `api/forecaster.py`; diagnostic endpoint at `GET /api/forecaster`

### Render model

One HTML `<table class="inline-table">` with:
- One `<tr>` per MLB team (30 teams, interleaved with empty spacer `<tr>`s)
- Six `<td>` columns: team logo, date, opp, pitcher, throws-hand, FPTS
- Each non-logo cell holds **10 `<br>`-separated values**, one per date in a rolling 10-day window starting "today" (ESPN time, US Pacific)

Alignment is by index within the `<br>`-split lists — `date_tokens[i]`, `opp_tokens[i]`, `pitcher_tokens[i]`, `throws_tokens[i]`, `fpts_tokens[i]` all refer to the same game.

### Cell parsing gotchas

- Some cells wrap their `<br>`-separated content in a single child `<div>` (e.g. `<td><div>val<br>val<br>…</div></td>`). `_split_br()` detects this and dives into the wrapper before splitting.
- Pitcher cells contain `<a>` tags per start; OFF days have no `<a>` in that slot. `_split_pitcher_cell()` returns `(name, player_id)` tuples so OFF days come out as `("", None)`.
- Date tokens look like `"Sat, 4/18"` — parsed with regex `(\d+)/(\d+)` and combined with current UTC year to produce ISO dates.

### Placeholder value detection

ESPN uses **exactly `1.0`** as a placeholder for far-future starts they haven't firmed up yet (typically dates ~7+ days out). Flag these with `is_placeholder=True` so downstream can exclude them from accuracy comparisons.

**MUST be an exact-equality check (`fpts == 1.0`), NOT a threshold (`fpts <= 1.0`).** Coors Field pitchers legitimately project negative in rough matchups (e.g. `-3.2` FPTS). A threshold check would wrongly flag those as placeholders.

### Team abbreviation quirks (logo filenames only)

ESPN logo files use slugs that don't always match our canonical abbreviations. `LOGO_TO_TEAM_OVERRIDES` in `api/forecaster.py` normalizes:

| Logo filename | Canonical abbrev | Note |
|---|---|---|
| `ath.png` | `OAK` | Athletics |
| `was.png` | `WSH` | **Nationals — same team, different slug than ESPN's opp column and scoreboard which both use `WSH`. Caught post-ship in PR #94 when the Forecaster scraper was returning `WAS` entries that didn't join against scheduled opponents.** |
| `chw.png` | `CWS` | White Sox |
| `az.png` | `ARI` | Diamondbacks |

The opp column uses the normal abbreviations directly (no mapping needed) — the mismatch is purely on the logo-filename side.

### Home/away detection

Opp column prefixes away games with `@` (e.g. `@TOR` means the team is playing at Toronto). Scraper strips the `@` and sets `opp_is_home = not opp_tok.startswith("@")`.

### Player ID extraction

Pitcher `<a>` href format: `/mlb/player/_/id/{player_id}/{slug}` (e.g. `/mlb/player/_/id/39910/zac-gallen`). Regex `/player/_/id/(\d+)/` extracts the numeric ID. Same ID space as ESPN Fantasy API — safe to join on.

### Output entry shape

```python
{
  "date":           "2026-04-18",
  "team":           "ARI",
  "opp":            "TOR",
  "opp_is_home":    True,
  "player_id":      39910,
  "pitcher":        "Zac Gallen",
  "throws":         "R",
  "fpts":           8.4,
  "is_placeholder": False
}
```

### Failure modes

- Table not found → returns `{"entries": [], "date_range": None}` (no crash)
- HTTP non-200 → returns `{"error": "HTTP {code}"}`
- Network/exception → returns `{"error": "fetch failed: {type}: {msg}"}`
- Per-row parse failures (bad date token, non-numeric FPTS) skip silently — one bad row doesn't kill the whole scrape

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

## Open-Meteo (Weather)
`Confidence: 8/10 · Last assessed: April 18, 2026`

### Base URL & Auth

```
https://api.open-meteo.com/v1/forecast
```

- Free, no auth, no API key
- Hourly forecast up to 16 days out
- Historical endpoint also available but not used — projections only run forward
- Requires a browser-like `User-Agent` header (`Mozilla/5.0`) to avoid occasional 403s

### Request shape

Query params used by `api/weather.py`:
- `latitude`, `longitude` — home plate coordinates per park
- `hourly=temperature_2m,wind_speed_10m,wind_direction_10m`
- `temperature_unit=fahrenheit`
- `wind_speed_unit=mph`
- `timezone=auto` — returns hourly timestamps in the park's local time
- `start_date`, `end_date` — single day (same value for both)

### Response shape

`hourly.time[]` is a list of ISO strings like `"2026-04-18T19:00"` — local to the park because `timezone=auto`. `temperature_2m[]`, `wind_speed_10m[]`, `wind_direction_10m[]` are parallel arrays by index.

Game-hour selection: pick `T19:00` as the canonical MLB game slot, fall back to `T13:00` (day games), then the first available hour.

### Park coordinates & dome parks

30-team `PARK_COORDS` dict in `api/weather.py` maps team abbrev → `(lat, lng)` tuples. Accuracy within ±0.01° is fine — Open-Meteo resolution is ~1km.

`DOME_PARKS = {TB, TOR, MIL, ARI, HOU, MIA, SEA, TEX}` — includes permanent dome (TB) plus retractables whose roof state isn't reliably knowable. Dome parks skip the API call entirely and always return `factor=1.0, source="dome"`.

### Temperature → run environment factor

Baseline 70°F = 1.0 neutral. Formula matches park-factor dampening pattern:

```
raw      = 1 + (temp_f - 70) / 1000      # ~1% per 10°F off baseline
dampened = 1 + (raw - 1) * 0.5           # only H/ER are temp-sensitive
clamped  = clip(dampened, 0.95, 1.05)    # ±5% cap
```

Examples: 40°F → 0.985, 70°F → 1.000, 95°F → 1.0125.

Wind direction modeling is **phase 3 / not yet implemented** — requires `PARK_OUTFIELD_BEARING` per park to compute the out-to-outfield wind component. Phase 1 (this fetcher) returns wind speed and direction in the diagnostic payload but doesn't fold them into the factor.

### Caching

`cache:weather:{park_abbrev}:{date_str}` → full factor dict, 3hr TTL. Shorter than other caches because forecasts update throughout the day as game time approaches.

### Failure mode

`get_weather_factor()` **always returns a dict with `factor` set** — unknown park, Open-Meteo error, network failure, malformed response all fall through to `factor=1.0, source="default"`. The caller never needs to guard against weather breaking the projection pipeline.

### Diagnostic endpoint

`GET /api/weather?park=NYY&date=2026-04-18` returns the full factor dict including `temp_f`, `wind_mph`, `wind_dir_deg`, `source`. Intended for production verification before wiring weather into projections — not part of the production request path.

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
cache:savant:{year}             → JSON dict of expected stats by pitcher name
cache:mlb-stats:{year}          → JSON dict of season pitching stats by pitcher name (force-refreshed at start of every cron run since session 25)
cache:game-logs:{year}          → JSON dict of per-game pitching stats by pitcher name (force-refreshed at start of every cron run since session 25)
cache:team-woba:{year}          → JSON dict of BLENDED team wOBA factors (65% season + 35% last-14-day)
cache:team-win-data:{year}      → JSON dict of team RS/RA/ERA for Pythagorean model
cache:weather:{park}:{date}     → JSON dict of weather factor + temp/wind (3hr TTL)
cache:daily:{date}              → JSON dict {fpts, saves, bench, my_team} for all league pitchers
cache:cron-summary:{date}       → JSON dict — full result of the day's cron run (60-day TTL). Written by handler regardless of MLB/ESPN lock outcome. Includes gameLogStats with per-outcome counters (with_data/empty/http_errors/exceptions). Use this as the post-hoc debugger when Vercel's 1hr log retention has rolled past.
Cache TTL strategy
Key patternTTLRationalecache:savant:2025PermanentLast year's data is finalcache:savant:202624 hoursUpdates daily during seasoncache:mlb-stats:2025PermanentLast year's data is finalcache:mlb-stats:202624 hoursUpdates daily during seasoncache:game-logs:202624 hoursNew games happen dailycache:team-woba:202624 hoursStores blended season+recent factor; recent window shifts dailycache:team-win-data:202624 hoursPythagorean model data updates dailycache:weather:{park}:{date}3 hoursForecasts update throughout day as game time approachescache:daily:2026-04-06PermanentCompleted day's stats never changecache:daily:{today}Never cachedGames may be in progressproj:*PermanentWrite-once, never overwritten (NX flag)proj2:*PermanentV2 rich projection locks (roster pitchers)proj2all:*PermanentV2 projection locks (all MLB starters, from cron)actual-all:*PermanentAll-MLB actuals from game logs (from cron)
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
Confidence: 9/10 · Last assessed: April 11, 2026
Approach
Hybrid model combining Savant expected stats (luck-adjusted) with MLB Stats API counting stats (skill-based), blended across 2025 and 2026 seasons, adjusted for opponent quality, recent form, and park factors.
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
`Confidence: 8/10 · Last assessed: April 18, 2026`

Team wOBA factors from MLB Stats API, normalized to league average, blended across season + recent form.

- **Season component** — `get_team_woba(season)` → full-season splits via `stats=season`, 10-game minimum
- **Recent component** — `get_team_woba_recent(season, days=14)` → last-14-day splits via `stats=byDateRange`, 3-game minimum (lower bar for short window)
- **Blend** — `get_team_woba_blended(season, recent_days=14, recent_weight=0.35)`:
  - 65% season + 35% last 14 days
  - `ThreadPoolExecutor(max_workers=2)` fetches both in parallel, then blends per team
  - Pure helper `_compute_team_woba_factors(splits, min_games, label)` computes raw factors from either split type
- **Fallback chain** — missing recent factor for a team → use season-only for that team. Full recent-fetch failure → return season dict unchanged. Season failure → return `{}` and consumers fall through to neutral 1.0 via `.get(abbrev, 1.0)`.
- **Cached** under `cache:team-woba:{year}` with 24hr TTL — the cache stores the blended dict, not the raw season dict.
- Applied per-start: each start's projection scaled by opponent's blended factor.
- RPs excluded from matchup adjustment.

Recent form weighting (Layer 2)
`Confidence: 8/10 · Last assessed: April 11, 2026`

Per-game pitching stats fetched via MLB Stats API (`stats=gameLog&playerPool=all`)
Single API call returns all pitchers' game logs for the season
`compute_recent_form_fpts()` filters to starts (gs=1), takes last 4
Weights: 10% oldest → 20% → 30% → 40% most recent
Blended with season base rate: 60% season + 40% recent form
Only applied when pitcher has 4+ starts this year — prevents overreaction to small samples
RPs excluded (not enough starts to weight meaningfully)
Cached with 24hr TTL (`cache:game-logs:YYYY`)

Park factors (Layer 3)
`Confidence: 8/10 · Last assessed: April 11, 2026`

3-year rolling Runs factors from Baseball Savant, hardcoded in `PARK_FACTORS` dict (30 teams)
100 = league average, >100 = hitter-friendly (bad for pitchers), <100 = pitcher-friendly
Dampened 50% before applying — only H/ER are park-dependent, K/IP are not
Formula: `dampened = 1.0 + (raw/100 - 1.0) * 0.5`
Example: Coors (115) → 1.075 (7.5% worse), Oracle Park (92) → 0.96 (4% better)
Applied per-start: `fpts × wOBA_factor × park_factor`
Park determined by home team: home start = pitcher's team park, away start = opponent's park
`is_home` field in startDates enables correct park identification
Savant park factors page is JS-rendered (no CSV endpoint) — hardcoding is standard approach

Projection locking

At game time (today or past), per-start projections locked into Upstash KV
Locked projections never recalculated — frozen at time of the game
Enables future model accuracy analysis: actual - projected per start

Projection breakdown tooltip

`ProjectionTooltip` component in `components/ProjectionTooltip.tsx`
Two modes: total (Proj FPTS column) and per-start (schedule grid cells)
Total mode shows: season base, model type, year blend, recent form, per-start adjustments, total
Start mode shows: base rate, lineup wOBA factor, park factor, projected
Uses `position: fixed` to escape `overflow: auto` table containers
`projectionDetails` and `faProjectionDetails` added to API response from `get_projected_fpts()`

Accuracy tracking dashboard
`Confidence: 9/10 · Last assessed: April 12, 2026`

`api/accuracy.py` endpoint reads `proj2:` keys and `cache:daily:` actual_stats, matches by player slug.
`pages/accuracy.tsx` displays summary tiles, per-stat MAE bar chart, and expandable per-start comparisons.
Period selector allows viewing any matchup period.

Matching logic: proj2 keys use slugs, actual_stats uses full names. Matching done by slugifying actual names.

Limitations:
- Only league-rostered pitchers have actual stats (free agents not in `mRoster` data)
- V2 projections only exist from session 14 onward — older starts only have v1 floats
- Data accumulates over time — dashboard becomes more useful as more starts complete

Summary metrics computed:
- MAE (mean absolute error) — average |projected - actual| across all matched starts
- Directional accuracy — % of starts where we correctly predicted above/below average
- Per-stat MAE — average error for each individual stat (IP, K, H, BB, ER, HBP, W, L, SV)
- Per-stat bias — average signed error (positive = over-projecting, negative = under-projecting)

Model architecture roadmap

Layer 1 ✅ COMPLETE — Savant xERA/xBA hybrid base rate
Layer 2 ✅ COMPLETE — Recent form weighting for pitcher (rolling last 4 starts)
Layer 3 ✅ COMPLETE — Park factors (dampened 50%)
Layer 4 ✅ COMPLETE — Vegas/Pythagorean win probability for W/L
Layer 5 PENDING — Platoon splits
Layer 6 PENDING — Rest & workload
Layer 7 ✅ COMPLETE — Opponent lineup quality adjustment (season + last-14-day blend), opponent starter xERA
Layer 8 🟡 IN PROGRESS — Weather impact (fetcher + diagnostic endpoint shipped PR #85; wiring into `get_projected_fpts()` and wind direction modeling deferred to phase 2/3)
Accuracy tracking ✅ COMPLETE — Factor contribution analysis (PR #74)

Win probability model (Layer 4)
`Confidence: 8/10 · Last assessed: April 12, 2026`

Three-tier fallback chain for per-start W/L scaling:
1. **Vegas moneyline** — DraftKings odds from ESPN scoreboard API (already called for probables). American odds → implied probability, normalized to remove vig. Available ~12-24hrs before game.
2. **Pythagorean model** — `get_team_win_data()` fetches team RS/RA and ERA via MLB Stats API (2 parallel calls: hitting + pitching). Pythagorean exponent 1.83. Log5 for head-to-head. Pitcher xERA adjustment capped 0.7–1.4.
3. **Default 0.5** — coin flip, same as old flat discount.

Formula per start:
- `base_no_wl` = IP×3 + K×1 + H×(-1) + BB×(-1) + ER×(-2) + HBP×(-1) + SV×5
- `w_contrib` = raw_w_rate × win_prob × STARTER_WIN_SHARE(0.57) × 5
- `l_contrib` = raw_l_rate × (1 - win_prob) × STARTER_WIN_SHARE(0.57) × (-5)
- `start_proj` = (base_no_wl + w_contrib + l_contrib) × woba_factor × park_factor

`winProb` and `wpSource` stored in v2 locked projections for accuracy tracking.
Opponent starter xERA threaded from ESPN scoreboard probables → schedule → projection model (PR #77).

Factor contribution analysis
`Confidence: 9/10 · Last assessed: April 12, 2026`

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

### Public API routes (NextAuth middleware exemption)
`Confidence: 10/10 · Last assessed: April 18, 2026`

Every non-static route in the app is protected by NextAuth's `withAuth` middleware (`middleware.ts`) by default — unauthenticated requests get a 307 redirect to `/login?callbackUrl=…`. A small allow-list of API routes is exempted via the matcher's negative-lookahead pattern so they can be hit without a user session.

**Exempted prefixes (as of April 18, 2026):**

| Prefix | Why it's public |
|---|---|
| `_next/static`, `_next/image`, `favicon.ico` | Next.js static assets; no sensitive data |
| `api/auth` | NextAuth's own handler — must be reachable to perform login itself |
| `api/cron` | Vercel Cron triggers; no session available, auth'd via `CRON_SECRET` header check inside the handler |
| `api/forecaster` | Public ESPN Forecaster scraper; no user-specific or sensitive data, safe to serve anonymously |
| `api/forecaster_probe` | Diagnostic/debug variant of the above |
| `api/espn_proj` | Read-only ESPN projections diagnostic endpoint |

**Matcher pattern (`middleware.ts`):**

```ts
matcher: [
  '/((?!_next/static|_next/image|favicon.ico|api/auth|api/cron|api/forecaster|api/forecaster_probe|api/espn_proj).*)',
]
```

Everything NOT in the negative-lookahead list is protected. To add a new public route, append its prefix to this list.

**How to tell if a 307 redirect is NextAuth vs Vercel SSO:**
- Redirect `Location` starts with `/login?callbackUrl=…` → it's our NextAuth middleware (fix in `middleware.ts`)
- Redirect `Location` starts with `https://vercel.com/sso-api?…` → it's Vercel Deployment Protection (fix in Vercel dashboard → Deployment Protection, or use a custom domain which is exempt from Standard Protection)

**Endpoints requiring auth-by-handler rather than middleware exemption:** routes that need a session BUT also need to skip the middleware's `/login` redirect (none today — all protected routes happily use the default middleware behavior).

### Silent API failures: defensive pattern
`Confidence: 10/10 · Last assessed: April 25, 2026`

Some upstream APIs return 200 OK with an empty payload instead of erroring when a request shape they don't support is sent. The MLB Stats API bulk game-logs endpoint is the canonical example (see "Game logs (per-game stats)" above). These are the worst kind of failures because they look indistinguishable from "no data exists" — production runs green, KV gets written with zero entries, and the bug compounds quietly until something downstream notices the gap.

**Defenses we now use, after sessions 24 and 25's diagnostic burns:**

1. **Floor checks on bulk fetches.** Any call expected to return ≥ N rows in normal operation should log `len(result)` and warn (or fail loudly in cron) when below floor. E.g., an all-pitcher game-log pull in mid-season should never legitimately return 0 splits.
2. **Per-outcome counters with granularity.** Single "errors" counters obscure silent-failure modes. `fetch_game_logs` (post-PR #108) splits each per-player call into `with_data` / `empty` / `http_errors` / `exceptions` because the 200-OK-but-empty case is the silent-failure mode and looks identical to "errors=0" otherwise. A spike in `empty` is the diagnostic signature of an upstream regression.
3. **Per-write counters surfaced to KV.** Cron handlers write a `cache:cron-summary:{date}` blob (60-day TTL) with the full result of the run including granular counters so the after-the-fact debugger has something to inspect even if Vercel logs have rolled off (Hobby tier = 1hr retention). The handler writes this blob unconditionally and inside try/except — write failure on the summary must NEVER break the cron's HTTP response.
4. **SETNX / write-once locking** for projection keys (`proj2:`, `proj2all:`, `projection-espn:`) — prevents a silent-failure rerun from overwriting good data with empty data.
5. **Floor checks on the writer, not just the reader.** SETNX is a footgun without a write-side floor: if a partial fetch produces a small dict, the writer happily writes it and NX then permanently locks the bad data. `api/cron.py` `ACTUALS_FLOOR = 4` (PR #108) skips writes for any date whose dict has fewer than 4 entries — regular-season MLB days reliably have 10+ starts, so anything below 4 is almost certainly partial. This is the missing piece between "detect the failure" (counter granularity) and "tolerate the failure" (don't lock in bad data; let the next run try again with a complete dataset).
6. **Force-refresh caches feeding write-once paths.** A 24h cache TTL aligned with a 24h cron schedule creates a race where stale or partial data from one cron run can be reused by the next, and any partial write becomes permanent via NX (see #5). PR #108 adds `_redis.delete()` of `cache:mlb-stats:{year}` and `cache:game-logs:{year}` at the top of every cron run. Cost: ~3-5 seconds of per-player API fan-out. Benefit: staleness is no longer a risk vector for the actuals path. Other caches (savant, team-woba, team-win-data) are NOT force-refreshed since they don't feed write-once data.
7. **Prefer per-entity calls when bulk is suspect.** For game logs we fan out per-player via `ThreadPoolExecutor`; the pattern is more expensive but failures isolate to one player rather than nuking the whole pull.

### Post-hoc adjustment vs data-flow reorder
`Confidence: 9/10 · Last assessed: April 25, 2026`

When a new piece of context (e.g. roster ownership history) needs to influence an output that's already been computed (e.g. per-pitcher projections + locked KV writes), there are two structural choices:

1. **Reorder the data flow** so the new context is available before the consumer runs. Cleaner end state. Higher up-front cost — touching the top of the orchestrator (`get_league_data` in our case) is a wide blast radius. Often pulls in unrelated structural changes (e.g. moving the FA fetch up because the actuals fetch needs FA names).
2. **Post-hoc adjustment** after the consumer has run. Tag the new context onto already-built output objects, recompute aggregates from per-item details. Lower up-front cost. Forward-only deferral on side effects the consumer baked in (e.g. `proj2:` locks already written by `projection.py` can't be unwritten).

Reach for **post-hoc** when:
- The consumer has bounded side effects, and the side effects don't need the new context for correctness (just for optimization). Example: `projection.py`'s per-start KV locks are already mostly populated by the all-MLB cron and prior owners; a per-roster pitcher locking pre-acq starts now and not later doesn't materially change the accuracy dashboard's roster scope behavior.
- The aggregates can be recomputed from already-emitted per-item detail. Per-start `proj` values in `per_start_details` let us subtract pre-acq contributions without re-running the full projection.
- The orchestrator reorder would touch unrelated code (FA fetch ordering, etc.) and the risk of breaking something incidental is non-trivial.

Reach for **reorder** when:
- The consumer's side effects are *destructive* without the new context. Example: if `projection.py` were sending emails or charging credit cards based on the un-tagged data, post-hoc would be wrong.
- The orchestrator is small enough that the reorder is contained.
- The post-hoc recompute would need information that wasn't emitted (forcing an even uglier "expose internals" workaround).

**Examples in the codebase:**
- **PR #111 (session 26)** — chose post-hoc for the pre-acquisition tagging. Trade was: contained ~65-line addition vs. a top-of-orchestrator reorder that would have moved the FA fetch up and changed the actuals-fetch ordering. Cost paid: lock-skip in projection.py is forward-only deferred.
- **PR #81 (session 19)** — also post-hoc for dropped streamers. Same pattern: the dropped-player branch built `dropped_intersected[name]` from a filtered `startDates`, then ran projection on the intersected data. Worked because dropped players were a *new* code path being added, not an existing computation that needed retrofitting.
- **Pattern this rules out:** "wrap the consumer in an early-exit branch" is usually worse than both options. It muddies the consumer's contract and tends to leak the new context throughout the function. If the consumer needs the context, fix one of the two structural cases instead of plumbing flags.

**Always log post-hoc adjustments visibly.** PR #111 prints `[espn.py] Pre-acquisition: <name> — tagged N start(s) (...)` for every affected player. Future regressions in the tagging logic surface in Vercel logs at deploy time — this is the cheap version of write-path observability for any post-hoc mutation.

### Rostered-window invariant
`Confidence: 10/10 · Last assessed: April 25, 2026`

Any per-pitcher value the user sees on the My Team page must be scoped to dates that pitcher was actually on the roster within the matchup window. This applies uniformly across all three pitcher-state branches in `api/espn.py`: currently-rostered pitchers (whose start history may include pre-acquisition dates), dropped streamers (whose start history may include post-drop dates), and the lag-fix newly-added case (whose start history wraps yet another timing edge). The rule is the same: a value attributed to a pitcher for a date outside their `days_on_team` set must not aggregate into row totals or tile counts.

The invariant is enforced in four places, each closing a different facet:

1. **PR #81 (session 19)** — dropped streamers' `startDates` intersected with `days_on_team`. Projected Starts and Actual Starts tiles only count rostered-window starts. The original instance.
2. **PR #111 (session 26)** — currently-rostered pitchers' `startDates` tagged `preAcquisition: true` for dates before the pickup. Effective `starts` and `projFpts` recomputed to exclude tagged entries. Frontend renders muted cells with the pre-acq `ProjectionTooltip` variant for context. Generalization of PR #81's pattern from one branch to all three.
3. **PR #114 (session 27)** — the lag-fix trigger fires off the returned scoring period, not UTC today, so newly-added pitchers reach the right code path regardless of UTC-vs-ET drift. Without this, evening adds fell through into the dropped-player branch and got the wrong invariant applied (slot `EX`, no per-start projection).
4. **PR #115 (session 27)** — dropped streamers' `info["player_fpts"]` intersected with `days_on_team`. Act FPTS row total excludes any post-drop FPTS attributed via the FA actual_fpts path. Symmetric closure of the same shape PR #81 fixed for `startDates`.

PR #113 (session 27) is gating infrastructure for #114 — when the lag-fix branch fires, derived structures (`starts_map`, `roster_team_map`, `all_player_names`) get rebuilt from the refreshed `roster_entries` so newly-added pitchers reach the projection model with their start data intact.

**When you next touch an aggregation in `api/espn.py` that sums or counts a per-date value across pitchers, ask: "is this scoped to the rostered window, or is it summing the raw dict?"** If raw, you have a fifth enforcement point to add. The pattern is `set(info["days_on_team"])` followed by a comprehension that filters keys/dates against that set. PR #115 is the smallest worked example.

**The invariant ends at the rendering layer.** The frontend trusts backend-emitted values — `pages/my-team.tsx` doesn't re-enforce. Any new aggregation must apply the intersection at the point of emission in `api/espn.py`; you can't fix it later in the frontend because the data is already wrong by the time it gets there.

**Connection to the post-hoc adjustment decision above.** All four enforcements are post-hoc adjustments rather than data-flow reorders. The choice was made independently each time but the rationale is the same: the consumer (`get_projected_fpts` for #111/#114, the `info["player_fpts"]` lookup for #81/#115) emits per-item detail that lets us recompute aggregates without re-running the consumer. When that property holds, post-hoc beats reorder.

### File architecture (refactored session 18)
`Confidence: 10/10 · Last assessed: April 25, 2026`

| File | Lines | Responsibility |
|---|---|---|
| `api/espn.py` | ~504 | Orchestrator: `get_league_data()` + HTTP handler |
| `api/projection.py` | ~415 | Projection model: Savant hybrid, year blend, recent form, matchup adjustments, W/L scaling, locking |
| `api/fetcher.py` | ~470 | ESPN data fetching, auth, pro team map, actual FPTS, cached data loading (load_cached_data unpacks fetch_game_logs tuple as of session 25) |
| `api/mlb.py` | ~1035 | MLB probables, schedule, wOBA (season + recent + blended), park factors, Pythagorean model, game logs (returns (data, stats) tuple as of session 25) |
| `api/savant.py` | ~255 | Baseball Savant CSV data fetching |
| `api/weather.py` | ~315 | Open-Meteo client + park coords + temperature factor + diagnostic endpoint |
| `api/kv.py` | ~255 | Upstash Redis helpers for projection locking and caching |
| `api/accuracy.py` | ~322 | Accuracy tracking endpoint (roster + all-MLB scopes) |
| `api/cron.py` | ~490 | Daily cron: lock all-MLB projections + store actuals + cron-summary write (session 25 hardened) |
| `api/config.py` | ~73 | Matchup period table + current period lookup |
| `api/analyze.py` | ~100 | Claude AI analysis endpoint |

### Daily cron job
`Confidence: 9/10 · Last assessed: April 25, 2026`

`/api/cron` runs daily at noon CT (17:00 UTC) via Vercel Cron (`vercel.json` → `crons` config).
Secured with `CRON_SECRET` env var — Vercel sends it automatically as `Authorization: Bearer {secret}`.

What it does (post-PR #108):
1. **Force-invalidates `cache:mlb-stats:{year}` and `cache:game-logs:{year}`** so the run starts on guaranteed-fresh data. Other caches (savant, team-woba, team-win-data) are kept since their data changes more slowly and they don't feed write-once paths.
2. Fetches all probable starters for today from ESPN scoreboard + MLB Stats API
3. Loads cached model data (Savant, MLB Stats, game logs) — the two invalidated caches refill via fresh fetches inside `load_cached_data()`
4. Runs projection model for every probable starter (~60 per day)
5. Locks projections to `proj2all:{season}:{period}:{slug}:{date}` KV keys (NX flag) — matchup sub-dict includes `opponent`, `isHome`, `winProb`, `wpSource` (PR #109 added the first two)
6. Computes actual FPTS from game logs for completed past dates
7. **Floor check (`ACTUALS_FLOOR = 4`)** before each `actual-all:{date}` NX-write — skips dates with fewer than 4 entries, on the heuristic that regular-season MLB days reliably have 10+ starts. Prevents partial fetches from being NX-locked permanently.
8. Stores actuals under `actual-all:{date}` KV keys
9. Locks today's ESPN Forecaster projections under `projection-espn:{year}:{period}:{slug}:{date}` (60-day TTL)
10. **Writes `cache:cron-summary:{date}`** with the full result blob (60-day TTL) including `gameLogStats`, `actualsStored`, `actualsSkippedPartial`, `actualsDatesEligible`, `totalGameRows`, etc. Persists past Vercel's 1hr log retention.

Hobby plan limit: 2 cron jobs, each triggered once per day. We use 1.

**Manual trigger (when debugging):**
```
curl -i "https://the-skipper-iota.vercel.app/api/cron" \
  -H "Authorization: Bearer $CRON_SECRET"
```

**Reading the response:** `gameLogStats: {requested, with_data, empty, http_errors, exceptions}` is the new health-check surface. A clean run is `requested == with_data` with `empty == 0`. A spike in `empty` is the silent-failure mode session 25 chased — that's the diagnostic signature of an upstream `fetch_game_logs` regression.

### Known ESPN API gaps
`Confidence: 7/10 · Last assessed: April 12, 2026`

- Suspended (SSPD) players may not appear in `mRoster` response — Reynaldo Lopez picked up but missing from roster data. Needs investigation of what `eligibleSlots`/`lineupSlotId` ESPN assigns to suspended players.
- `injuryStatus` returns empty string for all rostered players (use `player.injured` boolean instead)
- Free agent actual FPTS only available if player was rostered at time of start

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
| `CRON_SECRET` | Secures `/api/cron` endpoint (Vercel sends as Authorization header) |
