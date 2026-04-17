// components/ScheduleGrid.tsx
// Shared schedule grid used by both My Team and Free Agents pages.
// Shows a day-by-day breakdown of each pitcher's starts for the matchup period.

import { useMemo, useEffect } from 'react'
import ProjectionTooltip, { ProjectionBreakdown } from './ProjectionTooltip'

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
  projBlend?: number
  fptsPerStart?: number
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
  game_detail?: string  // "Bot 5th", "Top 3rd", "Final"
  score?: string        // "3-2" (from this team's perspective)
}

interface LiveStats {
  fpts: number
  stats: {
    ip: number; so: number; h: number; bb: number; er: number
    hb: number; w: number; l: number; sv: number
  }
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
  // Per-start projection: { "Garrett Crochet": 18.2 } — shown in start cells
  fptsPerStart?: Record<string, number>
  // Locked projections from KV: { "Garrett Crochet": { "2026-04-07": 14.2 } }
  // Used for past/today cells — frozen at game time, never recalculated
  lockedProjections?: Record<string, Record<string, number>>
  // Sortable column support
  sortCol?: string
  sortDir?: 'asc' | 'desc'
  onSortChange?: (col: string) => void
  // Projection model breakdown for tooltip: { "Garrett Crochet": { seasonBase, ... } }
  projectionDetails?: Record<string, ProjectionBreakdown>
  // Live stats for today: { "Garrett Crochet": { fpts, stats: {ip, so, h, ...} } }
  liveStats?: Record<string, LiveStats>
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

function DayCell({ pitcher, date, schedule, today, actualFpts, benchDays, actualSaves, fptsPerStart, lockedProjections, projectionDetails, liveStats }: {
  pitcher: Pitcher
  date: string
  schedule: Schedule
  today: string
  actualFpts?: Record<string, Record<string, number>>
  benchDays?: Record<string, string[]>
  actualSaves?: Record<string, Record<string, number>>
  fptsPerStart?: Record<string, number>
  lockedProjections?: Record<string, Record<string, number>>
  projectionDetails?: Record<string, ProjectionBreakdown>
  liveStats?: Record<string, LiveStats>
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
      const isLive = isToday && gameInfo.status === 'in_progress'
      const isFinal = gameInfo.status === 'final'
      // A start that's already in the past or is happening today is locked in —
      // show the green confirmed indicator regardless of the original probables source.
      // (`startInfo.confirmed` reflects whether MLB Stats API listed this as a confirmed
      // probable, which is a forward-looking signal — once the game is happening or has
      // happened, that distinction stops being meaningful to the user.)
      const isLockedIn = startInfo.confirmed || isPast || isToday
      const indicator = isLockedIn
          ? <span style={{ fontSize: 10, color: 'var(--green)' }}>✓</span>
          : <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--blue)', background: 'var(--blue-light)', borderRadius: 99, padding: '0px 4px' }}>P</span>
      const color = isLockedIn ? 'var(--green)' : 'var(--ink-3)'
      const fpts = actualFpts?.[pitcher.name]?.[date]
      const hasFpts = fpts !== undefined && fpts !== 0
      const wasOnBench = benchDays?.[pitcher.name]?.includes(date) ?? false
      const perStart = lockedProjections?.[pitcher.name]?.[date] ?? fptsPerStart?.[pitcher.name]
      const breakdown = projectionDetails?.[pitcher.name]
      const startDetail = breakdown?.starts?.find((s: any) => s.date === date)
      // Use the adjusted per-start projection (includes wOBA, park, W/L factors)
      // Falls back to locked projection, then base rate
      const displayProj = startDetail?.proj ?? perStart
      const live = liveStats?.[pitcher.name]

      return (
        <div style={{ textAlign: 'center' }}>
          {/* Live badge — red pulsing dot */}
          {isLive && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3, marginBottom: 2 }}>
              <span style={{
                display: 'inline-block', width: 6, height: 6,
                borderRadius: '50%', background: 'var(--red)',
                animation: 'livePulse 1.4s ease-in-out infinite',
              }} />
              <span style={{ fontSize: 8, fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--red)', letterSpacing: '0.08em' }}>
                LIVE
              </span>
            </div>
          )}

          {/* Opponent + confirmed/projected indicator */}
          <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
            {oppLabel} {indicator}
          </div>

          {/* Score + inning for live/final games */}
          {(isLive || isFinal) && gameInfo.score && (
            <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 600, color: isLive ? 'var(--ink)' : 'var(--ink-3)', marginTop: 1 }}>
              {gameInfo.score}
              {isLive && gameInfo.game_detail && (
                <span style={{ fontSize: 8, color: 'var(--ink-3)', marginLeft: 3 }}>
                  {gameInfo.game_detail}
                </span>
              )}
            </div>
          )}

          {/* Live FPTS (from ESPN live stats) */}
          {isLive && live && (
            <div style={{
              fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700,
              color: wasOnBench ? 'var(--ink-3)' : live.fpts > 0 ? 'var(--green)' : live.fpts < 0 ? 'var(--red)' : 'var(--ink-3)',
              marginTop: 2,
              textDecoration: wasOnBench ? 'line-through' : 'none',
            }}>
              {live.fpts > 0 ? '+' : ''}{live.fpts.toFixed(1)}
            </div>
          )}

          {/* Live stat line: IP, K, H, BB, ER */}
          {isLive && live && (
            <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginTop: 1, letterSpacing: '0.02em' }}>
              {live.stats.ip.toFixed(1)}IP {live.stats.so}K {live.stats.h}H {live.stats.bb}BB {live.stats.er}ER
            </div>
          )}

          {/* Actual FPTS (for completed games — same as before) */}
          {!isLive && hasFpts && (
            <div style={{
              fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 700,
              color: wasOnBench ? 'var(--ink-3)' : fpts > 0 ? 'var(--green)' : 'var(--red)',
              marginTop: 1,
              textDecoration: wasOnBench ? 'line-through' : 'none',
            }}>
              {fpts > 0 ? '+' : ''}{fpts.toFixed(1)}
            </div>
          )}

          {/* Projection — now wrapped in tooltip (fixes hoverable today projection) */}
          {displayProj !== undefined && (hasFpts || isToday) && (
            <ProjectionTooltip breakdown={breakdown} startDate={date}>
              <div style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginTop: 1, cursor: 'help' }}>
                (proj: {displayProj >= 0 ? '+' : ''}{displayProj.toFixed(1)})
              </div>
            </ProjectionTooltip>
          )}

          {actualSaves?.[pitcher.name]?.[date] && (
            <div style={{ fontSize: 10, marginTop: 1 }} title="Save recorded">🔒</div>
          )}
        </div>
      )
    } else {
      // Team played but pitcher didn't start — still show FPTS if they appeared (e.g. relievers)
      const isLive = isToday && gameInfo.status === 'in_progress'
      const fpts = actualFpts?.[pitcher.name]?.[date]
      const hasFpts = fpts !== undefined && fpts !== 0
      const wasOnBench = benchDays?.[pitcher.name]?.includes(date) ?? false
      const hasSave = !!actualSaves?.[pitcher.name]?.[date]
      const live = liveStats?.[pitcher.name]

      // Show live stats for relievers who have entered a live game
      if (isLive && live) {
        return (
          <div style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3, marginBottom: 2 }}>
              <span style={{
                display: 'inline-block', width: 5, height: 5,
                borderRadius: '50%', background: 'var(--red)',
                animation: 'livePulse 1.4s ease-in-out infinite',
              }} />
              <span style={{ fontSize: 7, fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--red)', letterSpacing: '0.08em' }}>
                LIVE
              </span>
            </div>
            <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
              {oppLabel}
            </span>
            <div style={{
              fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 700,
              color: wasOnBench ? 'var(--ink-3)' : live.fpts > 0 ? 'var(--green)' : live.fpts < 0 ? 'var(--red)' : 'var(--ink-3)',
              marginTop: 1,
              textDecoration: wasOnBench ? 'line-through' : 'none',
            }}>
              {live.fpts > 0 ? '+' : ''}{live.fpts.toFixed(1)}
            </div>
            <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginTop: 1, letterSpacing: '0.02em' }}>
              {live.stats.ip.toFixed(1)}IP {live.stats.so}K {live.stats.h}H {live.stats.bb}BB {live.stats.er}ER
            </div>
            {hasSave && (
              <div style={{ fontSize: 10, marginTop: 1 }} title="Save recorded">🔒</div>
            )}
          </div>
        )
      }

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
        ? <span style={{ fontSize: 10 }}>✅</span>
        : <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'var(--mono)', color: 'var(--blue)', background: 'var(--blue-light)', borderRadius: 99, padding: '0px 4px' }}>P</span>
    const breakdown = projectionDetails?.[pitcher.name]
    const startDetail = breakdown?.starts?.find(s => s.date === date)
    const perStart = startDetail?.proj ?? fptsPerStart?.[pitcher.name]
    return (
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--ink)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
          {oppLabel} {indicator}
        </div>
        {perStart !== undefined && (
          <ProjectionTooltip breakdown={breakdown} startDate={date}>
            <div style={{ fontSize: 9, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginTop: 1 }}>
              {perStart >= 0 ? '+' : ''}{perStart.toFixed(1)}
            </div>
          </ProjectionTooltip>
        )}
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
  fptsPerStart,
  lockedProjections,
  sortCol,
  sortDir,
  onSortChange,
  projectionDetails,
  liveStats,
}: Props) {
  const today = todayISO()

  // Inject keyframes for pulsing live indicator (once per page load)
  useEffect(() => {
    if (document.getElementById('skipper-live-pulse')) return
    const style = document.createElement('style')
    style.id = 'skipper-live-pulse'
    style.textContent = `
      @keyframes livePulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.4; transform: scale(0.75); }
      }
    `
    document.head.appendChild(style)
  }, [])

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

  // Returns sort arrow indicator for a given column key
  function sortIndicator(col: string) {
    if (sortCol !== col) return null
    return <span style={{ marginLeft: 3 }}>{sortDir === 'desc' ? '↓' : '↑'}</span>
  }

  // Style override for sortable headers
  const sortableHeader = (col: string): React.CSSProperties => ({
    ...headerStyle,
    cursor: onSortChange ? 'pointer' : 'default',
    color: sortCol === col ? 'var(--ink)' : 'var(--ink-3)',
    userSelect: 'none',
  })

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            {/* Fixed left columns */}
            {prefixHeaders}
            <th
              style={{ ...sortableHeader('name'), textAlign: 'left', paddingLeft: 10, minWidth: 140 }}
              onClick={() => onSortChange?.('name')}
            >
              Pitcher{sortIndicator('name')}
            </th>
            <th style={{ ...headerStyle, minWidth: 44 }}>Team</th>
            <th style={{ ...headerStyle, minWidth: 44 }}>Slot</th>

            {/* Date columns — inserted between Slot and Starts */}
            {dates.map(date => {
              const isToday = date === today
              const isActiveSort = sortCol === date
              return (
                <th
                  key={date}
                  onClick={() => onSortChange?.(date)}
                  style={{
                    ...headerStyle,
                    minWidth: 54,
                    fontWeight: isToday || isActiveSort ? 700 : 500,
                    color: isToday || isActiveSort ? 'var(--ink)' : 'var(--ink-3)',
                    background: isToday ? 'var(--paper-2)' : 'transparent',
                    borderBottom: isToday
                      ? '2px solid var(--green-mid)'
                      : '1px solid var(--border)',
                    cursor: onSortChange ? 'pointer' : 'default',
                    userSelect: 'none',
                  }}
                >
                  {fmtDate(date)}{sortIndicator(date)}
                  {isToday && (
                    <div style={{ fontSize: 8, letterSpacing: '0.08em', color: 'var(--green-mid)', marginTop: 1 }}>
                      TODAY
                    </div>
                  )}
                </th>
              )
            })}

            {/* Fixed right columns */}
            <th
              style={{ ...sortableHeader('starts'), minWidth: 52 }}
              onClick={() => onSortChange?.('starts')}
            >
              {savesData ? 'Saves' : 'Starts'}{sortIndicator('starts')}
            </th>
            {actualFpts && (
              <th
                style={{ ...sortableHeader('actFpts'), minWidth: 72 }}
                onClick={() => onSortChange?.('actFpts')}
              >
                Act FPTS{sortIndicator('actFpts')}
              </th>
            )}
            <th
              style={{ ...sortableHeader('projFpts'), minWidth: 72 }}
              onClick={() => onSortChange?.('projFpts')}
            >
              Proj FPTS{sortIndicator('projFpts')}
            </th>
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
                        fptsPerStart={fptsPerStart}
                        lockedProjections={lockedProjections}
                        projectionDetails={projectionDetails}
                        liveStats={liveStats}
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

                {/* Actual FPTS total — only rendered when actualFpts prop is provided */}
                {actualFpts && (() => {
                  const total = Object.values(actualFpts[pitcher.name] || {}).reduce((a, b) => a + b, 0)
                  return (
                    <td style={{
                      ...cellStyle,
                      fontFamily: 'var(--mono)', fontWeight: 700,
                      color: total > 0 ? 'var(--green)' : total < 0 ? 'var(--red)' : 'var(--ink-3)',
                    }}>
                      {total !== 0 ? (total > 0 ? '+' : '') + total.toFixed(1) : '—'}
                    </td>
                  )
                })()}

                {/* Proj FPTS */}
                <td style={{
                  ...cellStyle,
                  fontFamily: 'var(--mono)', fontWeight: 700,
                  color: pitcher.projFpts > 0 ? 'var(--green)' : 'var(--ink-3)',
                }}>
                  <ProjectionTooltip breakdown={projectionDetails?.[pitcher.name]}>
                    <span>
                      {pitcher.projFpts.toFixed(1)}
                      {pitcher.projBlend !== undefined && pitcher.projFpts > 0 && (
                        <div style={{
                          fontSize: 9, fontWeight: 500,
                          color: 'var(--ink-3)', marginTop: 2,
                          letterSpacing: '0.02em',
                        }}>
                          {Math.round(pitcher.projBlend * 100)}% &apos;26
                        </div>
                      )}
                    </span>
                  </ProjectionTooltip>
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