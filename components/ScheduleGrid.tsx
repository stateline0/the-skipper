// components/ScheduleGrid.tsx
// Shared schedule grid used by both My Team and Free Agents pages.
// Shows a day-by-day breakdown of each pitcher's starts for the matchup period.

import { useMemo } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface StartDate {
  date: string        // "2026-03-26"
  confirmed: boolean  // true = MLB confirmed, false = ESPN projected
}

interface Pitcher {
  name: string
  team: string
  slot: string
  starts: number
  projFpts: number
  startDates?: StartDate[]
  // Free agents also have these:
  percentOwned?: number
  injuryStatus?: string
  checked?: boolean
}

interface ScheduleEntry {
  opponent: string   // e.g. "CIN"
  is_home: boolean
  status: string     // "scheduled" | "in_progress" | "final"
}

// schedule shape: { "2026-03-26": { "BOS": { opponent, is_home, status } } }
type Schedule = Record<string, Record<string, ScheduleEntry>>

interface Props {
  pitchers: Pitcher[]
  schedule: Schedule
  matchupDates: string[]   // [startDate, endDate] as "YYYY-MM-DD"
  // Optional extras rendered before the date columns (e.g. checkbox, own%)
  renderPrefix?: (pitcher: Pitcher, index: number) => React.ReactNode
  // Optional extras rendered after Proj FPTS (e.g. opponent list)
  renderSuffix?: (pitcher: Pitcher, index: number) => React.ReactNode
  // Column headers for prefix/suffix cells
  prefixHeaders?: React.ReactNode
  suffixHeaders?: React.ReactNode
  onRowClick?: (index: number) => void
  // Actual // Actual FPTS earned per pitcher per day: { "Garrett Crochet": { "2026-03-26": 26.0 } }
  actualFpts?: Record<string, Record<string, number>>
  // Days each pitcher was on bench: { "Edwin Diaz": ["2026-03-26", ...] }
  benchDays?: Record<string, string[]>
  // Saves per pitcher per day: { "Edwin Diaz": { "2026-03-27": 1 } }
  // Saves per pitcher per day: { "Edwin Diaz": { "2026-03-27": 1 } }
  actualSaves?: Record<string, Record<string, number>>
  // When provided, replaces the Starts column with a Saves column
  savesData?: Record<string, Record<string, number>>
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Badge({ label, color }: { label: string; color: 'blue' | 'amber' | 'red' | 'gray' }) {
  const styles: Record<string, React.CSSProperties> = {
    blue:  { background: 'var(--blue-light)',  color: 'var(--blue)' },
    amber: { background: 'var(--amber-light)', color: 'var(--amber)' },
    red:   { background: 'var(--red-light)',   color: 'var(--red)' },
    gray:  { background: 'var(--paper-2)',     color: 'var(--ink-3)' },
  }
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600,
      fontFamily: 'var(--mono)', padding: '2px 8px', borderRadius: 99,
      letterSpacing: '0.04em', whiteSpace: 'nowrap', ...styles[color],
    }}>{label}</span>
  )
}

// Build array of YYYY-MM-DD strings between start and end (inclusive)
function buildDateRange(start: string, end: string): string[] {
  const dates: string[] = []
  const cur = new Date(start + 'T12:00:00Z') // noon UTC avoids DST edge cases
  const last = new Date(end + 'T12:00:00Z')
  while (cur <= last) {
    dates.push(cur.toISOString().slice(0, 10))
    cur.setUTCDate(cur.getUTCDate() + 1)
  }
  return dates
}

// Format "2026-03-26" -> "Mar 26"
function fmtDate(iso: string): string {
  const [, m, d] = iso.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[parseInt(m) - 1]} ${parseInt(d)}`
}

// Today's date as YYYY-MM-DD in local time
function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}

// ─── Cell renderer ────────────────────────────────────────────────────────────
// Returns what to show in a single pitcher × day cell.

function DayCell({ pitcher, date, schedule, today, actualFpts, benchDays, actualSaves }: {
  pitcher: Pitcher
  date: string
  schedule: Schedule
  today: string
  actualFpts?: Record<string, Record<string, number>>
  benchDays?: Record<string, string[]>
  actualSaves?: Record<string, Record<string, number>>
}){
  const isPast   = date < today
  const isToday  = date === today
  const isFuture = date > today

  const gameInfo = schedule[date]?.[pitcher.team]
  const startInfo = pitcher.startDates?.find(s => s.date === date)
  const isStarting = !!startInfo

  // No game for this team today
  if (!gameInfo) {
    return <span style={{ color: 'var(--ink-3)', fontSize: 11 }}>—</span>
  }

  const oppLabel = gameInfo.is_home ? gameInfo.opponent : `@${gameInfo.opponent}`

  // Past or live game
  if (isPast || isToday) {
    if (isStarting) {
      // They started — show opp + indicator + actual FPTS if available
      const indicator = startInfo.confirmed
          ? <span style={{ fontSize: 11, color: 'var(--green)' }}>✓</span>
          : <span style={{ fontSize: 10, fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--blue)', background: 'var(--blue-light)', borderRadius: 99, padding: '1px 5px' }}>P</span>
      const color = startInfo.confirmed ? 'var(--green)' : 'var(--ink-3)'
      const fpts = actualFpts?.[pitcher.name]?.[date]
      const hasFpts = fpts !== undefined && fpts !== 0
      const wasOnBench = benchDays?.[pitcher.name]?.includes(date) ?? false
      return (
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color }}>
            {oppLabel}
          </div>
          <div style={{ marginTop: 1 }}>{indicator}</div>
          {hasFpts && (
            <div style={{
              fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 700,
              color: wasOnBench ? 'var(--ink-3)' : fpts > 0 ? 'var(--green)' : 'var(--red)',
              marginTop: 1,
              textDecoration: wasOnBench ? 'line-through' : 'none',
            }}>
              {fpts > 0 ? '+' : ''}{fpts.toFixed(1)}
            </div>
          )}
          {actualSaves?.[pitcher.name]?.[date] && (
            <div style={{ fontSize: 10, marginTop: 1 }} title="Save recorded">🔒</div>
          )}
        </div>
      )
    } else {
      // Team played but pitcher didn't start — still show FPTS if they appeared (e.g. relievers)
      const fpts = actualFpts?.[pitcher.name]?.[date]
      const hasFpts = fpts !== undefined && fpts !== 0
      const wasOnBench = benchDays?.[pitcher.name]?.includes(date) ?? false
      const hasSave = !!actualSaves?.[pitcher.name]?.[date]

      if (hasFpts) {
        return (
          <div style={{ textAlign: 'center' }}>
            <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
              {oppLabel}
            </span>
            <div style={{
              fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 700,
              color: wasOnBench ? 'var(--ink-3)' : fpts > 0 ? 'var(--green)' : 'var(--red)',
              marginTop: 1,
              textDecoration: wasOnBench ? 'line-through' : 'none',
            }}>
              {fpts > 0 ? '+' : ''}{fpts.toFixed(1)}
            </div>
            {hasSave && (
              <div style={{ fontSize: 10, marginTop: 1 }} title="Save recorded">🔒</div>
            )}
          </div>
        )
      }

      return (
        <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
          {oppLabel}
        </span>
      )
    }
  }

  // Future game
  if (isStarting) {
    const indicator = startInfo.confirmed
        ? <span style={{ fontSize: 11 }}>✅</span>
        : <span style={{ fontSize: 10, fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--blue)', background: 'var(--blue-light)', borderRadius: 99, padding: '1px 5px' }}>P</span>
    return (
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--ink)' }}>
          {oppLabel}
        </div>
        <div style={{ fontSize: 11, marginTop: 1 }}>{indicator}</div>
      </div>
    )
  }

  // Future game, not starting
  return (
    <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
      {oppLabel}
    </span>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ScheduleGrid({
  pitchers, schedule, matchupDates,
  renderPrefix, renderSuffix,
  prefixHeaders, suffixHeaders,
  onRowClick,
  actualFpts,
  benchDays,
  actualSaves,
  savesData,
}: Props) {
  const today = todayISO()

  // Build the full date range for column headers
  const dates = useMemo(() => {
    if (matchupDates.length < 2) return []
    return buildDateRange(matchupDates[0], matchupDates[1])
  }, [matchupDates])

  if (dates.length === 0) return null

  const cellStyle: React.CSSProperties = {
    padding: '8px 6px',
    fontSize: 13,
    borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle',
    textAlign: 'center' as const,
    whiteSpace: 'nowrap' as const,
  }

  const headerStyle: React.CSSProperties = {
    padding: '8px 6px',
    fontSize: 10,
    fontFamily: 'var(--mono)',
    fontWeight: 500,
    color: 'var(--ink-3)',
    letterSpacing: '0.05em',
    borderBottom: '1px solid var(--border)',
    textAlign: 'center' as const,
    whiteSpace: 'nowrap' as const,
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            {/* Fixed left columns */}
            {prefixHeaders}
            <th style={{ ...headerStyle, textAlign: 'left', paddingLeft: 10, minWidth: 140 }}>Pitcher</th>
            <th style={{ ...headerStyle, minWidth: 44 }}>Team</th>
            <th style={{ ...headerStyle, minWidth: 44 }}>Slot</th>

            {/* Date columns — inserted between Slot and Starts */}
            {dates.map(date => {
              const isToday = date === today
              return (
                <th key={date} style={{
                  ...headerStyle,
                  minWidth: 54,
                  fontWeight: isToday ? 700 : 500,
                  color: isToday ? 'var(--ink)' : 'var(--ink-3)',
                  background: isToday ? 'var(--paper-2)' : 'transparent',
                  borderBottom: isToday
                    ? '2px solid var(--green-mid)'
                    : '1px solid var(--border)',
                }}>
                  {fmtDate(date)}
                  {isToday && (
                    <div style={{ fontSize: 8, letterSpacing: '0.08em', color: 'var(--green-mid)', marginTop: 1 }}>
                      TODAY
                    </div>
                  )}
                </th>
              )
            })}

            {/* Fixed right columns */}
            <th style={{ ...headerStyle, minWidth: 52 }}>{savesData ? 'Saves' : 'Starts'}</th>
            <th style={{ ...headerStyle, minWidth: 72 }}>Proj FPTS</th>
            {suffixHeaders}
          </tr>
        </thead>
        <tbody>
          {pitchers.map((pitcher, i) => {
            const isIL = pitcher.slot === 'IL'
            const rowStyle: React.CSSProperties = {
              opacity: isIL ? 0.5 : 1,
              cursor: onRowClick ? 'pointer' : 'default',
            }
            return (
              <tr
                key={i}
                style={rowStyle}
                onClick={() => onRowClick?.(i)}
              >
                {renderPrefix?.(pitcher, i)}

                {/* Pitcher name */}
                <td style={{ ...cellStyle, textAlign: 'left', paddingLeft: 10, fontWeight: 600 }}>
                  {pitcher.name}
                </td>

                {/* Team */}
                <td style={cellStyle}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>{pitcher.team}</span>
                </td>

                {/* Slot badge */}
                <td style={cellStyle}>
                  <Badge
                    label={pitcher.slot}
                    color={pitcher.slot === 'IL' ? 'red' : pitcher.slot === 'RP' ? 'amber' : 'blue'}
                  />
                </td>

                {/* Day cells */}
                {dates.map(date => {
                  const isToday = date === today
                  return (
                    <td key={date} style={{
                      ...cellStyle,
                      background: isToday ? 'var(--paper-2)' : 'transparent',
                    }}>
                      <DayCell
                        pitcher={pitcher}
                        date={date}
                        schedule={schedule}
                        today={today}
                        actualFpts={actualFpts}
                        benchDays={benchDays}
                        actualSaves={actualSaves}
                      />
                    </td>
                  )
                })}

                {/* Starts or Saves count */}
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700 }}>
                  {savesData
                    ? Object.values(savesData[pitcher.name] || {}).reduce((a, b) => a + b, 0)
                    : pitcher.starts}
                </td>

                {/* Proj FPTS */}
                <td style={{
                  ...cellStyle,
                  fontFamily: 'var(--mono)', fontWeight: 700,
                  color: pitcher.projFpts > 0 ? 'var(--green)' : 'var(--ink-3)',
                }}>
                  {pitcher.projFpts.toFixed(1)}
                </td>

                {renderSuffix?.(pitcher, i)}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}