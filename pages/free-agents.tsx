import Head from 'next/head'
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import ScheduleGrid from '../components/ScheduleGrid'
import StatsTable, { SeasonStats, SavantExpected } from '../components/StatsTable'
import {
  UIHitter, Weeks, buildDateRange, todayISO, hitterFromPayload,
  HitterScheduleGrid, HitterStatsTable,
} from '../components/HitterTables'

const CACHE_VERSION = 7 // bump this whenever the API response shape changes

interface FreeSP {
  name: string; team: string; slot: string; injuryStatus: string
  percentOwned: number; projFpts: number; projBlend?: number; starts: number
  opps?: string; checked: boolean; startDates?: any[]
  seasonStats?: SeasonStats | null; savantExpected?: SavantExpected | null
  fptsHistory?: number[] | null
}

interface MatchupPeriod {
  period: number; label: string; start: string; end: string; limit: number
}

// Human "Updated 4m ago" from the payload's computedAt ISO timestamp.
function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (secs < 45) return 'just now'
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`
  return `${Math.round(secs / 86400)}d ago`
}

export default function FreeAgents() {
  const [loading, setLoading] = useState(false)
  const [matchupPeriods, setMatchupPeriods] = useState<MatchupPeriod[]>([])
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [freeSPs, setFreeSPs] = useState<FreeSP[]>([])
  const [schedule, setSchedule] = useState<Record<string, any>>({})
  const [matchupDates, setMatchupDates] = useState<string[]>([])
  const [actualFpts, setActualFpts]     = useState<Record<string, Record<string, number>>>({})
  const [fptsPerStart, setFptsPerStart] = useState<Record<string, number>>({})
  const [projectionDetails, setProjectionDetails] = useState<Record<string, any>>({})
  const [liveStats, setLiveStats]       = useState<Record<string, any>>({})
  const [computedAt, setComputedAt]     = useState<string | null>(null)
  const [sortCol, setSortCol]           = useState<string>('percentOwned')
  const [sortDir, setSortDir]           = useState<'asc' | 'desc'>('desc')
  const [activeTab, setActiveTab]       = useState<'schedule' | 'stats'>('schedule')
  const [mode, setMode]                 = useState<'pitchers' | 'hitters'>('pitchers')

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        if (data.matchupPeriods) setMatchupPeriods(data.matchupPeriods)
        const saved = localStorage.getItem('skipper_selected_period')
        const period = saved ? parseInt(saved) : (data.currentPeriod ?? 1)
        setSelectedPeriod(period)
      })
      .catch(() => {})

    const cached = localStorage.getItem('skipper_free_agents')
    if (cached) {
      const data = JSON.parse(cached)
      if (data.version !== CACHE_VERSION) return // outdated shape — let the fetch effect handle it
      if (!data.matchupDates || data.matchupDates.length === 0) return
      setFreeSPs(data.freeSPs || [])
      setSchedule(data.schedule || {})
      setMatchupDates(data.matchupDates || [])
      setActualFpts(data.actualFpts || {})
      setFptsPerStart(data.fptsPerStart || {})
      setProjectionDetails(data.projectionDetails || {})
      setLiveStats(data.liveStats || {})
      setComputedAt(data.computedAt || null)
    }
  }, [])

  // Stale-while-revalidate: cached data (restored on mount from localStorage)
  // renders immediately; refresh in the background whenever the period changes.
  useEffect(() => {
    if (selectedPeriod === null) return
    fetchFreeAgents()
  }, [selectedPeriod])

  const fetchFreeAgents = useCallback(async (fresh = false) => {
    setLoading(true)
    setError('')
    try {
      const configRes = await fetch('/api/config')
      const config = await configRes.json()
      const teamId = config.teamId || '1'

      localStorage.setItem('skipper_selected_period', String(selectedPeriod))
      const res = await fetch(`/api/espn?teamId=${teamId}&week=${selectedPeriod}${fresh ? '&fresh=1' : ''}`)
      const data = await res.json()
      if (!data.ok) throw new Error(data.error || 'Failed to load ESPN data')

      const fas: FreeSP[] = (data.freeAgentSPs || []).map((p: any) => ({
        ...p,
        slot: p.slot || 'SP',
        starts: p.starts ?? 0,
        projFpts: p.projFpts ?? 0,
        projBlend: p.projBlend ?? 0,
        opps: p.opps || '',
        checked: p.percentOwned >= 15,
      }))

      const toCache = {
        version: CACHE_VERSION,
        freeSPs: fas,
        schedule: data.schedule || {},
        matchupDates: data.matchupDates || [],
        actualFpts: data.faActualFpts || {},
        fptsPerStart: data.faFptsPerStart || {},
        projectionDetails: data.faProjectionDetails || {},
        liveStats: data.liveStats || {},
        computedAt: data.computedAt || null,
      }
      localStorage.setItem('skipper_free_agents', JSON.stringify(toCache))
      setFreeSPs(fas)
      setSchedule(data.schedule || {})
      setMatchupDates(data.matchupDates || [])
      setActualFpts(data.faActualFpts || {})
      setFptsPerStart(data.faFptsPerStart || {})
      setProjectionDetails(data.faProjectionDetails || {})
      setLiveStats(data.liveStats || {})
      setComputedAt(data.computedAt || null)
    } catch (e: any) {
      setError(e.message || 'Failed to load free agents')
    } finally {
      setLoading(false)
    }
  }, [selectedPeriod])

function handleSort(col: string) {
    if (col === sortCol) {
      // Same column — cycle: desc → asc → default (percentOwned desc)
      if (sortDir === 'desc') {
        setSortDir('asc')
      } else {
        setSortCol('percentOwned')
        setSortDir('desc')
      }
    } else {
      setSortCol(col)
      setSortDir('desc')
    }
  }

  const sortedFreeSPs = useMemo(() => {
    const sorted = [...freeSPs]
    sorted.sort((a, b) => {
      let aVal: number
      let bVal: number

      if (sortCol === 'name') {
        // String sort — flip the numeric logic
        const cmp = a.name.localeCompare(b.name)
        return sortDir === 'asc' ? cmp : -cmp
      } else if (sortCol === 'percentOwned') {
        aVal = a.percentOwned ?? 0
        bVal = b.percentOwned ?? 0
      } else if (sortCol === 'projFpts') {
        aVal = a.projFpts ?? 0
        bVal = b.projFpts ?? 0
      } else if (sortCol === 'actFpts') {
        aVal = Object.values(actualFpts[a.name] || {}).reduce((sum: number, v: number) => sum + v, 0)
        bVal = Object.values(actualFpts[b.name] || {}).reduce((sum: number, v: number) => sum + v, 0)
      } else if (sortCol === 'starts') {
        aVal = a.starts ?? 0
        bVal = b.starts ?? 0
      } else {
        // Date column — sort by adjusted per-start projection if pitcher starts that day
        const aStart = a.startDates?.find(s => s.date === sortCol)
        const bStart = b.startDates?.find(s => s.date === sortCol)
        const aDetail = projectionDetails[a.name]?.starts?.find((s: any) => s.date === sortCol)
        const bDetail = projectionDetails[b.name]?.starts?.find((s: any) => s.date === sortCol)
        aVal = aStart ? (aDetail?.proj ?? fptsPerStart[a.name] ?? 0) : 0
        bVal = bStart ? (bDetail?.proj ?? fptsPerStart[b.name] ?? 0) : 0
      }

      return sortDir === 'desc' ? bVal - aVal : aVal - bVal
    })
    return sorted
  }, [freeSPs, sortCol, sortDir, fptsPerStart, actualFpts, projectionDetails])

  return (
    <>
      <Head><title>Free Agents · The Skipper</title></Head>

      <style>{`
        input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--green-mid); cursor: pointer; }
      `}</style>

      <div style={{ maxWidth: 1100 }}>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Free Agents</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {mode === 'pitchers'
                ? 'Available SPs — check the ones to include in your analysis'
                : 'Available hitters — projected with the hitter model'}
            </p>
            {mode === 'pitchers' && computedAt && (
              <div style={{ fontSize: 12, color: 'var(--ink-3)', opacity: 0.7, marginTop: 2, whiteSpace: 'nowrap' }}>
                Updated {relativeTime(computedAt)}{loading ? ' · refreshing…' : ''}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {/* Pitchers / Hitters toggle */}
            <div style={{ display: 'flex', gap: 2, background: 'var(--paper-2)', padding: 3, borderRadius: 8 }}>
              {(['pitchers', 'hitters'] as const).map(m => {
                const active = mode === m
                return (
                  <button key={m} onClick={() => setMode(m)} style={{
                    fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, padding: '5px 14px',
                    borderRadius: 6, border: 'none', cursor: 'pointer',
                    background: active ? 'var(--white)' : 'transparent',
                    color: active ? 'var(--ink)' : 'var(--ink-3)',
                    boxShadow: active ? 'var(--shadow)' : 'none', transition: 'all 0.15s',
                  }}>{m === 'pitchers' ? 'Pitchers' : 'Hitters'}</button>
                )
              })}
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
            {mode === 'pitchers' && (
              <button onClick={() => fetchFreeAgents(true)} disabled={loading} style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: loading ? 'not-allowed' : 'pointer',
                border: '1.5px solid var(--border-strong)',
                background: 'transparent', color: 'var(--ink)',
                opacity: loading ? 0.5 : 1,
              }}>
                {loading ? 'Refreshing...' : '↻ Refresh'}
              </button>
            )}
          </div>
        </div>

        {mode === 'hitters' && <FAHitters period={selectedPeriod} />}

        {mode === 'pitchers' && (<>
        {error && (
          <div style={{
            background: 'var(--red-light)', border: '1px solid var(--red)',
            borderRadius: 'var(--radius)', padding: '12px 16px',
            fontSize: 13, color: 'var(--red)', marginBottom: 16,
          }}>⚠ {error}</div>
        )}

        {freeSPs.length === 0 && !loading ? (
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '40px 24px',
            textAlign: 'center', boxShadow: 'var(--shadow)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No free agents loaded</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 20 }}>
              Click Refresh to load available pitchers.
            </div>
            <button onClick={() => fetchFreeAgents()} style={{
              fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
              padding: '9px 18px', borderRadius: 'var(--radius)',
              cursor: 'pointer', border: 'none', background: '#E2E4E8', color: '#0F1114',
            }}>Load free agents →</button>
          </div>
        ) : (
          <>
            <div style={{
              background: 'var(--blue-light)', border: '1px solid rgba(26,95,168,0.2)',
              borderRadius: 'var(--radius)', padding: '10px 14px',
              fontSize: 13, color: 'var(--blue)', marginBottom: 16,
            }}>
              Top available SPs by ownership %.
            </div>

            <div style={{
              background: 'var(--white)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px',
              boxShadow: 'var(--shadow)', marginBottom: 16,
            }}>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 12, gap: 12,
              }}>
                <div style={{
                  fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
                  letterSpacing: '0.1em', color: 'var(--ink-3)',
                  textTransform: 'uppercase',
                }}>Available starting pitchers</div>

                {/* Tab toggle — mirrors the My Team card (Schedule / Stats). */}
                <div style={{
                  display: 'flex', gap: 2,
                  background: 'var(--paper-2)', padding: 3,
                  borderRadius: 8,
                }}>
                  {(['schedule', 'stats'] as const).map(tab => {
                    const isActive = activeTab === tab
                    return (
                      <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        style={{
                          fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600,
                          padding: '5px 14px', borderRadius: 6,
                          border: 'none', cursor: 'pointer',
                          background: isActive ? 'var(--white)' : 'transparent',
                          color: isActive ? 'var(--ink)' : 'var(--ink-3)',
                          boxShadow: isActive ? 'var(--shadow)' : 'none',
                          transition: 'all 0.15s',
                        }}
                      >
                        {tab === 'schedule' ? 'Schedule' : 'Stats'}
                      </button>
                    )
                  })}
                </div>
              </div>

              {activeTab === 'schedule' ? (
              <ScheduleGrid
                pitchers={sortedFreeSPs}
                schedule={schedule}
                matchupDates={matchupDates}
                actualFpts={actualFpts}
                fptsPerStart={fptsPerStart}
                projectionDetails={projectionDetails}
                liveStats={liveStats}
                sortCol={sortCol}
                sortDir={sortDir}
                onSortChange={handleSort}
                suffixHeaders={
                  <th
                    onClick={() => handleSort('percentOwned')}
                    style={{
                      padding: '8px 6px', fontSize: 10, fontFamily: 'var(--mono)',
                      fontWeight: 500, borderBottom: '1px solid var(--border)',
                      minWidth: 52, whiteSpace: 'nowrap', cursor: 'pointer',
                      userSelect: 'none',
                      color: sortCol === 'percentOwned' ? 'var(--ink)' : 'var(--ink-3)',
                    }}
                  >
                    Own%{sortCol === 'percentOwned' ? (sortDir === 'desc' ? ' ↓' : ' ↑') : ''}
                  </th>
                }
                renderSuffix={(pitcher) => (
                  <td style={{ padding: '8px 6px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
                    {(pitcher as FreeSP).percentOwned ?? 0}%
                  </td>
                )}
              />
              ) : (
                <StatsTable
                  pitchers={sortedFreeSPs}
                  fptsPerStart={fptsPerStart}
                  actualFpts={actualFpts}
                />
              )}
            </div>
          </>
        )}
        </>)}
      </div>
    </>
  )
}

// ─── Free-agent hitters view ──────────────────────────────────────────────────
// Fetches /api/hitters for the selected period and renders its freeAgentHitters
// through the shared HitterTables components, with a Schedule/Stats sub-toggle
// and an Own% column.
function FAHitters({ period }: { period: number | null }) {
  const [tab, setTab] = useState<'schedule' | 'stats'>('schedule')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState<any | null>(null)

  useEffect(() => {
    if (period === null) return
    let cancelled = false
    setLoading(true); setError('')
    fetch(`/api/hitters?week=${period}`).then(r => r.json()).then(d => {
      if (cancelled) return
      if (d && d.ok) setData(d)
      else { setData(null); setError(d?.error || 'Failed to load free-agent hitters') }
    }).catch(e => {
      if (!cancelled) { setData(null); setError(e?.message || 'Failed to load free-agent hitters') }
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [period])

  const { hitters, weeks, weekDates, today } = useMemo(() => {
    if (!data) return { hitters: [] as UIHitter[], weeks: {} as Weeks, weekDates: [] as string[], today: todayISO() }
    const [start, end] = data.matchupDates || []
    const dates = start && end ? buildDateRange(start, end) : []
    const weeks: Weeks = {}
    const hitters: UIHitter[] = (data.freeAgentHitters || []).map((h: any) => {
      const { hitter, days } = hitterFromPayload(h, dates)
      weeks[h.name] = days
      return hitter
    })
    return { hitters, weeks, weekDates: dates, today: todayISO() }
  }, [data])

  if (loading) {
    return (
      <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '40px 24px', textAlign: 'center', boxShadow: 'var(--shadow)', color: 'var(--ink-3)', fontSize: 14 }}>
        Loading free-agent hitters…
      </div>
    )
  }
  if (error) {
    return (
      <div style={{ background: 'var(--red-light)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', padding: '12px 16px', fontSize: 13, color: 'var(--red)' }}>⚠ {error}</div>
    )
  }
  if (hitters.length === 0) {
    return (
      <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '40px 24px', textAlign: 'center', boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>🏏</div>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No free-agent hitters</div>
        <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>None were returned for this period.</div>
      </div>
    )
  }

  return (
    <>
      <div style={{
        background: 'var(--blue-light)', border: '1px solid rgba(26,95,168,0.2)',
        borderRadius: 'var(--radius)', padding: '10px 14px',
        fontSize: 13, color: 'var(--blue)', marginBottom: 16,
      }}>
        Top available hitters by ownership %, projected with the hitter model (Savant-de-lucked).
      </div>
      <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', boxShadow: 'var(--shadow)', marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, gap: 12 }}>
          <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Available hitters</div>
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
          ? <HitterScheduleGrid hitters={hitters} weeks={weeks} weekDates={weekDates} today={today} showOwn actualsTracked />
          : <HitterStatsTable hitters={hitters} weeks={weeks} showOwn leagueAvg={data?.leagueAvg} />}
      </div>
    </>
  )
}