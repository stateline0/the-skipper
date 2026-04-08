import Head from 'next/head'
import { useState, useEffect, useCallback, useRef } from 'react'
import { useRouter } from 'next/router'
import ScheduleGrid from '../components/ScheduleGrid'

interface FreeSP {
  name: string; team: string; slot: string; injuryStatus: string
  percentOwned: number; projFpts: number; starts: number
  opps?: string; checked: boolean; startDates?: any[]
}

interface MatchupPeriod {
  period: number; label: string; start: string; end: string; limit: number
}

export default function FreeAgents() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [matchupPeriods, setMatchupPeriods] = useState<MatchupPeriod[]>([])
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [freeSPs, setFreeSPs] = useState<FreeSP[]>([])
  const [schedule, setSchedule] = useState<Record<string, any>>({})
  const [matchupDates, setMatchupDates] = useState<string[]>([])
  const [actualFpts, setActualFpts] = useState<Record<string, Record<string, number>>>({})

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        if (data.matchupPeriods) setMatchupPeriods(data.matchupPeriods)
        const saved = sessionStorage.getItem('skipper_selected_period')
        const period = saved ? parseInt(saved) : (data.currentPeriod ?? 1)
        setSelectedPeriod(period)
      })
      .catch(() => {})

    const cached = sessionStorage.getItem('skipper_free_agents')
    if (cached) {
      const data = JSON.parse(cached)
      if (!data.matchupDates || data.matchupDates.length === 0) return
      setFreeSPs(data.freeSPs || [])
      setSchedule(data.schedule || {})
      setMatchupDates(data.matchupDates || [])
      setActualFpts(data.actualFpts || {})
    }
  }, [])

  const isFirstRender = useRef(true)

  useEffect(() => {
    if (selectedPeriod === null) return

    if (isFirstRender.current) {
      isFirstRender.current = false
      const cached = sessionStorage.getItem('skipper_free_agents')
      if (!cached) {
        fetchFreeAgents()
      } else {
        const data = JSON.parse(cached)
        if (!data.matchupDates || data.matchupDates.length === 0) fetchFreeAgents()
      }
      return
    }

    fetchFreeAgents()
  }, [selectedPeriod, matchupPeriods])

  const fetchFreeAgents = useCallback(async () => {
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

      const fas: FreeSP[] = (data.freeAgentSPs || []).map((p: any) => ({
        ...p,
        slot: p.slot || 'SP',
        starts: p.starts ?? 0,
        projFpts: p.projFpts ?? 0,
        opps: p.opps || '',
        checked: p.percentOwned >= 15,
      }))

      const toCache = {
        freeSPs: fas,
        schedule: data.schedule || {},
        matchupDates: data.matchupDates || [],
        actualFpts: data.actualFpts || {},
      }
      sessionStorage.setItem('skipper_free_agents', JSON.stringify(toCache))
      setFreeSPs(fas)
      setSchedule(data.schedule || {})
      setMatchupDates(data.matchupDates || [])
      setActualFpts(data.actualFpts || {})
    } catch (e: any) {
      setError(e.message || 'Failed to load free agents')
    } finally {
      setLoading(false)
    }
  }, [selectedPeriod])

  function toggleCheck(index: number) {
    const updated = [...freeSPs]
    updated[index] = { ...updated[index], checked: !updated[index].checked }
    setFreeSPs(updated)
    const cached = JSON.parse(sessionStorage.getItem('skipper_free_agents') || '{}')
    sessionStorage.setItem('skipper_free_agents', JSON.stringify({ ...cached, freeSPs: updated }))
  }

  const selectedCount = freeSPs.filter(p => p.checked).length

  return (
    <>
      <Head><title>Free Agents · The Skipper</title></Head>

      <style>{`
        input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--green-mid); cursor: pointer; }
      `}</style>

      <div style={{ maxWidth: 1100 }}>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Free Agents</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              Available SPs — check the ones to include in your analysis
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
            <button onClick={fetchFreeAgents} disabled={loading} style={{
              fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
              padding: '9px 18px', borderRadius: 'var(--radius)',
              cursor: loading ? 'not-allowed' : 'pointer',
              border: '1.5px solid var(--border-strong)',
              background: 'transparent', color: 'var(--ink)',
              opacity: loading ? 0.5 : 1,
            }}>
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
            <button onClick={fetchFreeAgents} style={{
              fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
              padding: '9px 18px', borderRadius: 'var(--radius)',
              cursor: 'pointer', border: 'none', background: 'var(--ink)', color: 'var(--white)',
            }}>Load free agents →</button>
          </div>
        ) : (
          <>
            <div style={{
              background: 'var(--blue-light)', border: '1px solid rgba(26,95,168,0.2)',
              borderRadius: 'var(--radius)', padding: '10px 14px',
              fontSize: 13, color: 'var(--blue)', marginBottom: 16,
            }}>
              Top available SPs by ownership %. Check the ones you want Claude to consider for adds.
            </div>

            <div style={{
              background: 'var(--white)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px',
              boxShadow: 'var(--shadow)', marginBottom: 16,
            }}>
              <ScheduleGrid
                pitchers={freeSPs}
                schedule={schedule}
                matchupDates={matchupDates}
                actualFpts={actualFpts}
                prefixHeaders={<th style={{ padding: '8px 6px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, color: 'var(--ink-3)', borderBottom: '1px solid var(--border)', minWidth: 32 }}></th>}
                suffixHeaders={<th style={{ padding: '8px 6px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, color: 'var(--ink-3)', borderBottom: '1px solid var(--border)', minWidth: 52, whiteSpace: 'nowrap' }}>Own%</th>}
                renderPrefix={(pitcher, i) => (
                  <td style={{ padding: '8px 6px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', textAlign: 'center' }}
                    onClick={e => { e.stopPropagation(); toggleCheck(i) }}>
                    <input type="checkbox" checked={(pitcher as FreeSP).checked || false}
                      onChange={() => toggleCheck(i)} />
                  </td>
                )}
                renderSuffix={(pitcher) => (
                  <td style={{ padding: '8px 6px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', textAlign: 'center', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
                    {(pitcher as FreeSP).percentOwned ?? 0}%
                  </td>
                )}
                onRowClick={toggleCheck}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'var(--ink-3)' }}>
                {selectedCount} pitcher{selectedCount !== 1 ? 's' : ''} selected for analysis
              </span>
              <button onClick={() => router.push('/recommendations')} style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: 'pointer', border: 'none',
                background: 'var(--green)', color: 'var(--white)',
              }}>Generate recommendations →</button>
            </div>
          </>
        )}
      </div>
    </>
  )
}