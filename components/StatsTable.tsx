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

export interface Pitcher {
  name: string
  team: string
  slot: string                // "SP" | "RP" | "IL" | etc.
  starts: number
  projFpts: number
  projBlend?: number
  percentOwned?: number
  startDates?: StartDate[]
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
  {
    key: 'fptsPerStart', label: 'FPTS/G', minWidth: 64,
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
      // Numeric columns default to descending (best first); string columns to ascending (A→Z).
      setSortDir(col.sortValue ? 'desc' : 'asc')
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
