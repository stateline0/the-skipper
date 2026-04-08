import Head from 'next/head'
import { useState, useEffect, useCallback, useRef } from 'react'
const CACHE_VERSION = 2 // bump this whenever the API response shape changes
import { useRouter } from 'next/router'
import ScheduleGrid from '../components/ScheduleGrid'

// ─── Types ────────────────────────────────────────────────────────────────────
interface RosterSP {
  name: string; team: string; slot: string; injuryStatus: string
  starts: number; projFpts: number; projBlend?: number; percentOwned: number; startDates?: any[]
}

interface MatchupPeriod {
  period: number; label: string; start: string; end: string; limit: number
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getWeekRange(start?: string, end?: string) {
  if (start && end) return `${start} – ${end}`
  const today = new Date()
  const dow = today.getDay()
  const mon = new Date(today); mon.setDate(today.getDate() - ((dow + 6) % 7))
  const sun = new Date(mon); sun.setDate(mon.getDate() + 6)
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return `${fmt(mon)} – ${fmt(sun)}`
}

function MetricCard({ label, value, accent }: {
  label: string; value: string | number; accent?: 'ok' | 'warn' | 'bad'
}) {
  const accentColor = { ok: 'var(--green)', warn: '#e89020', bad: 'var(--red)' }
  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '14px 16px', boxShadow: 'var(--shadow)',
    }}>
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4, letterSpacing: '0.04em' }}>{label}</div>
      <div style={{
        fontSize: 26, fontWeight: 700, letterSpacing: '-0.03em',
        color: accent ? accentColor[accent] : 'var(--ink)',
      }}>{value}</div>
    </div>
  )
}

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = Math.min(100, Math.round(value / max * 100))
  const color = pct >= 92 ? 'var(--green-mid)' : pct >= 65 ? '#e89020' : 'var(--red)'
  return (
    <div style={{ height: 6, background: 'var(--paper-3)', borderRadius: 99, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${pct}%`, borderRadius: 99, background: color, transition: 'width 0.5s ease' }} />
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function MyTeam() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [rosterSPs, setRosterSPs] = useState<RosterSP[]>([])
  const [limit, setLimit] = useState(12)
  const [confirmedStarts, setConfirmedStarts] = useState(0)
  const [weekStart, setWeekStart] = useState('')
  const [weekEnd, setWeekEnd] = useState('')
  const [teamName, setTeamName] = useState('')
  const [currentWeek, setCurrentWeek] = useState(1)
  const [matchupPeriods, setMatchupPeriods] = useState<MatchupPeriod[]>([])
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null)
  const [schedule, setSchedule] = useState<Record<string, any>>({})
  const [matchupDates, setMatchupDates] = useState<string[]>([])
  const [actualFpts, setActualFpts]   = useState<Record<string, Record<string, number>>>({})
  const [actualSaves, setActualSaves] = useState<Record<string, Record<string, number>>>({})
  const [benchDays, setBenchDays]     = useState<Record<string, string[]>>({})

  const weekLabel = getWeekRange(weekStart, weekEnd)
  const needed = Math.max(0, limit - confirmedStarts)

  const rosterStarterSPs = rosterSPs.filter(p => p.slot === 'SP')
  const rosterRelievers  = rosterSPs.filter(p => p.slot === 'RP')

  const teamSavesTotal = rosterRelievers.reduce((acc, p) => {
    const byDay = actualSaves[p.name] || {}
    return acc + Object.values(byDay).reduce((a, b) => a + b, 0)
  }, 0)

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        if (data.defaultLimit) setLimit(data.defaultLimit)
        if (data.matchupPeriods) setMatchupPeriods(data.matchupPeriods)
        // Use sessionStorage if present, otherwise default to today's period
        const saved = sessionStorage.getItem('skipper_selected_period')
        const period = saved ? parseInt(saved) : (data.currentPeriod ?? 1)
        setSelectedPeriod(period)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const cached = sessionStorage.getItem('skipper_roster')
    if (cached) {
      const data = JSON.parse(cached)
      if (data.version !== CACHE_VERSION) return // outdated shape — let the fetch effect handle it
      if (!data.matchupDates || data.matchupDates.length === 0) return // stale, wait for period
      setRosterSPs(data.rosterSPs || [])
      setConfirmedStarts(data.confirmedStarts || 0)
      setWeekStart(data.weekStart || '')
      setWeekEnd(data.weekEnd || '')
      setTeamName(data.teamName || '')
      setCurrentWeek(data.currentWeek || 1)
      setSchedule(data.schedule || {})
      setMatchupDates(data.matchupDates || [])
      setActualFpts(data.actualFpts || {})
      setActualSaves(data.actualSaves || {})
      setBenchDays(data.benchDays || {})
    }
  }, [])

  const isFirstRender = useRef(true)

  useEffect(() => {
    if (selectedPeriod === null) return
    const period = matchupPeriods.find(p => p.period === selectedPeriod)
    if (period) setLimit(period.limit)

    if (isFirstRender.current) {
      // On first render: only fetch if there's no usable cache
      isFirstRender.current = false
      const cached = sessionStorage.getItem('skipper_roster')
      if (!cached) {
        fetchRoster()
      } else {
        const data = JSON.parse(cached)
        if (!data.matchupDates || data.matchupDates.length === 0) fetchRoster()
      }
      return
    }

    // On subsequent renders (user changed the dropdown): always fetch fresh
    fetchRoster()
  }, [selectedPeriod, matchupPeriods])

  const fetchRoster = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const configRes = await fetch('/api/config')
      const config = await configRes.json()
      const teamId = config.teamId || '1'

      sessionStorage.setItem('skipper_selected_period', String(selectedPeriod))
      const res = await fetch(`/api/espn?teamId=${teamId}&week=${selectedPeriod}`)
      const data = await res.json()
      if (!data.ok) throw new Error(data.error || 'Failed to load ESPN data')

      const roster: RosterSP[] = data.rosterSPs.map((p: any) => ({
        ...p, starts: p.starts ?? 0, projFpts: p.projFpts ?? 0,
      }))
      const starts = roster.reduce((a, p) => a + p.starts, 0)

      const toCache = {
        version: CACHE_VERSION,
        rosterSPs: roster,
        confirmedStarts: starts,
        weekStart: data.weekStart || '',
        weekEnd: data.weekEnd || '',
        teamName: data.teamName || '',
        currentWeek: data.currentWeek || currentWeek,
        schedule: data.schedule || {},
        matchupDates: data.matchupDates || [],
        actualFpts: data.actualFpts || {},
        actualSaves: data.actualSaves || {},
        benchDays: data.benchDays || {},
      }
      sessionStorage.setItem('skipper_roster', JSON.stringify(toCache))

      setRosterSPs(roster)
      setConfirmedStarts(starts)
      setWeekStart(data.weekStart || '')
      setWeekEnd(data.weekEnd || '')
      setTeamName(data.teamName || '')
      setCurrentWeek(data.currentWeek || currentWeek)
      setSchedule(data.schedule || {})
      setMatchupDates(data.matchupDates || [])
      setActualFpts(data.actualFpts || {})
      setActualSaves(data.actualSaves || {})
      setBenchDays(data.benchDays || {})
    } catch (e: any) {
      setError(e.message || 'Failed to load roster')
    } finally {
      setLoading(false)
    }
  }, [selectedPeriod])

  return (
    <>
      <Head><title>My Team · The Skipper</title></Head>

      <style>{`
        input[type=number] {
          font-family: var(--mono); font-size: 13px;
          background: var(--white); border: 1px solid var(--border-strong);
          border-radius: var(--radius); padding: 8px 10px; outline: none; color: var(--ink);
        }
        input[type=number]:focus {
          border-color: var(--green-mid); box-shadow: 0 0 0 3px rgba(46,168,101,0.12);
        }
      `}</style>

      <div style={{ maxWidth: 1100 }}>

        {/* Page header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>My Team</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {teamName ? `${teamName} · ` : ''}{weekLabel}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
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
                    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
                    return `${months[parseInt(m)-1]} ${parseInt(d)}`
                  }
                  return (
                    <option key={p.period} value={p.period}>
                      {p.label} · {fmt(p.start)}–{fmt(p.end)}
                    </option>
                  )
                })}
              </select>
            )}
            <button
              onClick={fetchRoster} disabled={loading}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: loading ? 'not-allowed' : 'pointer',
                border: '1.5px solid var(--border-strong)',
                background: 'transparent', color: 'var(--ink)',
                opacity: loading ? 0.5 : 1, transition: 'all 0.15s',
              }}
            >
              {loading ? 'Refreshing...' : '↻ Refresh'}
            </button>
          </div>
        </div>

        {error && (
          <div style={{
            background: 'var(--red-light)', border: '1px solid var(--red)',
            borderRadius: 'var(--radius)', padding: '12px 16px',
            fontSize: 13, color: 'var(--red)', marginBottom: 16,
          }}>⚠ {error}</div>
        )}

        {rosterSPs.length === 0 && !loading ? (
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '40px 24px',
            textAlign: 'center', boxShadow: 'var(--shadow)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⚾</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No roster loaded</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 20 }}>
              Connect to ESPN from the Dashboard to load your team.
            </div>
            <button onClick={() => router.push('/dashboard')} style={{
              fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
              padding: '9px 18px', borderRadius: 'var(--radius)',
              cursor: 'pointer', border: 'none', background: 'var(--ink)', color: 'var(--white)',
            }}>Go to Dashboard →</button>
          </div>
        ) : (
          <>
            {/* Metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 16 }}>
              <MetricCard label="STARTS LIMIT" value={limit} />
              <MetricCard label="SCHEDULED" value={confirmedStarts}
                accent={confirmedStarts >= limit ? 'ok' : confirmedStarts >= limit * 0.7 ? 'warn' : 'bad'} />
              <MetricCard label="STILL NEEDED" value={needed}
                accent={needed === 0 ? 'ok' : needed <= 3 ? 'warn' : 'bad'} />
              <MetricCard label="ROSTERED SPs" value={rosterSPs.length} />
            </div>

            {/* Progress bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4 }}>
              <span>Starts utilization</span><span>{confirmedStarts} / {limit}</span>
            </div>
            <ProgressBar value={confirmedStarts} max={limit} />
            <div style={{ marginBottom: 16 }} />

            {/* Schedule grid */}
            <div style={{
              background: 'var(--white)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px',
              boxShadow: 'var(--shadow)', marginBottom: 16,
            }}>
              <div style={{
                fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
                letterSpacing: '0.1em', color: 'var(--ink-3)',
                textTransform: 'uppercase', marginBottom: 12,
              }}>Your starting pitchers</div>
              <ScheduleGrid
                pitchers={rosterStarterSPs}
                schedule={schedule}
                matchupDates={matchupDates}
                actualFpts={actualFpts}
                benchDays={benchDays}
              />
            </div>

            {/* Relievers section */}
            {rosterRelievers.length > 0 && (
              <div style={{
                background: 'var(--white)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-lg)', padding: '20px 24px',
                boxShadow: 'var(--shadow)', marginBottom: 16,
              }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'center', marginBottom: 12,
                }}>
                  <div style={{
                    fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
                    letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase',
                  }}>Your relievers</div>
                  {teamSavesTotal > 0 && (
                    <div style={{
                      fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700,
                      color: 'var(--ink-2)', background: 'var(--paper-2)',
                      borderRadius: 99, padding: '3px 10px',
                    }}>
                      🔒 {teamSavesTotal} team SV this period
                    </div>
                  )}
                </div>
                <ScheduleGrid
                  pitchers={rosterRelievers}
                  schedule={schedule}
                  matchupDates={matchupDates}
                  actualFpts={actualFpts}
                  actualSaves={actualSaves}
                  benchDays={benchDays}
                  savesData={actualSaves}
                />
              </div>
            )}

            {/* Starts editor */}
            <div style={{
              background: 'var(--white)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px',
              boxShadow: 'var(--shadow)', marginBottom: 24,
            }}>
              <div style={{
                fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
                letterSpacing: '0.1em', color: 'var(--ink-3)',
                textTransform: 'uppercase', marginBottom: 12,
              }}>Adjust starts</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 13, color: 'var(--ink-2)' }}>Starts limit:</label>
                  <input type="number" value={limit} min={1} max={30}
                    onChange={e => setLimit(parseInt(e.target.value) || 0)} style={{ width: 70 }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 13, color: 'var(--ink-2)' }}>Confirmed starts:</label>
                  <input type="number" value={confirmedStarts} min={0} max={30}
                    onChange={e => setConfirmedStarts(parseInt(e.target.value) || 0)} style={{ width: 70 }} />
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button onClick={() => router.push('/free-agents')} style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: 'pointer', border: 'none',
                background: 'var(--ink)', color: 'var(--white)',
              }}>View free agents →</button>
            </div>
          </>
        )}
      </div>
    </>
  )
}