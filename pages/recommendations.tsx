import Head from 'next/head'
import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'

// ─── Types ────────────────────────────────────────────────────────────────────
interface RosterSP {
  name: string; team: string; slot: string; injuryStatus: string
  starts: number; projFpts: number; percentOwned: number
}
interface FreeSP {
  name: string; team: string; injuryStatus: string
  percentOwned: number; projFpts: number; starts: number
  opps?: string; checked: boolean
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

const DAY_NAMES = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']

// ─── Sub-components ───────────────────────────────────────────────────────────
function Badge({ label, color }: { label: string; color: 'green'|'amber'|'red'|'blue'|'gray' }) {
  const styles: Record<string, React.CSSProperties> = {
    green: { background: 'var(--green-light)', color: 'var(--green)' },
    amber: { background: 'var(--amber-light)', color: 'var(--amber)' },
    red:   { background: 'var(--red-light)',   color: 'var(--red)' },
    blue:  { background: 'var(--blue-light)',  color: 'var(--blue)' },
    gray:  { background: 'var(--paper-2)',     color: 'var(--ink-3)' },
  }
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600,
      fontFamily: 'var(--mono)', padding: '2px 8px', borderRadius: 99,
      letterSpacing: '0.04em', ...styles[color],
    }}>{label}</span>
  )
}

function MetricCard({ label, value, accent }: {
  label: string; value: string|number; accent?: 'ok'|'warn'|'bad'
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

function Spinner() {
  return (
    <span style={{
      display: 'inline-block', width: 14, height: 14,
      border: '2px solid var(--paper-3)', borderTopColor: 'var(--green-mid)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
      verticalAlign: 'middle', marginRight: 8,
    }} />
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Recommendations() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [analysis, setAnalysis] = useState('')
  const [rosterSPs, setRosterSPs] = useState<RosterSP[]>([])
  const [freeSPs, setFreeSPs] = useState<FreeSP[]>([])
  const [limit, setLimit] = useState(12)
  const [confirmedStarts, setConfirmedStarts] = useState(0)
  const [weekStart, setWeekStart] = useState('')
  const [weekEnd, setWeekEnd] = useState('')

  const weekLabel = getWeekRange(weekStart, weekEnd)
  const todayName = DAY_NAMES[new Date().getDay() === 0 ? 6 : new Date().getDay() - 1]
  const needed = Math.max(0, limit - confirmedStarts)
  const projPts = rosterSPs.reduce((a, p) => a + (p.projFpts || 0), 0)

  // Load cached data from sessionStorage on page load
  useEffect(() => {
    const rosterCache = sessionStorage.getItem('skipper_roster')
    if (rosterCache) {
      const data = JSON.parse(rosterCache)
      setRosterSPs(data.rosterSPs || [])
      setConfirmedStarts(data.confirmedStarts || 0)
      setWeekStart(data.weekStart || '')
      setWeekEnd(data.weekEnd || '')
    }

    const faCache = sessionStorage.getItem('skipper_free_agents')
    if (faCache) {
      setFreeSPs(JSON.parse(faCache))
    }

    const configCache = sessionStorage.getItem('skipper_config')
    if (configCache) {
      const c = JSON.parse(configCache)
      if (c.limit) setLimit(c.limit)
    }

    // Also load cached analysis if available
    const analysisCache = sessionStorage.getItem('skipper_analysis')
    if (analysisCache) setAnalysis(analysisCache)
  }, [])

  // Load config
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => { if (data.defaultLimit) setLimit(data.defaultLimit) })
      .catch(() => {})
  }, [])

  const generateAnalysis = useCallback(async () => {
    setLoading(true)
    setError('')
    setAnalysis('')
    try {
      const payload = {
        limit,
        scheduledStarts: confirmedStarts,
        weekLabel,
        todayName,
        rosterSPs: rosterSPs.map(p => ({
          name: p.name, team: p.team, starts: p.starts,
          projFpts: p.projFpts, injuryStatus: p.injuryStatus,
        })),
        freeAgentSPs: freeSPs.filter(p => p.checked).map(p => ({
          name: p.name, team: p.team, starts: p.starts,
          projFpts: p.projFpts, percentOwned: p.percentOwned,
          opps: p.opps || '', injuryStatus: p.injuryStatus,
        })),
      }
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (!data.ok) throw new Error(data.error)
      setAnalysis(data.analysis)
      sessionStorage.setItem('skipper_analysis', data.analysis)
    } catch (e: any) {
      setError(e.message || 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }, [limit, confirmedStarts, weekLabel, todayName, rosterSPs, freeSPs])

  // Parse the analysis text into sections by ## heading
  function parseSections(text: string) {
    const result: Record<string, string> = {}
    const parts = text.split(/^##\s+/m)
    parts.forEach(p => {
      const nl = p.indexOf('\n')
      if (nl < 0) return
      const key = p.slice(0, nl).trim().toLowerCase()
      result[key] = p.slice(nl + 1).trim()
    })
    return result
  }

  const sections = analysis ? parseSections(analysis) : {}

  const hasData = rosterSPs.length > 0

  return (
    <>
      <Head>
        <title>Recommendations · The Skipper</title>
      </Head>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .rec-card {
          border: 1px solid var(--border); border-radius: var(--radius);
          padding: 14px 16px; margin-bottom: 10px; border-left-width: 3px;
        }
        .rec-add  { border-left-color: var(--green); }
        .rec-drop { border-left-color: var(--red); }
        .rec-hold { border-left-color: var(--blue); }
        .rec-watch{ border-left-color: #e89020; }
        .rec-name { font-size: 14px; font-weight: 700; margin-bottom: 5px; }
        .rec-body { font-size: 13px; color: var(--ink-2); line-height: 1.6; }
        .plan-row { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); align-items: flex-start; }
        .plan-row:last-child { border-bottom: none; }
        .plan-day { min-width: 90px; font-family: var(--mono); font-size: 12px; font-weight: 500; color: var(--ink-3); padding-top: 2px; }
        .plan-body { flex: 1; font-size: 13px; color: var(--ink-2); line-height: 1.5; }
        .plan-none { font-style: italic; color: var(--ink-3); }
      `}</style>

      <div style={{ maxWidth: 860 }}>

        {/* Page header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>
              Recommendations
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {weekLabel} · Claude-powered analysis
            </p>
          </div>
          {hasData && (
            <button
              onClick={generateAnalysis}
              disabled={loading}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: loading ? 'not-allowed' : 'pointer',
                border: 'none', background: 'var(--green)', color: 'var(--white)',
                opacity: loading ? 0.7 : 1, transition: 'all 0.15s',
              }}
            >
              {loading ? <><Spinner />Analyzing...</> : analysis ? '↻ Regenerate' : '🤖 Generate recommendations'}
            </button>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div style={{
            background: 'var(--red-light)', border: '1px solid var(--red)',
            borderRadius: 'var(--radius)', padding: '12px 16px',
            fontSize: 13, color: 'var(--red)', marginBottom: 16,
          }}>⚠ {error}</div>
        )}

        {!hasData ? (
          // Empty state
          <div style={{
            background: 'var(--white)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)', padding: '40px 24px',
            textAlign: 'center', boxShadow: 'var(--shadow)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>🤖</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No data loaded yet</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 20 }}>
              Load your roster and select free agents before generating recommendations.
            </div>
            <button
              onClick={() => router.push('/dashboard')}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: 'pointer', border: 'none',
                background: 'var(--ink)', color: 'var(--white)',
              }}
            >
              Start from Dashboard →
            </button>
          </div>
        ) : (
          <>
            {/* Metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 16 }}>
              <MetricCard label="STARTS LIMIT" value={limit} />
              <MetricCard label="SCHEDULED" value={confirmedStarts} />
              <MetricCard label="STILL NEEDED" value={needed} accent={needed === 0 ? 'ok' : needed <= 3 ? 'warn' : 'bad'} />
              <MetricCard label="PROJ SP PTS" value={Math.round(projPts)} accent="ok" />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4 }}>
              <span>Starts utilization</span><span>{confirmedStarts} / {limit}</span>
            </div>
            <ProgressBar value={confirmedStarts} max={limit} />
            <div style={{ marginBottom: 20 }} />

            {!analysis && !loading && (
              <div style={{
                background: 'var(--white)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-lg)', padding: '40px 24px',
                textAlign: 'center', boxShadow: 'var(--shadow)',
              }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>🤖</div>
                <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>Ready to analyze</div>
                <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>
                  Hit "Generate recommendations" above to run the Claude analysis.
                </div>
              </div>
            )}

            {loading && (
              <div style={{
                background: 'var(--white)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-lg)', padding: '32px 24px',
                textAlign: 'center', boxShadow: 'var(--shadow)',
              }}>
                <Spinner />
                <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>Claude is analyzing your roster...</span>
              </div>
            )}

            {analysis && (
              <>
                {/* Adds */}
                <div style={{
                  background: 'var(--white)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-lg)', padding: '20px 24px',
                  boxShadow: 'var(--shadow)', marginBottom: 16,
                }}>
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Adds</div>
                  {sections['adds']
                    ? sections['adds'].split('\n').filter(l => l.trim()).map((line, i) => {
                        const clean = line.replace(/^[-*\d.]\s*/, '')
                        const name = clean.match(/^([A-Z][a-z]+ [A-Z][a-zA-Z'-]+)/)?.[1] || ''
                        return (
                          <div key={i} className="rec-card rec-add">
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 5 }}>
                              <Badge label="ADD" color="green" />
                              {name && <span className="rec-name">{name}</span>}
                            </div>
                            <div className="rec-body">{clean}</div>
                          </div>
                        )
                      })
                    : <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>
                        {needed <= 0 ? "You're at the starts limit — no adds needed." : "No specific adds recommended."}
                      </div>
                  }
                </div>

                {/* Drops */}
                <div style={{
                  background: 'var(--white)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-lg)', padding: '20px 24px',
                  boxShadow: 'var(--shadow)', marginBottom: 16,
                }}>
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Drops</div>
                  {sections['drops']
                    ? sections['drops'].split('\n').filter(l => l.trim()).map((line, i) => {
                        const clean = line.replace(/^[-*\d.]\s*/, '')
                        const name = clean.match(/^([A-Z][a-z]+ [A-Z][a-zA-Z'-]+)/)?.[1] || ''
                        return (
                          <div key={i} className="rec-card rec-drop">
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 5 }}>
                              <Badge label="DROP" color="red" />
                              {name && <span className="rec-name">{name}</span>}
                            </div>
                            <div className="rec-body">{clean}</div>
                          </div>
                        )
                      })
                    : <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>Hold your current roster — no drops recommended.</div>
                  }
                </div>

                {/* Day-by-day plan */}
                <div style={{
                  background: 'var(--white)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-lg)', padding: '20px 24px',
                  boxShadow: 'var(--shadow)', marginBottom: 16,
                }}>
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Day-by-day plan</div>
                  {(() => {
                    const planText = sections['day-by-day plan'] || sections['day-by-day'] || ''
                    const lines = planText.split('\n').filter(l => l.trim())
                    const dayMap: Record<string, string> = {}
                    lines.forEach(l => {
                      const lower = l.toLowerCase()
                      const d = DAY_NAMES.find(day => lower.includes(day))
                      if (d) dayMap[d] = l.replace(/\*\*/g, '').replace(/^[A-Za-z]+:\s*/, '').trim()
                    })
                    return DAY_NAMES.map(d => {
                      const action = dayMap[d] || ''
                      const isNone = !action || action.toLowerCase().includes('no move') || action.toLowerCase().includes('no action')
                      return (
                        <div key={d} className="plan-row">
                          <div className="plan-day">{d.slice(0,3).toUpperCase()}</div>
                          <div className={`plan-body ${isNone ? 'plan-none' : ''}`}>
                            {action || 'No moves needed'}
                          </div>
                        </div>
                      )
                    })
                  })()}
                </div>

                {/* Watch list */}
                <div style={{
                  background: 'var(--white)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-lg)', padding: '20px 24px',
                  boxShadow: 'var(--shadow)', marginBottom: 16,
                }}>
                  <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 12 }}>Watch list</div>
                  {(sections['watch list'] || sections['watch'] || '').split('\n').filter(l => l.trim()).map((line, i) => {
                    const clean = line.replace(/^[-*\d.]\s*/, '')
                    const name = clean.match(/^([A-Z][a-z]+ [A-Z][a-zA-Z'-]+)/)?.[1] || ''
                    return (
                      <div key={i} className="rec-card rec-watch">
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 5 }}>
                          <Badge label="WATCH" color="amber" />
                          {name && <span className="rec-name">{name}</span>}
                        </div>
                        <div className="rec-body">{clean}</div>
                      </div>
                    )
                  })}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </>
  )
}