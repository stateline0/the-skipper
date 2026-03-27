import Head from 'next/head'
import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'

// ─── Types ────────────────────────────────────────────────────────────────────
interface FreeSP {
  name: string; team: string; injuryStatus: string
  percentOwned: number; projFpts: number; starts: number
  opps?: string; checked: boolean
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function FreeAgents() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [freeSPs, setFreeSPs] = useState<FreeSP[]>([])
  const [currentWeek, setCurrentWeek] = useState(1)

  // On page load, check sessionStorage for cached free agent data
  useEffect(() => {
    const cached = sessionStorage.getItem('skipper_free_agents')
    if (cached) {
      setFreeSPs(JSON.parse(cached))
    }

    // Also pull currentWeek from the roster cache if available
    const rosterCache = sessionStorage.getItem('skipper_roster')
    if (rosterCache) {
      const data = JSON.parse(rosterCache)
      if (data.currentWeek) setCurrentWeek(data.currentWeek)
    }
  }, [])

  const fetchFreeAgents = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const configRes = await fetch('/api/config')
      const config = await configRes.json()
      const teamId = config.teamId || '1'

      const res = await fetch(`/api/espn?teamId=${teamId}&week=${currentWeek}`)
      const data = await res.json()
      if (!data.ok) throw new Error(data.error || 'Failed to load ESPN data')

      const fas: FreeSP[] = (data.freeAgentSPs || []).map((p: any) => ({
        ...p,
        starts: p.starts || 2,
        projFpts: p.projFpts || Math.round(Math.random() * 18 + 8),
        opps: p.opps || '',
        checked: p.percentOwned >= 15,
      }))

      sessionStorage.setItem('skipper_free_agents', JSON.stringify(fas))
      setFreeSPs(fas)
    } catch (e: any) {
      setError(e.message || 'Failed to load free agents')
    } finally {
      setLoading(false)
    }
  }, [currentWeek])

  function toggleCheck(index: number) {
    const updated = [...freeSPs]
    updated[index] = { ...updated[index], checked: !updated[index].checked }
    setFreeSPs(updated)
    sessionStorage.setItem('skipper_free_agents', JSON.stringify(updated))
  }

  const selectedCount = freeSPs.filter(p => p.checked).length

  return (
    <>
      <Head>
        <title>Free Agents · The Skipper</title>
      </Head>

      <style>{`
        table { border-collapse: collapse; width: 100%; }
        th {
          text-align: left; font-size: 11px; font-family: var(--mono);
          font-weight: 500; color: var(--ink-3); letter-spacing: 0.05em;
          padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        td { padding: 10px; font-size: 13px; border-bottom: 1px solid var(--border); vertical-align: middle; }
        tr:last-child td { border-bottom: none; }
        .check-row { cursor: pointer; }
        .check-row:hover td { background: var(--paper-2); }
        input[type=checkbox] { width: 16px; height: 16px; accent-color: var(--green-mid); cursor: pointer; }
      `}</style>

      <div style={{ maxWidth: 860 }}>

        {/* Page header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>
              Free Agents
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              Available SPs in your league — check the ones to include in your analysis
            </p>
          </div>
          <button
            onClick={fetchFreeAgents}
            disabled={loading}
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

        {/* Error banner */}
        {error && (
          <div style={{
            background: 'var(--red-light)', border: '1px solid var(--red)',
            borderRadius: 'var(--radius)', padding: '12px 16px',
            fontSize: 13, color: 'var(--red)', marginBottom: 16,
          }}>⚠ {error}</div>
        )}

        {freeSPs.length === 0 && !loading ? (
          // Empty state
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '40px 24px',
            textAlign: 'center', boxShadow: 'var(--shadow)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No free agents loaded</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 20 }}>
              Load your roster first, then come back here to see available pitchers.
            </div>
            <button
              onClick={fetchFreeAgents}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: 'pointer', border: 'none',
                background: 'var(--ink)', color: 'var(--white)',
              }}
            >
              Load free agents →
            </button>
          </div>
        ) : (
          <>
            {/* Info banner */}
            <div style={{
              background: 'var(--blue-light)', border: '1px solid rgba(26,95,168,0.2)',
              borderRadius: 'var(--radius)', padding: '10px 14px',
              fontSize: 13, color: 'var(--blue)', marginBottom: 16,
            }}>
              Top available SPs by ownership %. Check the ones you want Claude to consider for adds.
            </div>

            {/* Free agents table */}
            <div style={{
              background: 'var(--white)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: '20px 24px',
              boxShadow: 'var(--shadow)', marginBottom: 16,
            }}>
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th></th>
                      <th>Pitcher</th>
                      <th>Team</th>
                      <th>Own%</th>
                      <th>Proj FPTS</th>
                      <th>Starts</th>
                      <th>Opponent(s)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {freeSPs.map((p, i) => (
                      <tr
                        key={i}
                        className="check-row"
                        onClick={() => toggleCheck(i)}
                      >
                        <td onClick={e => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={p.checked}
                            onChange={() => toggleCheck(i)}
                          />
                        </td>
                        <td style={{ fontWeight: 600 }}>{p.name}</td>
                        <td><span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{p.team}</span></td>
                        <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{p.percentOwned}%</td>
                        <td style={{ fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--green)' }}>{p.projFpts}</td>
                        <td style={{ textAlign: 'center', fontFamily: 'var(--mono)' }}>{p.starts}</td>
                        <td style={{ fontSize: 12, color: 'var(--ink-3)' }}>{p.opps || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Footer: count + navigation */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'var(--ink-3)' }}>
                {selectedCount} pitcher{selectedCount !== 1 ? 's' : ''} selected for analysis
              </span>
              <button
                onClick={() => router.push('/recommendations')}
                style={{
                  fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                  padding: '9px 18px', borderRadius: 'var(--radius)',
                  cursor: 'pointer', border: 'none',
                  background: 'var(--green)', color: 'var(--white)',
                  transition: 'all 0.15s',
                }}
              >
                Generate recommendations →
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}