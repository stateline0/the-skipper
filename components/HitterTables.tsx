// components/HitterTables.tsx
//
// Shared hitter Schedule/Stats tables used by both the Hitters page (My
// hitters) and the Free Agents page (FA hitters). Each table manages its own
// column sorting internally, so callers don't wire anything. The Stats table
// includes an advanced (Savant) column group: xBA/xSLG/xwOBA + Barrel%/Whiff%.
//
// Pass `showOwn` to render an Own% column (Free Agents view).

import { useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

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
  il?: string                 // typed injury label (IL10/IL15/IL60/DTD/SUSP)
  estReturn?: string          // est. return date (YYYY-MM-DD) — Phase B injuries feed
  injuryDetail?: string       // injury descriptor for the IL tooltip, e.g. "Right Quadriceps (Strain)"
  adv?: HitterAdvanced        // advanced Savant block (Stats tab)
}

export interface DayFactor { label: string; mult: number }

export interface DayGame {
  date: string
  off: boolean
  opp: string
  home: boolean
  proj: number
  oppHand?: 'L' | 'R' | null    // opposing starter throws (platoon)
  oppStarter?: string
  base?: number                 // pre-matchup per-game base
  factors?: DayFactor[]         // matchup adjustments (platoon, …) for the popover
  status?: string               // "scheduled" | "in_progress" | "final"
  actual?: number | null        // actual/live FPTS for played games
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
    case 'act': {
      const a = week.filter(g => !g.off && g.actual != null)
      return a.length ? a.reduce((s, g) => s + (g.actual || 0), 0) : null
    }
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

function SortTh({ label, col, sortKey, sortDir, onSort, align = 'center', minWidth, title, sub }: {
  label: string; col: string; sortKey: string | null; sortDir: SortDir
  onSort: (k: string) => void; align?: 'left' | 'center'; minWidth?: number
  title?: string; sub?: string
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
      {sub && (
        <div style={{ fontSize: 8, fontWeight: 400, color: 'var(--ink-3)', marginTop: 1, letterSpacing: 0, textTransform: 'none' }}>
          lg {sub}
        </div>
      )}
    </th>
  )
}

// ─── Badge ──────────────────────────────────────────────────────────────────

const POS_STYLE: Record<string, React.CSSProperties> = {
  C:    { background: 'var(--amber-light)', color: 'var(--amber)' },
  UTIL: { background: 'var(--green-light)', color: 'var(--green)' },
  DH:   { background: 'var(--green-light)', color: 'var(--green)' },
  BN:   { background: 'var(--paper-2)',     color: 'var(--ink-3)' },
  IL:   { background: 'var(--red-light)',   color: 'var(--red)' },
  // Pitcher eligibility (PosTags is reused for SP/RP pills on the pitcher
  // pages); colors mirror the Slot-column badge.
  SP:   { background: 'var(--blue-light)',  color: 'var(--blue)' },
  RP:   { background: 'var(--amber-light)', color: 'var(--amber)' },
}
const INFIELD = ['1B', '2B', '3B', 'SS', '2B/SS', '1B/3B']

function posColor(pos: string): React.CSSProperties {
  return POS_STYLE[pos]
    || (INFIELD.includes(pos) ? { background: 'var(--blue-light)', color: 'var(--blue)' }
    : pos === 'OF' ? { background: 'var(--green-light)', color: 'var(--green)' }
    : { background: 'var(--paper-2)', color: 'var(--ink-3)' })
}

// Multi-position eligibility as separate compact pills (e.g. "1B/OF" → 1B OF),
// shown on the hitter name sub-line in place of a dedicated Pos column.
export function PosTags({ pos }: { pos: string }) {
  const parts = pos.split('/').map(s => s.trim()).filter(Boolean)
  if (parts.length === 0) return null
  return (
    <span style={{ display: 'inline-flex', gap: 3, flexWrap: 'wrap', verticalAlign: 'middle' }}>
      {parts.map((p, i) => (
        <span key={i} style={{
          display: 'inline-block', fontSize: 9, fontWeight: 700, fontFamily: 'var(--mono)',
          padding: '1px 5px', borderRadius: 99, letterSpacing: '0.03em',
          whiteSpace: 'nowrap', ...posColor(p),
        }}>{p}</span>
      ))}
    </span>
  )
}

// Format an ISO date (YYYY-MM-DD) as "Jun 26" for the IL tooltip.
function fmtReturn(iso?: string): string | null {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const [, m, d] = iso.split('-')
  return `${MONTHS[parseInt(m) - 1]} ${parseInt(d)}`
}

// Injury-status pill on the name sub-line (IL10/IL15/IL60/DTD/SUSP). IL grades
// are red (projection zeroed until the return date); DTD/SUSP are amber (still
// projecting). Self-guarding: only injury statuses render — anything else
// (Active, Dropped, undefined) yields nothing. When an est. return date and/or
// injury detail are known (Phase B), tapping the pill opens a popover
// ("Est. return Jun 26" + injury detail). The popover renders through a portal
// to <body> so it escapes the IL row's dimming (opacity:0.55 would otherwise
// wash it out) and the table's horizontal scroll clipping.
export function IlPill({ status, estReturn, detail }: {
  status?: string; estReturn?: string; detail?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  if (!status) return null
  const isIL = status.startsWith('IL')
  if (!isIL && status !== 'DTD' && status !== 'SUSP') return null
  const style = isIL
    ? { background: 'var(--red-light)', color: 'var(--red)' }
    : { background: 'var(--amber-light)', color: 'var(--amber)' }
  const pillStyle: React.CSSProperties = {
    display: 'inline-block', fontSize: 9, fontWeight: 700, fontFamily: 'var(--mono)',
    padding: '1px 5px', borderRadius: 99, letterSpacing: '0.03em',
    whiteSpace: 'nowrap', ...style,
  }
  const ret = fmtReturn(estReturn)
  // No extra info → a plain, non-interactive pill.
  if (!ret && !detail) {
    return <span style={pillStyle}>{status}</span>
  }
  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (pos) { setPos(null); return }
    const r = ref.current?.getBoundingClientRect()
    if (r) setPos({ top: r.bottom + 4, left: r.left })
  }
  return (
    <span ref={ref} onClick={toggle} style={{ ...pillStyle, cursor: 'pointer' }}>
      {status}
      {pos && typeof document !== 'undefined' && createPortal(
        <>
          {/* Tap-anywhere backdrop to dismiss (touch-friendly, no listeners). */}
          <div onClick={(e) => { e.stopPropagation(); setPos(null) }}
               style={{ position: 'fixed', inset: 0, zIndex: 1000 }} />
          <div onClick={(e) => e.stopPropagation()} style={{
            position: 'fixed', top: pos.top, left: pos.left, zIndex: 1001,
            background: 'var(--white)', border: '1px solid var(--border-strong)',
            borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)', padding: '8px 10px',
            fontFamily: 'var(--mono)', fontSize: 11, whiteSpace: 'nowrap', textAlign: 'left',
            color: 'var(--ink-2)',
          }}>
            {ret && <div style={{ fontWeight: 700, color: 'var(--ink)' }}>Est. return {ret}</div>}
            {detail && <div style={{ marginTop: ret ? 2 : 0 }}>{detail}</div>}
          </div>
        </>,
        document.body,
      )}
    </span>
  )
}

// ─── Schedule grid ──────────────────────────────────────────────────────────

export function HitterScheduleGrid({ hitters, weeks, weekDates, today, showOwn, actualsTracked }: {
  hitters: UIHitter[]; weeks: Weeks; weekDates: string[]; today: string
  showOwn?: boolean; actualsTracked?: boolean
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
            <th onClick={() => onSort('name')} style={{ ...headerStyle, textAlign: 'left', paddingLeft: 10, minWidth: 170, cursor: 'pointer', userSelect: 'none', color: key === 'name' ? 'var(--ink)' : 'var(--ink-3)' }}>
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
            {actualsTracked && <th onClick={() => onSort('act')} style={{ ...headerStyle, minWidth: 56, cursor: 'pointer', userSelect: 'none', color: key === 'act' ? 'var(--ink)' : 'var(--ink-3)' }}>Act{arrow('act')}</th>}
            <th onClick={() => onSort('projWk')} style={{ ...headerStyle, minWidth: 60, cursor: 'pointer', userSelect: 'none', color: key === 'projWk' ? 'var(--ink)' : 'var(--ink-3)' }}>Proj{arrow('projWk')}</th>
            {showOwn && <th onClick={() => onSort('own')} style={{ ...headerStyle, minWidth: 52, cursor: 'pointer', userSelect: 'none', color: key === 'own' ? 'var(--ink)' : 'var(--ink-3)' }}>Own%{arrow('own')}</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map(h => {
            const week = weeks[h.name] || []
            const isBench = h.pos === 'BN' || h.pos === 'IL' || !!h.il
            const games = week.filter(g => !g.off)
            const projTotal = games.reduce((a, g) => a + g.proj, 0)
            const actGames = games.filter(g => g.actual != null)
            const actTotal = actGames.reduce((a, g) => a + (g.actual || 0), 0)
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={{ ...cellStyle, textAlign: 'left', paddingLeft: 10 }}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', marginTop: 2 }}>
                    <PosTags pos={h.pos} />
                    <IlPill status={h.il} estReturn={h.estReturn} detail={h.injuryDetail} />
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                      {h.team}{h.bats ? ` · ${h.bats}HB` : ''}
                    </span>
                  </div>
                </td>
                {week.map(g => (
                  <td key={g.date} style={{ ...cellStyle, background: g.date === today ? 'var(--paper-2)' : 'transparent' }}>
                    <HitterDayCell g={g} actualsTracked={actualsTracked} />
                  </td>
                ))}
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700 }}>{games.length}</td>
                {actualsTracked && (
                  <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700, color: actGames.length ? (actTotal >= 0 ? 'var(--green)' : 'var(--red)') : 'var(--ink-3)' }}>
                    {actGames.length ? actTotal.toFixed(1) : '—'}
                  </td>
                )}
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

function HitterDayCell({ g, actualsTracked }: { g: DayGame; actualsTracked?: boolean }) {
  const [open, setOpen] = useState(false)
  if (g.off) return <span style={{ color: 'var(--ink-3)', fontSize: 11 }}>—</span>
  const oppLabel = `${g.home ? '' : '@'}${g.opp}`
  // Only treat games as actual/DNP when actuals are tracked for this view
  // (rostered hitters). For free agents we have no actuals, so always project.
  const played = !!actualsTracked && (g.status === 'final' || g.status === 'in_progress')
  const live = !!actualsTracked && g.status === 'in_progress'
  const showActual = played && g.actual != null
  const dnp = !!actualsTracked && g.status === 'final' && g.actual == null   // played, hitter didn't appear
  const hasDetail = g.base !== undefined
  // Projection edge arrow vs the pre-matchup base (only shown on projections).
  const up = g.base !== undefined && g.proj > g.base
  const down = g.base !== undefined && g.proj < g.base
  return (
    <div
      style={{ position: 'relative', textAlign: 'center', cursor: hasDetail ? 'help' : 'default', opacity: dnp ? 0.6 : 1 }}
      onMouseEnter={() => hasDetail && setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onClick={() => hasDetail && setOpen(o => !o)}
    >
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--ink)' }}>
        {oppLabel}
        {live && <span style={{ fontSize: 8, fontWeight: 700, color: 'var(--red)', marginLeft: 3, letterSpacing: '0.06em' }}>● LIVE</span>}
        {!played && g.oppHand && (
          <span style={{ fontSize: 9, fontWeight: 500, color: g.oppHand === 'L' ? 'var(--amber)' : 'var(--ink-3)', marginLeft: 3 }}>
            {g.oppHand}HP
          </span>
        )}
      </div>
      {showActual ? (
        // Actual / live — bold, signed, saturated — with the projection beneath
        // it so projection-vs-actual is visible at a glance.
        <>
          <div style={{ fontSize: 12, fontFamily: 'var(--mono)', fontWeight: 700, color: g.actual! > 0 ? 'var(--green)' : g.actual! < 0 ? 'var(--red)' : 'var(--ink-3)', marginTop: 1 }}>
            {g.actual! > 0 ? '+' : ''}{g.actual!.toFixed(1)}
          </div>
          {g.base !== undefined && (
            <div style={{ fontSize: 8, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginTop: 0 }}>
              proj {g.proj.toFixed(1)}
            </div>
          )}
        </>
      ) : dnp ? (
        // Game played but hitter didn't appear — no projection shown.
        <div style={{ fontSize: 9, fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--ink-3)', marginTop: 1, letterSpacing: '0.04em' }}>DNP</div>
      ) : (
        // Projection — smaller, muted, with the matchup-edge arrow (provisional).
        <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, color: 'var(--ink-3)', marginTop: 1, fontStyle: 'italic' }}>
          {g.proj.toFixed(1)}
          {(up || down) && <span style={{ fontStyle: 'normal', marginLeft: 2, color: up ? 'var(--green)' : 'var(--red)' }}>{up ? '↑' : '↓'}</span>}
        </div>
      )}
      {open && hasDetail && <DayPopover g={g} oppLabel={oppLabel} dnp={dnp} />}
    </div>
  )
}

function DayPopover({ g, oppLabel, dnp }: { g: DayGame; oppLabel: string; dnp?: boolean }) {
  const row = (label: React.ReactNode, value: React.ReactNode, color?: string) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '1px 0', color: color || 'var(--ink-2)' }}>
      <span>{label}</span><span style={{ fontWeight: 700 }}>{value}</span>
    </div>
  )
  return (
    <div
      onClick={e => e.stopPropagation()}
      style={{
        position: 'absolute', zIndex: 30, top: '100%', left: '50%', transform: 'translateX(-50%)',
        marginTop: 4, width: 190, textAlign: 'left',
        background: 'var(--white)', border: '1px solid var(--border-strong)',
        borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)', padding: '10px 12px',
        fontFamily: 'var(--mono)', fontSize: 11, whiteSpace: 'normal',
      }}
    >
      <div style={{ fontWeight: 700, color: 'var(--ink)', marginBottom: 6 }}>
        {oppLabel}{g.oppStarter ? ` · ${g.oppStarter}` : ''}{g.oppHand ? ` (${g.oppHand}HP)` : ''}
      </div>
      {row('Base', (g.base ?? 0).toFixed(1))}
      {(g.factors || []).length === 0 && (
        <div style={{ color: 'var(--ink-3)', padding: '1px 0' }}>No matchup edge</div>
      )}
      {(g.factors || []).map((f, i) => (
        <div key={i}>{row(f.label, `×${f.mult.toFixed(2)}`, f.mult > 1 ? 'var(--green)' : f.mult < 1 ? 'var(--red)' : 'var(--ink-2)')}</div>
      ))}
      <div style={{ borderTop: '1px solid var(--border)', margin: '5px 0' }} />
      {row('Proj', <span style={{ color: 'var(--green)' }}>{g.proj.toFixed(1)}</span>, 'var(--ink)')}
      {dnp && row('Result', <span style={{ color: 'var(--ink-3)' }}>Did not play</span>, 'var(--ink)')}
      {g.actual != null && row(
        g.status === 'in_progress' ? 'Actual (live)' : 'Actual',
        <span style={{ color: g.actual > 0 ? 'var(--green)' : g.actual < 0 ? 'var(--red)' : 'var(--ink-3)' }}>
          {g.actual > 0 ? '+' : ''}{g.actual.toFixed(1)}
        </span>,
        'var(--ink)',
      )}
    </div>
  )
}

// ─── Stats table (with advanced Savant columns) ───────────────────────────────

export function HitterStatsTable({ hitters, weeks, showOwn, leagueAvg }: {
  hitters: UIHitter[]; weeks: Weeks; showOwn?: boolean; leagueAvg?: HitterAdvanced
}) {
  const { sorted, key, dir, onSort } = useSortedHitters(hitters, weeks)
  const cellStyle: React.CSSProperties = {
    padding: '10px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', whiteSpace: 'nowrap',
  }
  const num = (extra?: React.CSSProperties): React.CSSProperties => ({ ...cellStyle, textAlign: 'center', fontFamily: 'var(--mono)', ...extra })
  const th = (label: string, col: string, align: 'left' | 'center' = 'center', title?: string, sub?: string) =>
    <SortTh label={label} col={col} sortKey={key} sortDir={dir} onSort={onSort} align={align} title={title} sub={sub} />
  const la = leagueAvg || {}
  const subRate = (n?: number) => (n === undefined ? undefined : n.toFixed(3).replace(/^0/, ''))
  const subPct  = (n?: number) => (n === undefined ? undefined : `${n.toFixed(1)}%`)
  const subNum  = (n?: number) => (n === undefined ? undefined : n.toFixed(1))
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {th('Hitter', 'name', 'left')}
            {th('AVG / OBP / SLG', 'ops', 'left', 'Sorted by OPS (OBP + SLG)')}
            {th('HR', 'hr')}
            {th('R', 'r')}
            {th('RBI', 'rbi')}
            {th('SB', 'sb')}
            {th('xBA', 'xba', 'center', undefined, subRate(la.xba))}
            {th('xSLG', 'xslg', 'center', undefined, subRate(la.xslg))}
            {th('xwOBA', 'xwoba', 'center', undefined, subRate(la.xwoba))}
            {th('Brl%', 'barrel', 'center', undefined, subPct(la.barrelPct))}
            {th('EV', 'ev', 'center', undefined, subNum(la.evAvg))}
            {th('Proj/G', 'projG')}
            {th('Proj wk', 'projWk')}
            {showOwn && th('Own%', 'own')}
          </tr>
        </thead>
        <tbody>
          {sorted.map(h => {
            const week = weeks[h.name] || []
            const projWk = week.reduce((a, g) => a + g.proj, 0)
            const isBench = h.pos === 'BN' || h.pos === 'IL' || !!h.il
            const hasLine = h.avg || h.obp || h.slg || h.hr || h.r || h.rbi || h.sb
            const adv = h.adv || {}
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', marginTop: 2 }}>
                    <PosTags pos={h.pos} />
                    <IlPill status={h.il} estReturn={h.estReturn} detail={h.injuryDetail} />
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                      {h.team}{h.bats ? ` · ${h.bats}HB` : ''}
                    </span>
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
      ? { date, off: false, opp: d.opp, home: d.home, proj: d.proj,
          oppHand: d.oppHand ?? null, oppStarter: d.oppStarter, base: d.base, factors: d.factors,
          status: d.status, actual: d.actual ?? null }
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
      il: h.injuryStatus && h.injuryStatus !== 'Active' ? h.injuryStatus : undefined,
      estReturn: h.estReturn || undefined,
      injuryDetail: h.injuryDetail || undefined,
      adv: h.advanced || undefined,
    },
    days,
  }
}
