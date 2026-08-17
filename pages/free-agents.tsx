import Head from 'next/head'
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import ScheduleGrid from '../components/ScheduleGrid'
import StatsTable, { PITCHER_COLUMNS, SV_COLUMN, PitcherColumn, SeasonStats, SavantExpected, sortPitchersBy } from '../components/StatsTable'
import {
  UIHitter, Weeks, buildDateRange, todayISO, hitterFromPayload,
  HitterScheduleGrid, HitterStatsTable, HitterSort,
} from '../components/HitterTables'

const CACHE_VERSION = 11 // bump this whenever the API response shape changes

// Canonical hitter positions for the Free Agents position filter. A hitter's
// pos may be composite (e.g. "2B/SS"), so matching splits on "/". UTIL is a
// lineup slot (any position can fill it), not a real position, so it's excluded.
const HITTER_POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'OF', 'DH']

// The RP tab reuses the pitcher StatsTable but drops start-based columns
// (Starts, Form sparkline, season Pace) that are meaningless for relievers, and
// adds Saves (SV) — a key part of reliever scoring, omitted from the SP set.
const RP_COLUMN_KEYS = ['name', 'percentOwned', 'era', 'k9', 'bb9', 'sv',
  'xera', 'xwoba', 'wobaDiff', 'luck', 'barrelPct', 'whiffPct', 'projFpts', 'actFpts']
const RP_COLUMN_POOL = [...PITCHER_COLUMNS, SV_COLUMN]
const RP_COLUMNS: PitcherColumn[] = RP_COLUMN_KEYS
  .map(k => RP_COLUMN_POOL.find(c => c.key === k))
  .filter((c): c is PitcherColumn => Boolean(c))

interface FreeSP {
  name: string; team: string; slot: string; injuryStatus: string
  percentOwned: number; projFpts: number; projBlend?: number; starts: number
  opps?: string; checked: boolean; startDates?: any[]
  seasonStats?: SeasonStats | null; savantExpected?: SavantExpected | null
  fptsHistory?: number[] | null
}

// A free-agent pitcher belongs in the SPs (start-based) view if ESPN lists them
// as SP-eligible OR they have a projected start this period — e.g. an RP-only
// arm making a spot start. Everyone else (relievers with no scheduled start)
// goes to the RPs view.
function isStarterView(p: FreeSP): boolean {
  return p.slot === 'SP' || (p.startDates?.length ?? 0) > 0
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
  const [mode, setMode]                 = useState<'sp' | 'rp' | 'batters'>('sp')
  const [nameQuery, setNameQuery]       = useState('')
  const [posFilter, setPosFilter]       = useState('')

  // The position filter only applies to the Batters tab; clear it when leaving
  // (or on any tab switch) so it never silently hides rows elsewhere.
  useEffect(() => { setPosFilter('') }, [mode])

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

function handleSort(col: string, preferredDir: 'asc' | 'desc' = 'desc') {
    // preferredDir is the column's first-click direction — 'desc' for the
    // schedule headers, and the Stats tab's per-column hint ('asc' for
    // lower-is-better stats like ERA).
    if (col === sortCol) {
      // Same column — cycle: first-click dir → flipped → default (percentOwned desc)
      if (sortDir === preferredDir) {
        setSortDir(preferredDir === 'desc' ? 'asc' : 'desc')
      } else {
        setSortCol('percentOwned')
        setSortDir('desc')
      }
    } else {
      setSortCol(col)
      setSortDir(preferredDir)
    }
  }

  // The position dropdown only applies to the Batters tab (SPs/RPs are their
  // own tabs now), so its options are always the canonical hitter list.
  const positionOptions = HITTER_POSITIONS

  // Pitchers are filtered by name only; the SP/RP split is by isStarterView
  // (slot or a projected spot start), so a spot-starting reliever shows in SPs.
  const nameMatches = useCallback((n: string) => {
    const q = nameQuery.trim().toLowerCase()
    return !q || n.toLowerCase().includes(q)
  }, [nameQuery])
  const spList = useMemo(() => freeSPs.filter(p => isStarterView(p) && nameMatches(p.name)), [freeSPs, nameMatches])
  const rpList = useMemo(() => freeSPs.filter(p => !isStarterView(p) && nameMatches(p.name)), [freeSPs, nameMatches])

  // One sorted list feeds BOTH the Schedule and Stats tabs, so the order (and
  // the shared sortCol/sortDir state) survives the tab switch. Date columns
  // exist only on the schedule, so they're sorted here; every other key is a
  // StatsTable column — delegate to its comparator so the two tabs can never
  // disagree on ordering.
  const sortedSPs = useMemo(() => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(sortCol)) {
      return sortPitchersBy(spList, sortCol, sortDir, { fptsPerStart, actualFpts })
    }
    const sorted = [...spList]
    sorted.sort((a, b) => {
      // Date column — sort by adjusted per-start projection if pitcher starts that day
      const aStart = a.startDates?.find(s => s.date === sortCol)
      const bStart = b.startDates?.find(s => s.date === sortCol)
      const aDetail = projectionDetails[a.name]?.starts?.find((s: any) => s.date === sortCol)
      const bDetail = projectionDetails[b.name]?.starts?.find((s: any) => s.date === sortCol)
      const aVal = aStart ? (aDetail?.proj ?? fptsPerStart[a.name] ?? 0) : 0
      const bVal = bStart ? (bDetail?.proj ?? fptsPerStart[b.name] ?? 0) : 0
      return sortDir === 'desc' ? bVal - aVal : aVal - bVal
    })
    return sorted
  }, [spList, sortCol, sortDir, fptsPerStart, actualFpts, projectionDetails])

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
              {mode === 'sp'
                ? 'Available starting pitchers — check the ones to include in your analysis'
                : mode === 'rp'
                ? 'Available relievers by ownership and projection'
                : 'Available hitters — projected with the hitter model'}
            </p>
            {mode !== 'batters' && computedAt && (
              <div style={{ fontSize: 12, color: 'var(--ink-3)', opacity: 0.7, marginTop: 2, whiteSpace: 'nowrap' }}>
                Updated {relativeTime(computedAt)}{loading ? ' · refreshing…' : ''}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {/* SPs / RPs / Batters toggle */}
            <div style={{ display: 'flex', gap: 2, background: 'var(--paper-2)', padding: 3, borderRadius: 8 }}>
              {(['sp', 'rp', 'batters'] as const).map(m => {
                const active = mode === m
                const label = m === 'sp' ? 'SPs' : m === 'rp' ? 'RPs' : 'Batters'
                return (
                  <button key={m} onClick={() => setMode(m)} style={{
                    fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, padding: '5px 14px',
                    borderRadius: 6, border: 'none', cursor: 'pointer',
                    background: active ? 'var(--white)' : 'transparent',
                    color: active ? 'var(--ink)' : 'var(--ink-3)',
                    boxShadow: active ? 'var(--shadow)' : 'none', transition: 'all 0.15s',
                  }}>{label}</button>
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
            {mode !== 'batters' && (
              <button onClick={() => fetchFreeAgents(true)} disabled={loading}
                title="Refresh" aria-label="Refresh" style={{
                fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 600,
                padding: '8px 12px', borderRadius: 'var(--radius)',
                cursor: loading ? 'not-allowed' : 'pointer',
                border: '1.5px solid var(--border-strong)',
                background: 'var(--white)', color: 'var(--ink)',
                lineHeight: 1, opacity: loading ? 0.5 : 1,
              }}>
                ↻
              </button>
            )}
          </div>
        </div>

        {/* Name search (all tabs) + position filter (Batters only). */}
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <span style={{ position: 'absolute', left: 12, fontSize: 13, color: 'var(--ink-3)', pointerEvents: 'none' }}>⌕</span>
            <input
              type="text"
              value={nameQuery}
              onChange={e => setNameQuery(e.target.value)}
              placeholder={mode === 'batters' ? 'Search hitters…' : 'Search pitchers…'}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, padding: '8px 12px 8px 30px',
                borderRadius: 'var(--radius)', border: '1.5px solid var(--border-strong)',
                background: 'var(--white)', color: 'var(--ink)', outline: 'none', minWidth: 200,
              }}
            />
          </div>
          {mode === 'batters' && (
            <select
              value={posFilter}
              onChange={e => setPosFilter(e.target.value)}
              style={{
                fontFamily: 'var(--mono)', fontSize: 12, padding: '8px 12px',
                borderRadius: 'var(--radius)', border: '1.5px solid var(--border-strong)',
                background: 'var(--white)', color: 'var(--ink)', cursor: 'pointer', outline: 'none',
              }}
            >
              <option value="">All positions</option>
              {positionOptions.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          )}
          {(nameQuery || posFilter) && (
            <button
              onClick={() => { setNameQuery(''); setPosFilter('') }}
              style={{
                fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, padding: '8px 14px',
                borderRadius: 'var(--radius)', cursor: 'pointer',
                border: '1.5px solid var(--border-strong)', background: 'transparent', color: 'var(--ink-3)',
              }}
            >Clear</button>
          )}
        </div>

        {mode === 'batters' && <FAHitters period={selectedPeriod} nameQuery={nameQuery} posFilter={posFilter} />}

        {mode !== 'batters' && (<>
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
        ) : mode === 'sp' ? (
          <>
            <div style={{
              background: 'var(--blue-light)', border: '1px solid rgba(26,95,168,0.2)',
              borderRadius: 'var(--radius)', padding: '10px 14px',
              fontSize: 13, color: 'var(--blue)', marginBottom: 16,
            }}>
              Top available starting pitchers by ownership %.
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

              {sortedSPs.length === 0 ? (
                <div style={{ padding: '28px 12px', textAlign: 'center', fontSize: 13, color: 'var(--ink-3)' }}>
                  No starting pitchers match your filters.
                </div>
              ) : activeTab === 'schedule' ? (
              <ScheduleGrid
                pitchers={sortedSPs}
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
                  pitchers={sortedSPs}
                  fptsPerStart={fptsPerStart}
                  actualFpts={actualFpts}
                  projectionDetails={projectionDetails}
                  sortCol={sortCol}
                  sortDir={sortDir}
                  onSortChange={handleSort}
                />
              )}
            </div>
          </>
        ) : (
          <>
            <div style={{
              background: 'var(--blue-light)', border: '1px solid rgba(26,95,168,0.2)',
              borderRadius: 'var(--radius)', padding: '10px 14px',
              fontSize: 13, color: 'var(--blue)', marginBottom: 16,
            }}>
              Top available relievers by ownership %. Relievers have no scheduled
              starts, so they're ranked by projection and recent stats.
            </div>

            <div style={{
              background: 'var(--white)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px',
              boxShadow: 'var(--shadow)', marginBottom: 16,
            }}>
              <div style={{
                fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
                letterSpacing: '0.1em', color: 'var(--ink-3)',
                textTransform: 'uppercase', marginBottom: 12,
              }}>Available relievers</div>

              {rpList.length === 0 ? (
                <div style={{ padding: '28px 12px', textAlign: 'center', fontSize: 13, color: 'var(--ink-3)' }}>
                  No relievers match your filters.
                </div>
              ) : (
                <StatsTable
                  pitchers={rpList}
                  columns={RP_COLUMNS}
                  fptsPerStart={fptsPerStart}
                  actualFpts={actualFpts}
                  projectionDetails={projectionDetails}
                  defaultSortCol="projFpts"
                  defaultSortDir="desc"
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
function FAHitters({ period, nameQuery, posFilter }: { period: number | null; nameQuery: string; posFilter: string }) {
  const [tab, setTab] = useState<'schedule' | 'stats'>('schedule')
  // Shared between the Schedule and Stats tables so the sort survives the tab
  // switch (each table would otherwise reset it on unmount).
  const [sort, setSort] = useState<HitterSort | null>(null)
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

  // A hitter's pos may be composite (e.g. "2B/SS"), so split on "/" to match.
  const filteredHitters = useMemo(() => {
    const q = nameQuery.trim().toLowerCase()
    return hitters.filter(h => {
      const nameMatch = !q || h.name.toLowerCase().includes(q)
      const posMatch = !posFilter || h.pos.split('/').includes(posFilter)
      return nameMatch && posMatch
    })
  }, [hitters, nameQuery, posFilter])

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
        {filteredHitters.length === 0 ? (
          <div style={{ padding: '28px 12px', textAlign: 'center', fontSize: 13, color: 'var(--ink-3)' }}>
            No hitters match your filters.
          </div>
        ) : tab === 'schedule'
          ? <HitterScheduleGrid hitters={filteredHitters} weeks={weeks} weekDates={weekDates} today={today} showOwn actualsTracked sort={sort} onSortChange={setSort} />
          : <HitterStatsTable hitters={filteredHitters} weeks={weeks} showOwn leagueAvg={data?.leagueAvg} sort={sort} onSortChange={setSort} />}
      </div>
    </>
  )
}