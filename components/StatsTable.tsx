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

import { useMemo, useState } from 'react'

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
  ip: number
  gs: number
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
}

// Lookups the table needs but that don't live on the player object itself.
// Passed once by the parent and threaded into each column's sortValue/render.
export interface StatsTableContext {
  fptsPerStart: Record<string, number>
  actualFpts: Record<string, Record<string, number>>
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
  // Help text rendered as the native HTML title attribute on the column
  // header. Hover the header for ~1 second and the browser shows the
  // tooltip. Skip for self-explanatory columns (Pitcher, Team, Starts).
  tooltip?: string
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
    tooltip: 'SP = starter · RP = reliever · IL = injured list · EX = recently dropped',
    stringValue: (p) => p.slot,
    render: (p) => <SlotBadge slot={p.slot} />,
  },
  {
    key: 'percentOwned', label: 'Own%', minWidth: 60,
    tooltip: 'Percentage of ESPN leagues that have this pitcher rostered',
    sortValue: (p) => p.percentOwned ?? 0,
    render: (p) => (
      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
        {Math.round(p.percentOwned ?? 0)}%
      </span>
    ),
  },
  {
    key: 'starts', label: 'Starts', minWidth: 56,
    tooltip: 'Projected starts in this matchup period (confirmed + scheduled)',
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
    tooltip: 'Season wins and losses. Sorts by wins.',
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
    tooltip: 'Earned run average — earned runs allowed per 9 innings. Lower is better.',
    sortValue: (p) => p.seasonStats ? p.seasonStats.era : NaN,
    render: (p) => (
      <NumOrDash value={p.seasonStats?.era} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)' }}>{v.toFixed(2)}</span>
      )} />
    ),
  },
  {
    key: 'k9', label: 'K/9', minWidth: 56,
    tooltip: 'Strikeouts per 9 innings pitched. Higher is better.',
    sortValue: (p) => p.seasonStats ? p.seasonStats.k9 : NaN,
    render: (p) => (
      <NumOrDash value={p.seasonStats?.k9} render={(v) => (
        <span style={{ fontFamily: 'var(--mono)' }}>{v.toFixed(1)}</span>
      )} />
    ),
  },
  {
    key: 'bb9', label: 'BB/9', minWidth: 56, preferredDir: 'asc',
    tooltip: 'Walks per 9 innings pitched. Lower is better.',
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
    tooltip: 'Expected ERA from Statcast contact quality. xERA below ERA suggests the pitcher has been unlucky — actual results worse than the underlying batted-ball data implies.',
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
    tooltip: 'Expected weighted on-base average allowed. Single best contact-quality summary stat — what hitters’ EV and launch angle off this pitcher say their wOBA should be. Lower is better.',
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
    tooltip: 'xwOBA minus actual wOBA allowed. Positive (green) = pitcher has been unlucky and is statistically due for improvement. Negative (red) = pitcher has been lucky and is due for regression.',
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
    key: 'barrelPct', label: 'Brl%', minWidth: 56, preferredDir: 'asc',
    tooltip: 'Barrel rate — % of batted balls hit at the optimal exit-velocity / launch-angle combo for extra-base contact. Lower is better for the pitcher.',
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
    tooltip: 'Swinging-strike rate — % of swings that miss. Higher is better. (Data plumbing in progress — see PR 4.)',
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
    key: 'fptsPerStart', label: 'FPTS/G', minWidth: 64,
    tooltip: 'Projected fantasy points per start, including matchup adjustments (opponent wOBA, park factor, win probability, weather).',
    sortValue: (_p, ctx) => 0,  // overridden inline below — see note
    render: (p, ctx) => {
      const v = ctx.fptsPerStart[p.name]
      if (v === undefined) {
        return <span style={{ color: 'var(--ink-3)' }}>—</span>
      }
      return (
        <span style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>
          {v.toFixed(1)}
        </span>
      )
    },
  },
  {
    key: 'projFpts', label: 'Proj FPTS', minWidth: 84,
    tooltip: 'Total projected fantasy points across this matchup period (FPTS/G × projected starts in window).',
    sortValue: (p) => p.projFpts ?? 0,
    render: (p) => (
      <span style={{
        fontFamily: 'var(--mono)', fontWeight: 700,
        color: (p.projFpts ?? 0) > 0 ? 'var(--green)' : 'var(--ink-3)',
      }}>
        {(p.projFpts ?? 0).toFixed(1)}
      </span>
    ),
  },
  {
    key: 'actFpts', label: 'Act FPTS', minWidth: 84,
    tooltip: 'Actual fantasy points scored so far in this matchup period. Excludes pre-acquisition starts (dates before this pitcher was on your roster).',
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
]

// Patch FPTS/G sortValue to use the actual ctx lookup. Done out-of-line so the
// column object literal stays readable; the function above was a placeholder.
PITCHER_COLUMNS.find(c => c.key === 'fptsPerStart')!.sortValue =
  (p, ctx) => ctx.fptsPerStart[p.name] ?? 0

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  pitchers: Pitcher[]
  columns?: PitcherColumn[]
  fptsPerStart?: Record<string, number>
  actualFpts?: Record<string, Record<string, number>>
  defaultSortCol?: string
  defaultSortDir?: 'asc' | 'desc'
}

export default function StatsTable({
  pitchers,
  columns = PITCHER_COLUMNS,
  fptsPerStart = {},
  actualFpts = {},
  defaultSortCol = 'projFpts',
  defaultSortDir = 'desc',
}: Props) {
  const [sortCol, setSortCol] = useState(defaultSortCol)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(defaultSortDir)

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

  const ctx: StatsTableContext = { fptsPerStart, actualFpts }

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
                  // Native browser tooltip — shows after ~1s hover. No custom
                  // styling, but consistent across browsers and accessible to
                  // screen readers without extra ARIA wiring.
                  title={col.tooltip}
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
  )
}
