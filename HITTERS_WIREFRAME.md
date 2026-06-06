# Hitters — exploration & wireframe

> Status: **exploration / wireframe only.** The `/hitters` page ships with
> hard-coded mock data and no backend. This doc captures the thinking behind
> it so we can react to the *shape* of the feature before building the
> ESPN/MLB/Savant plumbing.

## Why hitters are a different problem than pitchers

The Skipper today is built entirely around **starting pitchers** and a
**weekly starts limit**. Almost every concept in the app — the schedule grid,
"projected vs. actual starts," the Mon–Sun action plan — exists to answer one
question: *which SPs do I start this week to hit my limit with the best
points?*

Hitters don't fit that frame:

| | Starting pitchers | Hitters |
|---|---|---|
| Cadence | Start every 5th day | Play (nearly) every day |
| Scarce resource | Weekly **starts limit** | Daily **lineup slots** by position |
| Key decision | Which SPs to roster/stream for the week | Who to **start vs. bench today**; when to upgrade a slot |
| Matchup driver | Opponent lineup quality, park, weather (run environment) | Opposing-SP handedness (platoon), park, weather — the **inverse** of the run-environment math |
| Variance | High (one bad start tanks a week) | Lower per game, smoother over a week |

So a hitter view isn't "the SP page with different stats." The optimization
axis changes from *budgeting a weekly starts cap* to *winning daily lineup
decisions and catching waiver upgrades* — which is exactly the lightweight
**"nudge engine"** already noted in `BACKLOG.md`:

> **Hitter nudge engine** — Lighter-weight than the pitcher optimizer — "this
> waiver wire guy is outperforming your current 2B." Not a full streamer
> optimizer, more of a watchlist with performance alerts.

## What the wireframe shows (`pages/hitters.tsx`)

Reuses the existing Midnight design language (MetricCard, mono section labels,
segmented toggle, card containers, slot badges) so it reads as a native
screen, not a bolt-on.

1. **Header metrics** — Proj FPTS today, hitters rostered, favorable matchups
   (n/total), open upgrade nudges.
2. **Today's lineup** with two lenses (segmented toggle, mirroring
   Schedule/Stats on the pitcher pages):
   - **Today's edges** — opposing SP + handedness + park, a green/red **matchup
     edge chip** (the inverse of the pitcher model's run-environment
     multiplier), today's projected points, and a **form sparkline** (reused
     concept from the pitcher StatsTable). Benched/unfavorable bats are dimmed.
   - **Season line** — AVG/OBP/SLG slash + HR/R/RBI/SB counting stats.
3. **Bench** — same row renderer, with an inline call-out when a bench bat
   out-projects a starter at an eligible slot today.
4. **Waiver upgrade nudges** — the core "nudge engine": FAs projected to
   out-earn a rostered hitter at the same position over the next 7 days, with a
   plain-language reason, the points delta, and a (non-functional) Compare CTA.
   Marginal nudges (<3 pts/wk) are de-emphasized to avoid alert fatigue.

## What it would take to make it real

None of the below is built — it's the implied backend work.

- **Roster ingest** — `api/espn.py` already pulls the full roster; today it
  filters to SP/RP via `eligibleSlots`. We'd keep the hitter slots (C, 1B, 2B,
  3B, SS, OF, UTIL) instead of discarding them, and surface per-day
  `lineupSlotId` (active vs. bench) that KNOWLEDGE.md already documents.
- **Hitter projections** — a parallel to the pitcher `projection.py` model:
  a skill base (rate stats / wOBA) × a **run-environment multiplier applied the
  normal way** (favorable park/weather/opposing-SP = higher, the literal
  inverse of `env_to_pitcher_mult`). The opposing-SP handedness + platoon split
  is the new input (MLB Stats API handedness; Savant for xwOBA vs. L/R).
- **Daily projections, not weekly** — projections are per-game and the unit of
  decision is the day, so the warm-cache precompute (`api/warm.py`) would key
  on date rather than matchup week.
- **Nudge engine** — compare each rostered hitter's 7-day projection against
  the top same-position FAs (data already available from the free-agent fetch);
  emit a nudge when the delta clears a threshold. This is far cheaper than the
  pitcher streamer optimizer — no starts-limit constraint solving.

## Open questions for the design review

- **Scope** — full daily lineup optimizer, or just the watchlist/nudge engine
  to start (the cheaper, backlog-aligned path)?
- **Nav** — separate "Hitters" tab (as wireframed), or fold hitters into "My
  Team" as a second section under the pitchers?
- **League fit** — this assumes a daily-lineup, points league with positional
  slots. Worth confirming against the actual league's roster/scoring settings.
