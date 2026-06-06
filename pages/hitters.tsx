// pages/hitters.tsx
//
// Hitters page — live data only. Fetches baseline (Phase 0–1) projections from
// /api/hitters and renders them in the same Schedule / Stats tabs the pitcher
// pages use. While loading it shows a loading state (no placeholder data); if
// the league returns no hitters it shows an empty state.
//
// Phase 1 projections are flat per game (no matchup context yet); the schedule
// grid still shows real opponents from the shared schedule. Matchup edge chips,
// opposing-hand tags, actuals, and a nudge engine come in later phases.

import Head from 'next/head'
import { useEffect, useMemo, useState } from 'react'

// ─── Types ──────────────────────────────────────────────────────────────────

interface UIHitter {
  name: string
  team: string
  pos: string
  bats: string
  projG: number               // projected FPTS per game
  projFpts: number            // projected FPTS for the week
  avg: number; obp: number; slg: number
  hr: number; r: number; rbi: number; sb: number
}

interface DayGame {
  date: string
  off: boolean
  opp: string
  home: boolean
  proj: number
}

type Weeks = Record<string, DayGame[]>

interface MatchupPeriod {
  period: number; label: string; start: string; end: string; limit: number
}

// ─── Date / format helpers ──────────────────────────────────────────────────

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function fmtDay(iso: string) {
  const [, m, d] = iso.split('-')
  const wd = WD[new Date(iso + 'T12:00:00Z').getUTCDay()]
  return { wd, md: `${MONTHS[parseInt(m) - 1]} ${parseInt(d)}` }
}
function buildDateRange(start: string, end: string): string[] {
  const out: string[] = []
  const cur = new Date(start + 'T12:00:00Z')
  const last = new Date(end + 'T12:00:00Z')
  while (cur <= last) { out.push(cur.toISOString().slice(0, 10)); cur.setUTCDate(cur.getUTCDate() + 1) }
  return out
}
function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
function slash(h: UIHitter) {
  const f = (n: number) => (n || 0).toFixed(3).replace(/^0/, '')
  return `${f(h.avg)}/${f(h.obp)}/${f(h.slg)}`
}

// ─── Presentational helpers ──────────────────────────────────────────────────

function MetricCard({ label, value, accent }: {
  label: string; value: string | number; accent?: 'ok' | 'warn' | 'bad'
}) {
  const accentColor = { ok: 'var(--green)', warn: 'var(--amber)', bad: 'var(--red)' }
  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '14px 16px', boxShadow: 'var(--shadow)',
    }}>
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4, letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.03em', color: accent ? accentColor[accent] : 'var(--ink)' }}>{value}</div>
    </div>
  )
}

function PosBadge({ pos }: { pos: string }) {
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

// ════════════════════════════════════════════════════════════════════════════
//  PAGE
// ════════════════════════════════════════════════════════════════════════════

type Tab = 'schedule' | 'stats'

export default function Hitters() {
  const [tab, setTab] = useState<Tab>('schedule')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [live, setLive] = useState<any | null>(null)
  const [matchupPeriods, setMatchupPeriods] = useState<MatchupPeriod[]>([])
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null)

  // Load matchup periods + the initial selection (shared with the other pages
  // via the skipper_selected_period localStorage key).
  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(cfg => {
      if (cfg.matchupPeriods) setMatchupPeriods(cfg.matchupPeriods)
      const saved = localStorage.getItem('skipper_selected_period')
      setSelectedPeriod(saved ? parseInt(saved) : (cfg.currentPeriod ?? 1))
    }).catch(() => setSelectedPeriod(1))
  }, [])

  // Fetch hitters whenever the selected period changes.
  useEffect(() => {
    if (selectedPeriod === null) return
    let cancelled = false
    setLoading(true); setError('')
    localStorage.setItem('skipper_selected_period', String(selectedPeriod))
    fetch(`/api/hitters?week=${selectedPeriod}`).then(r => r.json()).then(data => {
      if (cancelled) return
      if (data && data.ok) setLive(data)
      else { setLive(null); setError(data?.error || 'Failed to load hitters') }
    }).catch(e => {
      if (!cancelled) { setLive(null); setError(e?.message || 'Failed to load hitters') }
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedPeriod])

  const { hitters, weeks, weekDates, today, label } = useMemo(() => {
    if (!live) {
      return { hitters: [] as UIHitter[], weeks: {} as Weeks, weekDates: [] as string[], today: todayISO(), label: '' }
    }
    const [start, end] = live.matchupDates || []
    const dates = start && end ? buildDateRange(start, end) : []
    const weeks: Weeks = {}
    const hitters: UIHitter[] = (live.rosterHitters || []).map((h: any) => {
      const byDate: Record<string, any> = {}
      ;(h.days || []).forEach((d: any) => { byDate[d.date] = d })
      weeks[h.name] = dates.map(date => {
        const d = byDate[date]
        return d
          ? { date, off: false, opp: d.opp, home: d.home, proj: d.proj }
          : { date, off: true, opp: '', home: false, proj: 0 }
      })
      const s = h.seasonStats || {}
      return {
        name: h.name, team: h.team, pos: h.pos, bats: h.bats || '',
        projG: h.projPerGame || 0, projFpts: h.projFpts || 0,
        avg: s.avg || 0, obp: s.obp || 0, slg: s.slg || 0,
        hr: s.hr || 0, r: s.r || 0, rbi: s.rbi || 0, sb: s.sb || 0,
      }
    })
    return {
      hitters, weeks, weekDates: dates, today: todayISO(),
      label: `${live.weekStart || ''} – ${live.weekEnd || ''}`,
    }
  }, [live])

  const metrics = useMemo(() => {
    const projWk = hitters.reduce((a, h) => a + (h.projFpts || 0), 0)
    const games = Object.values(weeks).reduce((a, w) => a + w.filter(g => !g.off).length, 0)
    const topG = hitters.reduce((a, h) => Math.max(a, h.projG), 0)
    return [
      { label: 'PROJ FPTS / WK', value: projWk.toFixed(1), accent: 'ok' as const },
      { label: 'HITTERS ROSTERED', value: hitters.length },
      { label: 'GAMES THIS WK', value: games },
      { label: 'TOP PROJ / G', value: topG.toFixed(1) },
    ]
  }, [hitters, weeks])

  return (
    <>
      <Head><title>Hitters · The Skipper</title></Head>

      <div style={{ maxWidth: 1100 }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Hitters</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {live?.teamName ? `${live.teamName} · ` : ''}{label || 'Daily projections'}
            </p>
          </div>
          {matchupPeriods.length > 0 && (
            <select
              value={selectedPeriod ?? ''}
              onChange={e => setSelectedPeriod(parseInt(e.target.value))}
              style={{
                fontFamily: 'var(--mono)', fontSize: 12, padding: '8px 12px',
                borderRadius: 'var(--radius)', border: '1.5px solid var(--border-strong)',
                background: 'var(--white)', color: 'var(--ink)', cursor: 'pointer', outline: 'none',
              }}
            >
              {matchupPeriods.map(p => {
                const fmt = (iso: string) => {
                  const [, m, d] = iso.split('-')
                  return `${MONTHS[parseInt(m) - 1]} ${parseInt(d)}`
                }
                return (
                  <option key={p.period} value={p.period}>
                    {p.label} · {fmt(p.start)}–{fmt(p.end)}
                  </option>
                )
              })}
            </select>
          )}
        </div>

        {loading ? (
          <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '40px 24px', textAlign: 'center', boxShadow: 'var(--shadow)', color: 'var(--ink-3)', fontSize: 14 }}>
            Loading hitter projections…
          </div>
        ) : error ? (
          <div style={{ background: 'var(--red-light)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', padding: '12px 16px', fontSize: 13, color: 'var(--red)' }}>
            ⚠ {error}
          </div>
        ) : hitters.length === 0 ? (
          <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '40px 24px', textAlign: 'center', boxShadow: 'var(--shadow)' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>🏏</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No hitters found</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>
              No hitters were returned for this matchup period.
            </div>
          </div>
        ) : (
          <>
            {/* Phase note */}
            <div style={{ background: 'var(--green-light)', border: '1px solid rgba(46,196,160,0.35)', borderRadius: 'var(--radius)', padding: '10px 14px', fontSize: 13, color: 'var(--green)', marginBottom: 20 }}>
              ● <strong>Phase 1 baseline.</strong> Per-game projections are season-rate (flat) for now; matchup, park, weather &amp; recent-form layers come in later phases.
            </div>

            {/* Metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
              {metrics.map(m => <MetricCard key={m.label} {...m} />)}
            </div>

            {/* Roster card */}
            <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', boxShadow: 'var(--shadow)', marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, gap: 12 }}>
                <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Your hitters</div>
                <div style={{ display: 'flex', gap: 2, background: 'var(--paper-2)', padding: 3, borderRadius: 8 }}>
                  {(['schedule', 'stats'] as const).map(t => {
                    const active = tab === t
                    return (
                      <button key={t} onClick={() => setTab(t)} style={{
                        fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, padding: '5px 14px',
                        borderRadius: 6, border: 'none', cursor: 'pointer',
                        background: active ? 'var(--white)' : 'transparent',
                        color: active ? 'var(--ink)' : 'var(--ink-3)',
                        boxShadow: active ? 'var(--shadow)' : 'none', transition: 'all 0.15s',
                      }}>{t === 'schedule' ? 'Schedule' : 'Stats'}</button>
                    )
                  })}
                </div>
              </div>

              {tab === 'schedule'
                ? <HitterScheduleGrid hitters={hitters} weeks={weeks} weekDates={weekDates} today={today} />
                : <HitterStatsTable hitters={hitters} weeks={weeks} />}
            </div>
          </>
        )}

      </div>
    </>
  )
}

// ─── Schedule grid ──────────────────────────────────────────────────────────

function HitterScheduleGrid({ hitters, weeks, weekDates, today }: {
  hitters: UIHitter[]; weeks: Weeks; weekDates: string[]; today: string
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

function HitterStatsTable({ hitters, weeks }: { hitters: UIHitter[]; weeks: Weeks }) {
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
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
