// components/HitterTables.tsx
//
// Shared hitter Schedule/Stats tables used by both the Hitters page (My
// hitters) and the Free Agents page (FA hitters). Each table manages its own
// column sorting internally, so callers don't wire anything. The Stats table
// includes an advanced (Savant) column group: xBA/xSLG/xwOBA + Barrel%/Whiff%.
//
// Pass `showOwn` to render an Own% column (Free Agents view).

import { useMemo, useState } from 'react'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface HitterAdvanced {
  xba?: number; xslg?: number; xwoba?: number; wobaDiff?: number
  barrelPct?: number; hardHitPct?: number; evAvg?: number
}

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
  adv?: HitterAdvanced        // advanced Savant block (Stats tab)
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
const rate = (n?: number) => (n === undefined ? '—' : n.toFixed(3).replace(/^0/, ''))
const pct = (n?: number) => (n === undefined ? '—' : `${n.toFixed(1)}%`)

// ─── Sorting ──────────────────────────────────────────────────────────────────

type SortDir = 'asc' | 'desc'

// Numeric sort value for a hitter under a given column key. Returns null for an
// absent value (sinks to the bottom regardless of direction).
function sortVal(h: UIHitter, weeks: Weeks, key: string): number | null {
  const week = weeks[h.name] || []
  switch (key) {
    case 'g':      return week.filter(g => !g.off).length
    case 'projWk': return week.reduce((a, g) => a + g.proj, 0)
    case 'projG':  return h.projG
    case 'own':    return h.percentOwned ?? null
    case 'ops':    return (h.obp || 0) + (h.slg || 0)
    case 'hr':     return h.hr
    case 'r':      return h.r
    case 'rbi':    return h.rbi
    case 'sb':     return h.sb
    case 'xba':    return h.adv?.xba ?? null
    case 'xslg':   return h.adv?.xslg ?? null
    case 'xwoba':  return h.adv?.xwoba ?? null
    case 'barrel': return h.adv?.barrelPct ?? null
    case 'ev':     return h.adv?.evAvg ?? null
    default:
      // A date column (YYYY-MM-DD): that day's projection (off day → null).
      if (/^\d{4}-\d{2}-\d{2}$/.test(key)) {
        const g = week.find(x => x.date === key)
        return g && !g.off ? g.proj : null
      }
      return null
  }
}

function useSortedHitters(hitters: UIHitter[], weeks: Weeks) {
  const [key, setKey] = useState<string | null>(null)   // null → caller's order
  const [dir, setDir] = useState<SortDir>('desc')

  function onSort(k: string) {
    if (k === key) setDir(d => (d === 'desc' ? 'asc' : 'desc'))
    else { setKey(k); setDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!key) return hitters
    const arr = [...hitters]
    arr.sort((a, b) => {
      if (key === 'name') {
        const c = a.name.localeCompare(b.name)
        return dir === 'asc' ? c : -c
      }
      const av = sortVal(a, weeks, key)
      const bv = sortVal(b, weeks, key)
      if (av === null && bv === null) return 0
      if (av === null) return 1          // missing sinks
      if (bv === null) return -1
      return dir === 'desc' ? bv - av : av - bv
    })
    return arr
  }, [hitters, weeks, key, dir])

  return { sorted, key, dir, onSort }
}

function SortTh({ label, col, sortKey, sortDir, onSort, align = 'center', minWidth, title }: {
  label: string; col: string; sortKey: string | null; sortDir: SortDir
  onSort: (k: string) => void; align?: 'left' | 'center'; minWidth?: number; title?: string
}) {
  const active = sortKey === col
  return (
    <th
      onClick={() => onSort(col)}
      title={title}
      style={{
        padding: '8px 10px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
        letterSpacing: '0.04em', textTransform: 'uppercase',
        borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
        textAlign: align, cursor: 'pointer', userSelect: 'none',
        color: active ? 'var(--ink)' : 'var(--ink-3)', minWidth,
      }}
    >
      {label}{active ? (sortDir === 'desc' ? ' ↓' : ' ↑') : ''}
    </th>
  )
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
  const { sorted, key, dir, onSort } = useSortedHitters(hitters, weeks)
  const headerStyle: React.CSSProperties = {
    padding: '8px 6px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
    color: 'var(--ink-3)', letterSpacing: '0.04em', borderBottom: '1px solid var(--border)',
    textAlign: 'center', whiteSpace: 'nowrap',
  }
  const cellStyle: React.CSSProperties = {
    padding: '8px 6px', fontSize: 13, borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle', textAlign: 'center', whiteSpace: 'nowrap',
  }
  const arrow = (col: string) => (key === col ? (dir === 'desc' ? ' ↓' : ' ↑') : '')
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={{ ...headerStyle, minWidth: 50 }}>Pos</th>
            <th onClick={() => onSort('name')} style={{ ...headerStyle, textAlign: 'left', paddingLeft: 10, minWidth: 150, cursor: 'pointer', userSelect: 'none', color: key === 'name' ? 'var(--ink)' : 'var(--ink-3)' }}>
              Hitter{arrow('name')}
            </th>
            {weekDates.map(date => {
              const isToday = date === today
              const { wd, md } = fmtDay(date)
              const active = key === date
              return (
                <th key={date} onClick={() => onSort(date)} style={{
                  ...headerStyle, minWidth: 56, cursor: 'pointer', userSelect: 'none',
                  fontWeight: isToday ? 700 : 500,
                  color: (isToday || active) ? 'var(--ink)' : 'var(--ink-3)',
                  background: isToday ? 'var(--paper-2)' : 'transparent',
                  borderBottom: isToday ? '2px solid var(--green-mid)' : '1px solid var(--border)',
                }}>
                  {md}{arrow(date)}
                  <div style={{ fontSize: 8, letterSpacing: '0.08em', marginTop: 1, color: isToday ? 'var(--green-mid)' : 'var(--ink-3)' }}>
                    {isToday ? 'TODAY' : wd.toUpperCase()}
                  </div>
                </th>
              )
            })}
            <th onClick={() => onSort('g')} style={{ ...headerStyle, minWidth: 36, cursor: 'pointer', userSelect: 'none', color: key === 'g' ? 'var(--ink)' : 'var(--ink-3)' }}>G{arrow('g')}</th>
            <th onClick={() => onSort('projWk')} style={{ ...headerStyle, minWidth: 60, cursor: 'pointer', userSelect: 'none', color: key === 'projWk' ? 'var(--ink)' : 'var(--ink-3)' }}>Proj{arrow('projWk')}</th>
            {showOwn && <th onClick={() => onSort('own')} style={{ ...headerStyle, minWidth: 52, cursor: 'pointer', userSelect: 'none', color: key === 'own' ? 'var(--ink)' : 'var(--ink-3)' }}>Own%{arrow('own')}</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map(h => {
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

// ─── Stats table (with advanced Savant columns) ───────────────────────────────

export function HitterStatsTable({ hitters, weeks, showOwn }: {
  hitters: UIHitter[]; weeks: Weeks; showOwn?: boolean
}) {
  const { sorted, key, dir, onSort } = useSortedHitters(hitters, weeks)
  const cellStyle: React.CSSProperties = {
    padding: '10px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', whiteSpace: 'nowrap',
  }
  const num = (extra?: React.CSSProperties): React.CSSProperties => ({ ...cellStyle, textAlign: 'center', fontFamily: 'var(--mono)', ...extra })
  const th = (label: string, col: string, align: 'left' | 'center' = 'center', title?: string) =>
    <SortTh label={label} col={col} sortKey={key} sortDir={dir} onSort={onSort} align={align} title={title} />
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ padding: '8px 10px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.04em', color: 'var(--ink-3)', textTransform: 'uppercase', borderBottom: '1px solid var(--border)' }}>Pos</th>
            {th('Hitter', 'name', 'left')}
            {th('AVG / OBP / SLG', 'ops', 'left', 'Sorted by OPS (OBP + SLG)')}
            {th('HR', 'hr')}
            {th('R', 'r')}
            {th('RBI', 'rbi')}
            {th('SB', 'sb')}
            {th('xBA', 'xba')}
            {th('xSLG', 'xslg')}
            {th('xwOBA', 'xwoba')}
            {th('Brl%', 'barrel')}
            {th('EV', 'ev')}
            {th('Proj/G', 'projG')}
            {th('Proj wk', 'projWk')}
            {showOwn && th('Own%', 'own')}
          </tr>
        </thead>
        <tbody>
          {sorted.map(h => {
            const week = weeks[h.name] || []
            const projWk = week.reduce((a, g) => a + g.proj, 0)
            const isBench = h.pos === 'BN' || h.pos === 'IL'
            const hasLine = h.avg || h.obp || h.slg || h.hr || h.r || h.rbi || h.sb
            const adv = h.adv || {}
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
                <td style={num({ color: 'var(--ink-2)' })}>{rate(adv.xba)}</td>
                <td style={num({ color: 'var(--ink-2)' })}>{rate(adv.xslg)}</td>
                <td style={num({ color: 'var(--ink-2)' })}>{rate(adv.xwoba)}</td>
                <td style={num({ color: 'var(--ink-2)' })}>{pct(adv.barrelPct)}</td>
                <td style={num({ color: 'var(--ink-2)' })}>{adv.evAvg === undefined ? '—' : adv.evAvg.toFixed(1)}</td>
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
      adv: h.advanced || undefined,
    },
    days,
  }
}
