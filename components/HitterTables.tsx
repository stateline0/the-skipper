// components/HitterTables.tsx
//
// Shared hitter Schedule/Stats tables used by both the Hitters page (My
// hitters) and the Free Agents page (FA hitters). Extracted from the original
// pages/hitters.tsx so the FA Pitchers/Hitters toggle can reuse them.
//
// Pass `showOwn` to render an Own% column (Free Agents view).

// ─── Types ──────────────────────────────────────────────────────────────────

export interface UIHitter {
  name: string
  team: string
  pos: string
  bats: string
  projG: number               // projected FPTS per game
  projFpts: number            // projected FPTS for the week
  avg: number; obp: number; slg: number
  hr: number; r: number; rbi: number; sb: number
  percentOwned?: number       // Free Agents view only
}

export interface DayGame {
  date: string
  off: boolean
  opp: string
  home: boolean
  proj: number
}

export type Weeks = Record<string, DayGame[]>

// ─── Date / format helpers ──────────────────────────────────────────────────

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
export const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

export function fmtDay(iso: string) {
  const [, m, d] = iso.split('-')
  const wd = WD[new Date(iso + 'T12:00:00Z').getUTCDay()]
  return { wd, md: `${MONTHS[parseInt(m) - 1]} ${parseInt(d)}` }
}
export function buildDateRange(start: string, end: string): string[] {
  const out: string[] = []
  const cur = new Date(start + 'T12:00:00Z')
  const last = new Date(end + 'T12:00:00Z')
  while (cur <= last) { out.push(cur.toISOString().slice(0, 10)); cur.setUTCDate(cur.getUTCDate() + 1) }
  return out
}
export function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
function slash(h: UIHitter) {
  const f = (n: number) => (n || 0).toFixed(3).replace(/^0/, '')
  return `${f(h.avg)}/${f(h.obp)}/${f(h.slg)}`
}

// ─── Badge ──────────────────────────────────────────────────────────────────

export function PosBadge({ pos }: { pos: string }) {
  const styles: Record<string, React.CSSProperties> = {
    C:    { background: 'var(--amber-light)', color: 'var(--amber)' },
    UTIL: { background: 'var(--green-light)', color: 'var(--green)' },
    DH:   { background: 'var(--green-light)', color: 'var(--green)' },
    BN:   { background: 'var(--paper-2)',     color: 'var(--ink-3)' },
    IL:   { background: 'var(--red-light)',   color: 'var(--red)' },
  }
  const infield = ['1B', '2B', '3B', 'SS', '2B/SS', '1B/3B']
  const style = styles[pos]
    || (infield.includes(pos) ? { background: 'var(--blue-light)', color: 'var(--blue)' }
    : pos === 'OF' ? { background: 'var(--green-light)', color: 'var(--green)' }
    : { background: 'var(--paper-2)', color: 'var(--ink-3)' })
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600, fontFamily: 'var(--mono)',
      padding: '2px 8px', borderRadius: 99, letterSpacing: '0.04em',
      whiteSpace: 'nowrap', minWidth: 44, textAlign: 'center', ...style,
    }}>{pos}</span>
  )
}

// ─── Schedule grid ──────────────────────────────────────────────────────────

export function HitterScheduleGrid({ hitters, weeks, weekDates, today, showOwn }: {
  hitters: UIHitter[]; weeks: Weeks; weekDates: string[]; today: string; showOwn?: boolean
}) {
  const headerStyle: React.CSSProperties = {
    padding: '8px 6px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
    color: 'var(--ink-3)', letterSpacing: '0.04em', borderBottom: '1px solid var(--border)',
    textAlign: 'center', whiteSpace: 'nowrap',
  }
  const cellStyle: React.CSSProperties = {
    padding: '8px 6px', fontSize: 13, borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle', textAlign: 'center', whiteSpace: 'nowrap',
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={{ ...headerStyle, minWidth: 50 }}>Pos</th>
            <th style={{ ...headerStyle, textAlign: 'left', paddingLeft: 10, minWidth: 150 }}>Hitter</th>
            {weekDates.map(date => {
              const isToday = date === today
              const { wd, md } = fmtDay(date)
              return (
                <th key={date} style={{
                  ...headerStyle, minWidth: 56,
                  fontWeight: isToday ? 700 : 500,
                  color: isToday ? 'var(--ink)' : 'var(--ink-3)',
                  background: isToday ? 'var(--paper-2)' : 'transparent',
                  borderBottom: isToday ? '2px solid var(--green-mid)' : '1px solid var(--border)',
                }}>
                  {md}
                  <div style={{ fontSize: 8, letterSpacing: '0.08em', marginTop: 1, color: isToday ? 'var(--green-mid)' : 'var(--ink-3)' }}>
                    {isToday ? 'TODAY' : wd.toUpperCase()}
                  </div>
                </th>
              )
            })}
            <th style={{ ...headerStyle, minWidth: 36 }}>G</th>
            <th style={{ ...headerStyle, minWidth: 60 }}>Proj</th>
            {showOwn && <th style={{ ...headerStyle, minWidth: 52 }}>Own%</th>}
          </tr>
        </thead>
        <tbody>
          {hitters.map(h => {
            const week = weeks[h.name] || []
            const isBench = h.pos === 'BN' || h.pos === 'IL'
            const games = week.filter(g => !g.off)
            const projTotal = games.reduce((a, g) => a + g.proj, 0)
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}><PosBadge pos={h.pos} /></td>
                <td style={{ ...cellStyle, textAlign: 'left', paddingLeft: 10 }}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                    {h.team}{h.bats ? ` · ${h.bats}HB` : ''}
                  </div>
                </td>
                {week.map(g => (
                  <td key={g.date} style={{ ...cellStyle, background: g.date === today ? 'var(--paper-2)' : 'transparent' }}>
                    <HitterDayCell g={g} />
                  </td>
                ))}
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700 }}>{games.length}</td>
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--green)' }}>
                  {projTotal.toFixed(1)}
                </td>
                {showOwn && (
                  <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
                    {h.percentOwned ?? 0}%
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function HitterDayCell({ g }: { g: DayGame }) {
  if (g.off) return <span style={{ color: 'var(--ink-3)', fontSize: 11 }}>—</span>
  const oppLabel = `${g.home ? '' : '@'}${g.opp}`
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--ink)' }}>{oppLabel}</div>
      <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, color: 'var(--ink-2)', marginTop: 1 }}>
        {g.proj.toFixed(1)}
      </div>
    </div>
  )
}

// ─── Stats table ──────────────────────────────────────────────────────────────

export function HitterStatsTable({ hitters, weeks, showOwn }: {
  hitters: UIHitter[]; weeks: Weeks; showOwn?: boolean
}) {
  const headerStyle: React.CSSProperties = {
    padding: '8px 10px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
    letterSpacing: '0.04em', color: 'var(--ink-3)', textTransform: 'uppercase',
    borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
  }
  const cellStyle: React.CSSProperties = {
    padding: '10px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', whiteSpace: 'nowrap',
  }
  const num = (extra?: React.CSSProperties): React.CSSProperties => ({ ...cellStyle, textAlign: 'center', fontFamily: 'var(--mono)', ...extra })
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={headerStyle}>Pos</th>
            <th style={{ ...headerStyle, textAlign: 'left' }}>Hitter</th>
            <th style={{ ...headerStyle, textAlign: 'left' }}>AVG / OBP / SLG</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>HR</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>R</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>RBI</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>SB</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>Proj/G</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>Proj wk</th>
            {showOwn && <th style={{ ...headerStyle, textAlign: 'center' }}>Own%</th>}
          </tr>
        </thead>
        <tbody>
          {hitters.map(h => {
            const week = weeks[h.name] || []
            const projWk = week.reduce((a, g) => a + g.proj, 0)
            const isBench = h.pos === 'BN' || h.pos === 'IL'
            const hasLine = h.avg || h.obp || h.slg || h.hr || h.r || h.rbi || h.sb
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}><PosBadge pos={h.pos} /></td>
                <td style={cellStyle}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                    {h.team}{h.bats ? ` · ${h.bats}HB` : ''}
                  </div>
                </td>
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)' }}>{hasLine ? slash(h) : '—'}</td>
                <td style={num()}>{h.hr || '—'}</td>
                <td style={num()}>{h.r || '—'}</td>
                <td style={num()}>{h.rbi || '—'}</td>
                <td style={num()}>{h.sb || '—'}</td>
                <td style={num({ fontWeight: 700 })}>{h.projG.toFixed(1)}</td>
                <td style={num({ fontWeight: 700, color: 'var(--green)' })}>{projWk.toFixed(1)}</td>
                {showOwn && <td style={num({ color: 'var(--ink-3)', fontSize: 12 })}>{h.percentOwned ?? 0}%</td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// Map an /api/hitters hitter record + matchup date range into {UIHitter, weeks entry}.
export function hitterFromPayload(h: any, dates: string[]): { hitter: UIHitter; days: DayGame[] } {
  const byDate: Record<string, any> = {}
  ;(h.days || []).forEach((d: any) => { byDate[d.date] = d })
  const days = dates.map(date => {
    const d = byDate[date]
    return d
      ? { date, off: false, opp: d.opp, home: d.home, proj: d.proj }
      : { date, off: true, opp: '', home: false, proj: 0 }
  })
  const s = h.seasonStats || {}
  return {
    hitter: {
      name: h.name, team: h.team, pos: h.pos, bats: h.bats || '',
      projG: h.projPerGame || 0, projFpts: h.projFpts || 0,
      avg: s.avg || 0, obp: s.obp || 0, slg: s.slg || 0,
      hr: s.hr || 0, r: s.r || 0, rbi: s.rbi || 0, sb: s.sb || 0,
      percentOwned: h.percentOwned,
    },
    days,
  }
}
