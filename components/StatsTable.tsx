// components/StatsTable.tsx
// Stats lens for the same pitcher data the ScheduleGrid renders.
// Renders one row per pitcher, one column per stat — instead of one
// column per day. Sortable by any numeric or string column, IL
// pitchers always sink to the bottom regardless of sort direction.
//
// Column system is data-driven via the PITCHER_COLUMNS const so future
// column additions (season W/L/ERA, Savant expecteds, luck indicator,
// projected season pace) plug into the same renderer. The table itself
// stays renderer-only — all data shaping lives in the column defs.

import { useCallback, useMemo, useState } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface StartDate {
  date: string
  preAcquisition?: boolean
}

// Compact season-stat payload built on the backend in api/espn.py.
// Returned as null when the pitcher has no IP yet (avoids divide-by-zero
// and lets cells render an em-dash without per-field null checks).
export interface SeasonStats {
  w: number
  l: number
  era: number
  k9: number
  bb9: number
  sv?: number                // season saves (relievers)
  ip: number
  gs: number
  seasonFptsToDate?: number  // season-to-date FPTS from season totals (backend)
}

// Combined Savant payload — expected stats + statcast. Each field is
// only present when its source had a non-zero value, so rendering must
// gracefully handle any field being absent (the whole object is null
// only for pitchers with no Savant footprint at all).
export interface SavantExpected {
  xera?: number
  xwoba?: number
  wobaDiff?: number   // est_woba - woba: positive = unlucky, due to improve
  barrelPct?: number
  whiffPct?: number
}

export interface Pitcher {
  name: string
  team: string
  slot: string                // "SP" | "RP" | "IL" | etc.
  starts: number
  projFpts: number
  projBlend?: number
  percentOwned?: number
  startDates?: StartDate[]
  seasonStats?: SeasonStats | null
  savantExpected?: SavantExpected | null
  fptsHistory?: number[] | null   // actual FPTS per start, oldest→newest (last ~10)
}

// Lookups the table needs but that don't live on the player object itself.
// Passed once by the parent and threaded into each column's sortValue/render.
export interface StatsTableContext {
  fptsPerStart: Record<string, number>
  actualFpts: Record<string, Record<string, number>>
  // Per-pitcher projection breakdown (api/espn.py faProjectionDetails). Feeds
  // the Proj FPTS tooltip — especially useful for relievers, where it explains
  // appearances assumed and which season the projection leans on.
  projectionDetails?: Record<string, any>
  // Opens a tap-to-show popover anchored at the tapped element. Set by the
  // table so cell renderers can surface their detail on touch (where the
  // native hover `title` never fires). Undefined in the sort-only context.
  openInfo?: (content: React.ReactNode, e: React.MouseEvent) => void
}

export interface PitcherColumn {
  key: string                                // sort key (also React key for headers)
  label: string                              // header label
  align?: 'left' | 'center'
  minWidth?: number
  // Provide one of sortValue (numeric) or stringValue (string).
  // Columns with neither are unsortable.
  sortValue?: (p: Pitcher, ctx: StatsTableContext) => number
  stringValue?: (p: Pitcher, ctx: StatsTableContext) => string
  render: (p: Pitcher, ctx: StatsTableContext) => React.ReactNode
  // First-click sort direction. Defaults: 'desc' for numeric, 'asc' for string.
  // Override for "lower is better" stats (ERA, BB/9, xERA, xwOBA, Barrel%) so
  // a single click puts the best pitchers at the top.
  preferredDir?: 'asc' | 'desc'
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function SlotBadge({ slot }: { slot: string }) {
  const styles: Record<string, React.CSSProperties> = {
    SP: { background: 'var(--blue-light)',  color: 'var(--blue)' },
    RP: { background: 'var(--amber-light)', color: 'var(--amber)' },
    IL: { background: 'var(--red-light)',   color: 'var(--red)' },
  }
  const style = styles[slot] || { background: 'var(--paper-2)', color: 'var(--ink-3)' }
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600,
      fontFamily: 'var(--mono)', padding: '2px 8px', borderRadius: 99,
      letterSpacing: '0.04em', whiteSpace: 'nowrap', ...style,
    }}>{slot}</span>
  )
}

// Sums actualFpts for a pitcher, excluding any date tagged as a
// pre-acquisition start. Mirrors the ScheduleGrid Act FPTS row total
// so the two tabs agree on the same number for the same pitcher.
function actFptsTotal(p: Pitcher, ctx: StatsTableContext): number {
  const preAcqDates = new Set(
    (p.startDates || []).filter(s => s.preAcquisition).map(s => s.date)
  )
  return Object.entries(ctx.actualFpts[p.name] || {}).reduce(
    (a, [d, v]) => a + (preAcqDates.has(d) ? 0 : v),
    0
  )
}

// Baseball convention: rate stats with a max of 1 (BA, wOBA, xwOBA) are
// rendered without a leading zero (".285" not "0.285"). Negative values
// keep their sign in front of the dot.
function fmtBaseballDecimal(v: number, places: number = 3): string {
  const sign = v < 0 ? '-' : ''
  const abs = Math.abs(v).toFixed(places)
  return abs.startsWith('0.') ? `${sign}${abs.slice(1)}` : `${sign}${abs}`
}

// Same convention with an explicit + sign for non-negative values, so
// "+.012" reads as a clearly-positive luck delta on the wOBA-diff column.
function fmtWobaDiff(v: number): string {
  const sign = v > 0 ? '+' : v < 0 ? '-' : ''
  const abs = Math.abs(v).toFixed(3)
  return abs.startsWith('0.') ? `${sign}${abs.slice(1)}` : `${sign}${abs}`
}

// Render an em-dash for missing numeric values — wraps a value-or-null
// pattern that recurs across every season/Savant column.
function NumOrDash({ value, render }: {
  value: number | undefined | null
  render: (v: number) => React.ReactNode
}) {
  if (value === undefined || value === null || !Number.isFinite(value)) {
    return <span style={{ color: 'var(--ink-3)' }}>—</span>
  }
  return <>{render(value)}</>
}

// Luck lens over the wOBA-diff signal. wOBAΔ = expected wOBA − wOBA allowed:
// positive means a pitcher's contact results have been unluckier than the
// quality of contact warrants (results should improve), negative means they've
// been riding good luck (regression risk). Rendered as a compact colored
// trend line — slope direction shows up/flat/down, slope steepness scales with
// the magnitude of the delta. The numeric value + interpretation are in the
// tooltip. Threshold is 10 points of wOBA — below that the line reads flat/grey.
const LUCK_THRESHOLD = 0.010
// Delta at which the line hits its steepest slope (a strong luck signal).
const LUCK_FULL_SCALE = 0.030

function LuckTrend({ wobaDiff, onInfo }: {
  wobaDiff: number | undefined
  onInfo?: (content: React.ReactNode, e: React.MouseEvent) => void
}) {
  if (wobaDiff === undefined || !Number.isFinite(wobaDiff)) {
    return <span style={{ color: 'var(--ink-3)' }}>—</span>
  }
  const up = wobaDiff > LUCK_THRESHOLD
  const down = wobaDiff < -LUCK_THRESHOLD
  const color = up ? 'var(--green)' : down ? 'var(--red)' : 'var(--ink-3)'
  const label = up ? 'Trending up' : down ? 'Trending down' : 'On pace'
  const meaning =
    up   ? 'contact allowed has been unluckier than expected; results due to improve'
    : down ? 'contact allowed has been luckier than expected; regression risk'
    : 'actual and expected results are in line'
  const tip = `wOBAΔ ${fmtWobaDiff(wobaDiff)} — ${meaning}`
  const popover = (
    <div>
      <div style={{ fontWeight: 700, color, marginBottom: 4 }}>Luck · {label}</div>
      <div>wOBAΔ <strong>{fmtWobaDiff(wobaDiff)}</strong> — {meaning}.</div>
    </div>
  )

  // Geometry: a 2-point line across the cell. SVG y grows downward, so a
  // positive (unlucky → improving) delta should END higher = smaller y.
  const W = 46, H = 18, pad = 3
  const maxRise = (H / 2) - pad
  const norm = Math.max(-1, Math.min(1, wobaDiff / LUCK_FULL_SCALE))
  const dy = norm * maxRise
  const midY = H / 2
  const x0 = pad, x1 = W - pad
  const y0 = midY + dy / 2   // left endpoint
  const y1 = midY - dy / 2   // right endpoint (rises for positive delta)

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
      onClick={onInfo ? (e) => onInfo(popover, e) : undefined}
      style={{ display: 'inline-block', verticalAlign: 'middle',
               cursor: onInfo ? 'pointer' : 'default' }}
      role="img" aria-label={tip}>
      <title>{tip}</title>
      <line x1={x0} y1={y0} x2={x1} y2={y1}
        stroke={color} strokeWidth={2} strokeLinecap="round" />
      <circle cx={x1} cy={y1} r={2.5} fill={color} />
    </svg>
  )
}

// Form sparkline — actual FPTS for each of a pitcher's last ~10 starts,
// oldest→newest (assembled on the backend from game logs). Plots a real line
// with a dashed zero baseline so good vs blow-up starts read at a glance.
// Colored by RECENT form vs the season baseline: the last-5-start average
// against the pitcher's season FPTS/start (seasonFptsToDate ÷ gs) — green when
// running hotter than the season norm, red when colder, grey within a
// dead-band. Per-start values + the comparison live in the tap/hover detail.
const FORM_DEADBAND = 1.0  // FPTS — |L5 avg − season avg| within this reads flat/grey

function Sparkline({ values, seasonAvg, onInfo }: {
  values: number[] | null | undefined
  seasonAvg?: number
  onInfo?: (content: React.ReactNode, e: React.MouseEvent) => void
}) {
  if (!values || values.length < 2) {
    return <span style={{ color: 'var(--ink-3)' }}>—</span>
  }
  const W = 76, H = 22, pad = 3
  const n = values.length
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const range = max - min || 1
  const x = (i: number) => pad + (i / (n - 1)) * (W - 2 * pad)
  const y = (v: number) => pad + (1 - (v - min) / range) * (H - 2 * pad)
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = values[n - 1]

  // Recent form: last 5 starts (or fewer if that's all we have).
  const l5 = values.slice(-5)
  const l5avg = l5.reduce((a, b) => a + b, 0) / l5.length

  // Color by L5 vs season average, with a dead-band for "in line".
  let formColor = 'var(--ink-3)'
  let verdict = 'in line with season'
  if (seasonAvg !== undefined) {
    const delta = l5avg - seasonAvg
    if (delta > FORM_DEADBAND)       { formColor = 'var(--green)'; verdict = 'hotter than season' }
    else if (delta < -FORM_DEADBAND) { formColor = 'var(--red)';   verdict = 'colder than season' }
  }
  const seasonStr = seasonAvg !== undefined ? ` vs season ${seasonAvg.toFixed(1)}` : ''
  const tip = `Last ${n} starts. L5 avg ${l5avg.toFixed(1)}${seasonStr} — ${verdict}`
  const popover = (
    <div>
      <div style={{ fontWeight: 700, color: formColor, marginBottom: 4 }}>Form · {verdict}</div>
      <div style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
        {values.map((v, i) => (
          <span key={i} style={{ color: v >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {v.toFixed(0)}{i < n - 1 ? ', ' : ''}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 4 }}>
        L5 avg <strong>{l5avg.toFixed(1)}</strong>
        {seasonAvg !== undefined && <> vs season <strong>{seasonAvg.toFixed(1)}</strong>/start</>}
      </div>
    </div>
  )
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
      onClick={onInfo ? (e) => onInfo(popover, e) : undefined}
      style={{ display: 'inline-block', verticalAlign: 'middle',
               cursor: onInfo ? 'pointer' : 'default' }}
      role="img" aria-label={tip}>
      <title>{tip}</title>
      <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)}
        stroke="var(--border)" strokeWidth={1} strokeDasharray="2 2" />
      <polyline points={pts} fill="none" stroke={formColor}
        strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(n - 1)} cy={y(last)} r={2} fill={formColor} />
    </svg>
  )
}

// Projected full-season FPTS: season-to-date actual + model FPTS/start ×
// estimated remaining starts. A rough comparator (not a prediction) — remaining
// starts assume a healthy ~32-start season. Only meaningful for pitchers who've
// actually started (gs > 0); relievers and unstarted arms return undefined so
// the cell shows an em-dash rather than a fictional season total.
const FULL_SEASON_STARTS = 32

// Season actual FPTS per start = season-to-date FPTS ÷ games started. The
// baseline the Form sparkline colors against (NOT the FPTS/G column, which is
// the model's projected per-start). Undefined for pitchers with no starts.
function seasonAvgPerStart(p: Pitcher): number | undefined {
  const s = p.seasonStats
  if (!s || !s.gs || s.gs <= 0 || !Number.isFinite(s.seasonFptsToDate as number)) {
    return undefined
  }
  return (s.seasonFptsToDate as number) / s.gs
}

function projectedPace(p: Pitcher, ctx: StatsTableContext): number | undefined {
  const s = p.seasonStats
  if (!s || !s.gs || s.gs <= 0 || !Number.isFinite(s.seasonFptsToDate as number)) {
    return undefined
  }
  const perStart = ctx.fptsPerStart[p.name]
  if (perStart === undefined) return undefined
  const remaining = Math.max(0, FULL_SEASON_STARTS - s.gs)
  return (s.seasonFptsToDate as number) + perStart * remaining
}

// ─── Column definitions ──────────────────────────────────────────────────────
// V1 columns — only fields already present on the rosterSPs / droppedPlayers
// payload from /api/espn. Future PRs add season stats and Savant expecteds
// behind their own backend changes; those columns slot in here without
// changing the renderer.

export const PITCHER_COLUMNS: PitcherColumn[] = [
  {
    key: 'name', label: 'Pitcher', align: 'left', minWidth: 160,
    stringValue: (p) => p.name,
    render: (p) => (
      <span style={{ fontWeight: 600 }}>{p.name}</span>
    ),
  },
  {
    key: 'team', label: 'Team', minWidth: 52,
    stringValue: (p) => p.team,
    render: (p) => (
      <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{p.team}</span>
    ),
  },
  {
    key: 'slot', label: 'Slot', minWidth: 52,
    stringValue: (p) => p.slot,
    render: (p) => <SlotBadge slot={p.slot} />,
  },
  {
    key: 'percentOwned', label: 'Own%', minWidth: 60,
    sortValue: (p) => p.percentOwned ?? 0,
    render: (p) => (
      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
        {Math.round(p.percentOwned ?? 0)}%
      </span>
    ),
  },
  {
    key: 'starts', label: 'Starts', minWidth: 56,
    sortValue: (p) => p.starts ?? 0,
    render: (p) => (
      <span style={{ fontFamily: 'var(--mono)', fontWeight: 700 }}>
        {p.starts ?? 0}
      </span>
    ),
  },

  // ── Season real stats (from MLB Stats API season pitching totals) ──
  // Missing data → render em-dash AND return NaN from sortValue so the
  // pitcher sinks to the bottom regardless of sort direction.
  {
    key: 'wl', label: 'W-L', minWidth: 56,
    sortValue: (p) => p.seasonStats ? p.seasonStats.w : NaN,
    render: (p) => (
      <NumOrDash value={p.seasonStats?.w} render={(_w) => (
        <span style={{ fontFamily: 'var(--mono)' }}>
          {p.seasonStats!.w}-{p.seasonStats!.l}
        </span>
      )} />
    ),
  },
  {
    key: 'era', label: 'ERA', minWidth: 56, preferredDir: 'asc',
    sortValue: (p) => p.seasonStats ? p.seasonStats.era : NaN,
    render: (p) => (
      <NumOrDash value={p.seasonStats?.era} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)' }}>{v.toFixed(2)}</span>
      )} />
    ),
  },
  {
    key: 'k9', label: 'K/9', minWidth: 56,
    sortValue: (p) => p.seasonStats ? p.seasonStats.k9 : NaN,
    render: (p) => (
      <NumOrDash value={p.seasonStats?.k9} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)' }}>{v.toFixed(1)}</span>
      )} />
    ),
  },
  {
    key: 'bb9', label: 'BB/9', minWidth: 56, preferredDir: 'asc',
    sortValue: (p) => p.seasonStats ? p.seasonStats.bb9 : NaN,
    render: (p) => (
      <NumOrDash value={p.seasonStats?.bb9} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)' }}>{v.toFixed(1)}</span>
      )} />
    ),
  },

  // ── Savant expecteds (xERA, xwOBA, wOBA-diff from cache:savant; ──
  // Barrel%, Whiff% from cache:savant-statcast). Each field is independently
  // optional — render em-dash for any missing one without dimming the row.
  {
    key: 'xera', label: 'xERA', minWidth: 60, preferredDir: 'asc',
    sortValue: (p) => p.savantExpected?.xera ?? NaN,
    render: (p) => (
      <NumOrDash value={p.savantExpected?.xera} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
          {v.toFixed(2)}
        </span>
      )} />
    ),
  },
  {
    key: 'xwoba', label: 'xwOBA', minWidth: 64, preferredDir: 'asc',
    sortValue: (p) => p.savantExpected?.xwoba ?? NaN,
    render: (p) => (
      <NumOrDash value={p.savantExpected?.xwoba} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
          {fmtBaseballDecimal(v, 3)}
        </span>
      )} />
    ),
  },
  {
    // Higher = pitcher has been more unlucky (xwOBA > wOBA allowed) and
    // is statistically due for positive regression. Default desc surfaces
    // the most-due-to-improve names at the top — a "buy low" lens.
    key: 'wobaDiff', label: 'wOBAΔ', minWidth: 64,
    sortValue: (p) => p.savantExpected?.wobaDiff ?? NaN,
    render: (p) => (
      <NumOrDash value={p.savantExpected?.wobaDiff} render={(v) => (
        <span style={{
          fontFamily: 'var(--mono)',
          color: v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--ink-3)',
        }}>
          {fmtWobaDiff(v)}
        </span>
      )} />
    ),
  },
  {
    // Colored trend-line indicator derived from the wOBAΔ signal next to it.
    // Sort by the raw delta so a desc click surfaces the most due-to-improve
    // pitchers (steepest green climb) first.
    key: 'luck', label: 'Luck', minWidth: 64,
    sortValue: (p) => p.savantExpected?.wobaDiff ?? NaN,
    render: (p, ctx) => <LuckTrend wobaDiff={p.savantExpected?.wobaDiff} onInfo={ctx.openInfo} />,
  },
  {
    key: 'barrelPct', label: 'Brl%', minWidth: 56, preferredDir: 'asc',
    sortValue: (p) => p.savantExpected?.barrelPct ?? NaN,
    render: (p) => (
      <NumOrDash value={p.savantExpected?.barrelPct} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
          {v.toFixed(1)}%
        </span>
      )} />
    ),
  },
  {
    key: 'whiffPct', label: 'Whiff%', minWidth: 64,
    sortValue: (p) => p.savantExpected?.whiffPct ?? NaN,
    render: (p) => (
      <NumOrDash value={p.savantExpected?.whiffPct} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-2)' }}>
          {v.toFixed(1)}%
        </span>
      )} />
    ),
  },

  {
    // Model's projected FPTS per start — NOT a season average. Renamed from
    // "FPTS/G" (which read like a season-to-date average) to "Proj/G".
    key: 'fptsPerStart', label: 'Proj/G', minWidth: 64,
    sortValue: (_p, ctx) => 0,  // overridden inline below — see note
    render: (p, ctx) => {
      const v = ctx.fptsPerStart[p.name]
      if (v === undefined) {
        return <span style={{ color: 'var(--ink-3)' }}>—</span>
      }
      const tip = "The projection model's estimated fantasy points per start — not a season average."
      const popover = (
        <div>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Proj/G · {v.toFixed(1)}</div>
          <div>{tip}</div>
        </div>
      )
      return (
        <span
          title={tip}
          onClick={ctx.openInfo ? (e) => ctx.openInfo!(popover, e) : undefined}
          style={{ fontFamily: 'var(--mono)', fontWeight: 600,
                   cursor: ctx.openInfo ? 'pointer' : 'default' }}
        >
          {v.toFixed(1)}
        </span>
      )
    },
  },
  {
    // Recent-form sparkline: actual FPTS over the last ~10 starts. Sort by the
    // window average so a desc click surfaces the hottest arms.
    key: 'form', label: 'Form', minWidth: 88,
    sortValue: (p) => {
      const h = p.fptsHistory
      return h && h.length ? h.reduce((a, b) => a + b, 0) / h.length : NaN
    },
    render: (p, ctx) => <Sparkline values={p.fptsHistory} seasonAvg={seasonAvgPerStart(p)} onInfo={ctx.openInfo} />,
  },
  {
    key: 'projFpts', label: 'Proj FPTS', minWidth: 84,
    sortValue: (p) => p.projFpts ?? 0,
    render: (p, ctx) => {
      const v = p.projFpts ?? 0
      const valueEl = (
        <span style={{
          fontFamily: 'var(--mono)', fontWeight: 700,
          color: v > 0 ? 'var(--green)' : 'var(--ink-3)',
        }}>
          {v.toFixed(1)}
        </span>
      )
      const d = ctx.projectionDetails?.[p.name]
      if (!d) return valueEl
      // blendWeight is the fraction of the projection on the current season;
      // a tiny value means it leans on last season (small current-year sample).
      const yr = typeof d.blendWeight === 'number' ? d.blendWeight : 1
      const basis = yr >= 0.85 ? 'this season'
        : yr <= 0.15 ? 'last season'
        : `a blend (${Math.round(yr * 100)}% this season)`
      const rp = d.rp
      const popover = (
        <div>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Projection · {v.toFixed(1)} FPTS</div>
          {rp ? (
            <>
              <div>{Number(rp.perAppearance).toFixed(1)} FPTS/appearance × {rp.appearances} appearances</div>
              <div style={{ marginTop: 3 }}>Based on {basis} stats.</div>
              {rp.regressed && (
                <div style={{ marginTop: 3, color: 'var(--ink-3)' }}>
                  Small sample — regressed toward a league-average reliever.
                </div>
              )}
            </>
          ) : (
            <>
              <div>Base {Number(d.adjustedBase ?? d.seasonBase ?? 0).toFixed(1)} FPTS/start · {d.modelType} model</div>
              <div style={{ marginTop: 3 }}>Based on {basis} stats.</div>
            </>
          )}
        </div>
      )
      return (
        <span
          title="Projection detail"
          onClick={ctx.openInfo ? (e) => ctx.openInfo!(popover, e) : undefined}
          style={{
            cursor: ctx.openInfo ? 'pointer' : 'default',
            borderBottom: ctx.openInfo ? '1px dotted var(--ink-3)' : 'none',
          }}
        >
          {valueEl}
        </span>
      )
    },
  },
  {
    key: 'actFpts', label: 'Act FPTS', minWidth: 84,
    sortValue: (p, ctx) => actFptsTotal(p, ctx),
    render: (p, ctx) => {
      const total = actFptsTotal(p, ctx)
      if (total === 0) {
        return <span style={{ color: 'var(--ink-3)' }}>—</span>
      }
      return (
        <span style={{
          fontFamily: 'var(--mono)', fontWeight: 700,
          color: total > 0 ? 'var(--green)' : 'var(--red)',
        }}>
          {total > 0 ? '+' : ''}{total.toFixed(1)}
        </span>
      )
    },
  },
  {
    // Projected full-season FPTS pace — a comparator, not a prediction.
    // Blank (em-dash) for non-starters, where it would be meaningless.
    key: 'pace', label: 'Pace', minWidth: 72,
    sortValue: (p, ctx) => projectedPace(p, ctx) ?? NaN,
    render: (p, ctx) => (
      <NumOrDash value={projectedPace(p, ctx)} render={(v) => {
        const tip = 'Projected full-season FPTS: season-to-date actual + model FPTS/start × estimated remaining starts (~32-start season). A rough comparator, not a prediction.'
        const popover = (
          <div>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Pace · {v.toFixed(0)} FPTS</div>
            <div>{tip}</div>
          </div>
        )
        return (
          <span
            title={tip}
            onClick={ctx.openInfo ? (e) => ctx.openInfo!(popover, e) : undefined}
            style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--ink-2)',
                     cursor: ctx.openInfo ? 'pointer' : 'default' }}
          >
            {v.toFixed(0)}
          </span>
        )
      }} />
    ),
  },
]

// Patch FPTS/G sortValue to use the actual ctx lookup. Done out-of-line so the
// column object literal stays readable; the function above was a placeholder.
PITCHER_COLUMNS.find(c => c.key === 'fptsPerStart')!.sortValue =
  (p, ctx) => ctx.fptsPerStart[p.name] ?? 0

// Saves column — deliberately NOT in the default (SP) set, since starters
// rarely save. The Free Agents RP view includes it explicitly, as saves are a
// key part of reliever scoring.
export const SV_COLUMN: PitcherColumn = {
  key: 'sv', label: 'SV', minWidth: 48,
  sortValue: (p) => p.seasonStats?.sv ?? NaN,
  render: (p) => (
    <NumOrDash value={p.seasonStats?.sv} render={(v) => (
      <span style={{ fontFamily: 'var(--mono)', fontWeight: 700 }}>{v}</span>
    )} />
  ),
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  pitchers: Pitcher[]
  columns?: PitcherColumn[]
  fptsPerStart?: Record<string, number>
  actualFpts?: Record<string, Record<string, number>>
  projectionDetails?: Record<string, any>
  defaultSortCol?: string
  defaultSortDir?: 'asc' | 'desc'
}

export default function StatsTable({
  pitchers,
  columns = PITCHER_COLUMNS,
  fptsPerStart = {},
  actualFpts = {},
  projectionDetails = {},
  defaultSortCol = 'projFpts',
  defaultSortDir = 'desc',
}: Props) {
  const [sortCol, setSortCol] = useState(defaultSortCol)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(defaultSortDir)
  // Tap-to-show popover for cell detail (sparkline values, Luck/Pace help) —
  // surfaces what the hover `title` can't reach on touch devices.
  const [popover, setPopover] = useState<{ content: React.ReactNode; top: number; left: number } | null>(null)

  const openInfo = useCallback((content: React.ReactNode, e: React.MouseEvent) => {
    const rect = (e.currentTarget as Element).getBoundingClientRect()
    const PW = 220
    setPopover({
      content,
      top: rect.bottom + 6,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - PW - 8)),
    })
  }, [])

  function handleSort(col: PitcherColumn) {
    if (!col.sortValue && !col.stringValue) return
    if (col.key === sortCol) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortCol(col.key)
      // First-click direction:
      // 1. Honor an explicit preferredDir if the column declares one
      //    (used for "lower is better" stats like ERA, BB/9, xERA).
      // 2. Else: numeric columns default to desc (best first), strings to asc (A→Z).
      const defaultDir: 'asc' | 'desc' = col.sortValue ? 'desc' : 'asc'
      setSortDir(col.preferredDir || defaultDir)
    }
  }

  const sortedPitchers = useMemo(() => {
    const col = columns.find(c => c.key === sortCol)
    if (!col) return pitchers
    const ctx: StatsTableContext = { fptsPerStart, actualFpts }
    const list = [...pitchers]
    list.sort((a, b) => {
      // IL always sinks to the bottom regardless of sort direction.
      // Mirrors the existing ScheduleGrid layout where IL is rendered last.
      if (a.slot === 'IL' && b.slot !== 'IL') return 1
      if (b.slot === 'IL' && a.slot !== 'IL') return -1

      if (col.stringValue) {
        const cmp = col.stringValue(a, ctx).localeCompare(col.stringValue(b, ctx))
        return sortDir === 'asc' ? cmp : -cmp
      }
      if (col.sortValue) {
        const av = col.sortValue(a, ctx)
        const bv = col.sortValue(b, ctx)
        // Missing data (sortValue returns NaN) always sinks to the bottom
        // regardless of sort direction — flipping desc→asc shouldn't bring
        // pitchers without season stats to the top.
        const aMissing = !Number.isFinite(av)
        const bMissing = !Number.isFinite(bv)
        if (aMissing && !bMissing) return 1
        if (bMissing && !aMissing) return -1
        if (aMissing && bMissing) return 0
        return sortDir === 'desc' ? bv - av : av - bv
      }
      return 0
    })
    return list
  }, [pitchers, sortCol, sortDir, columns, fptsPerStart, actualFpts])

  const ctx: StatsTableContext = { fptsPerStart, actualFpts, projectionDetails, openInfo }

  // ── Styles ──
  const headerBase: React.CSSProperties = {
    padding: '8px 10px',
    fontSize: 10,
    fontFamily: 'var(--mono)',
    fontWeight: 500,
    letterSpacing: '0.05em',
    borderBottom: '1px solid var(--border)',
    textAlign: 'center',
    whiteSpace: 'nowrap',
    userSelect: 'none',
  }

  const cellBase: React.CSSProperties = {
    padding: '10px',
    fontSize: 13,
    borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle',
    textAlign: 'center',
    whiteSpace: 'nowrap',
  }

  function sortIndicator(col: PitcherColumn) {
    if (col.key !== sortCol) return null
    return <span style={{ marginLeft: 3 }}>{sortDir === 'desc' ? '↓' : '↑'}</span>
  }

  if (pitchers.length === 0) {
    return (
      <div style={{
        fontSize: 13, color: 'var(--ink-3)', textAlign: 'center', padding: '24px 0',
      }}>
        No pitchers to display.
      </div>
    )
  }

  return (
    <>
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            {columns.map(col => {
              const sortable = !!(col.sortValue || col.stringValue)
              const isActive = col.key === sortCol
              return (
                <th
                  key={col.key}
                  onClick={() => handleSort(col)}
                  style={{
                    ...headerBase,
                    minWidth: col.minWidth,
                    textAlign: col.align || 'center',
                    cursor: sortable ? 'pointer' : 'default',
                    color: isActive ? 'var(--ink)' : 'var(--ink-3)',
                    fontWeight: isActive ? 700 : 500,
                  }}
                >
                  {col.label}{sortIndicator(col)}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sortedPitchers.map((pitcher, i) => {
            const isIL = pitcher.slot === 'IL'
            return (
              <tr key={`${pitcher.name}-${i}`} style={{ opacity: isIL ? 0.5 : 1 }}>
                {columns.map(col => (
                  <td
                    key={col.key}
                    style={{
                      ...cellBase,
                      textAlign: col.align || 'center',
                    }}
                  >
                    {col.render(pitcher, ctx)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>

    {/* Tap-to-show popover. Full-screen overlay catches the dismiss tap; the
        box is fixed-positioned just under the tapped indicator. */}
    {popover && (
      <>
        <div
          onClick={() => setPopover(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 50 }}
        />
        <div
          role="dialog"
          style={{
            position: 'fixed', top: popover.top, left: popover.left, zIndex: 51,
            width: 220, background: 'var(--paper-2)', color: 'var(--ink)',
            border: '1px solid var(--border)', borderRadius: 8,
            boxShadow: 'var(--shadow)', padding: '10px 12px',
            fontSize: 12, lineHeight: 1.45,
          }}
        >
          {popover.content}
        </div>
      </>
    )}
    </>
  )
}
