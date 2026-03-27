import Head from 'next/head'
import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/router'

// ─── Types ────────────────────────────────────────────────────────────────────
interface RosterSP {
  name: string; team: string; slot: string; injuryStatus: string
  starts: number; projFpts: number; percentOwned: number
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

// ─── Sub-components ───────────────────────────────────────────────────────────
function Badge({ label, color }: { label: string; color: 'green' | 'amber' | 'red' | 'blue' | 'gray' }) {
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

function MetricCard({ label, value, sub, accent }: {
  label: string; value: string | number; sub?: string; accent?: 'ok' | 'warn' | 'bad'
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
      {sub && <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = Math.min(100, Math.round(value / max * 100))
  const color = pct >= 92 ? 'var(--green-mid)' : pct >= 65 ? '#e89020' : 'var(--red)'
  return (
    <div style={{ height: 6, background: 'var(--paper-3)', borderRadius: 99, overflow: 'hidden' }}>
      <div style={{
        height: '100%', width: `${pct}%`, borderRadius: 99,
        background: color, transition: 'width 0.5s ease',
      }} />
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

  const weekLabel = getWeekRange(weekStart, weekEnd)
  const needed = Math.max(0, limit - confirmedStarts)

  // Load config (team ID, starts limit) from env vars via /api/config
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        if (data.defaultLimit) setLimit(data.defaultLimit)
      })
      .catch(() => {})
  }, [])

  // On page load, check if we have cached roster data in sessionStorage
  // sessionStorage persists across page navigations in the same tab
  useEffect(() => {
    const cached = sessionStorage.getItem('skipper_roster')
    if (cached) {
      const data = JSON.parse(cached)
      setRosterSPs(data.rosterSPs || [])
      setConfirmedStarts(data.confirmedStarts || 0)
      setWeekStart(data.weekStart || '')
      setWeekEnd(data.weekEnd || '')
      setTeamName(data.teamName || '')
      setCurrentWeek(data.currentWeek || 1)
    }
  }, [])

  const fetchRoster = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const configRes = await fetch('/api/config')
      const config = await configRes.json()
      const teamId = config.teamId || '1'

      const res = await fetch(`/api/espn?teamId=${teamId}&week=${currentWeek}`)
      const data = await res.json()
      if (!data.ok) throw new Error(data.error || 'Failed to load ESPN data')

      const roster: RosterSP[] = data.rosterSPs.map((p: any) => ({
        ...p,
        starts: p.starts || 2,
        projFpts: p.projFpts || Math.round(Math.random() * 20 + 12),
      }))

      const starts = roster.reduce((a, p) => a + p.starts, 0)

      // Save to sessionStorage so Free Agents and Recommendations pages can use it
      const toCache = {
        rosterSPs: roster,
        confirmedStarts: starts,
        weekStart: data.weekStart || '',
        weekEnd: data.weekEnd || '',
        teamName: data.teamName || '',
        currentWeek: data.currentWeek || currentWeek,
      }
      sessionStorage.setItem('skipper_roster', JSON.stringify(toCache))

      setRosterSPs(roster)
      setConfirmedStarts(starts)
      setWeekStart(data.weekStart || '')
      setWeekEnd(data.weekEnd || '')
      setTeamName(data.teamName || '')
      setCurrentWeek(data.currentWeek || currentWeek)
    } catch (e: any) {
      setError(e.message || 'Failed to load roster')
    } finally {
      setLoading(false)
    }
  }, [currentWeek])

  return (
    <>
      <Head>
        <title>My Team · The Skipper</title>
      </Head>

      <style>{`
        table { border-collapse: collapse; width: 100%; }
        th {
          text-align: left; font-size: 11px; font-family: var(--mono);
          font-weight: 500; color: var(--ink-3); letter-spacing: 0.05em;
          padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        td { padding: 10px 10px; font-size: 13px; border-bottom: 1px solid var(--border); vertical-align: middle; }
        tr:last-child td { border-bottom: none; }
        input[type=number] {
          font-family: var(--mono); font-size: 13px;
          background: var(--white); border: 1px solid var(--border-strong);
          border-radius: var(--radius); padding: 8px 10px; outline: none; color: var(--ink);
        }
        input[type=number]:focus {
          border-color: var(--green-mid); box-shadow: 0 0 0 3px rgba(46,168,101,0.12);
        }
      `}</style>

      <div style={{ maxWidth: 860 }}>

        {/* Page header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>
              My Team
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {teamName ? `${teamName} · ` : ''}{weekLabel}
            </p>
          </div>
          <button
            onClick={fetchRoster}
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

        {rosterSPs.length === 0 && !loading ? (
          // Empty state — no data loaded yet
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
            <button
              onClick={() => router.push('/dashboard')}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: 'pointer', border: 'none',
                background: 'var(--ink)', color: 'var(--white)',
              }}
            >
              Go to Dashboard →
            </button>
          </div>
        ) : (
          <>
            {/* Metrics row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 16 }}>
              <MetricCard label="STARTS LIMIT" value={limit} />
              <MetricCard
                label="SCHEDULED" value={confirmedStarts}
                accent={confirmedStarts >= limit ? 'ok' : confirmedStarts >= limit * 0.7 ? 'warn' : 'bad'}
              />
              <MetricCard
                label="STILL NEEDED" value={needed}
                accent={needed === 0 ? 'ok' : needed <= 3 ? 'warn' : 'bad'}
              />
              <MetricCard label="ROSTERED SPs" value={rosterSPs.length} />
            </div>

            {/* Progress bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4 }}>
              <span>Starts utilization</span>
              <span>{confirmedStarts} / {limit}</span>
            </div>
            <ProgressBar value={confirmedStarts} max={limit} />
            <div style={{ marginBottom: 16 }} />

            {/* Roster table */}
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
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Pitcher</th><th>Team</th><th>Slot</th>
                      <th>Starts</th><th>Proj FPTS</th><th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...rosterSPs].sort((a, b) => {
                      const order = (s: string) => s === 'SP' ? 0 : s === 'RP' ? 1 : 2
                      if (order(a.slot) !== order(b.slot)) return order(a.slot) - order(b.slot)
                      if (b.starts !== a.starts) return b.starts - a.starts
                      return b.projFpts - a.projFpts
                    }).map((p, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 600 }}>{p.name}</td>
                        <td><span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{p.team}</span></td>
                        <td><Badge label={p.slot} color={p.slot === 'IL' ? 'red' : p.slot === 'RP' ? 'amber' : 'blue'} /></td>
                        <td style={{ textAlign: 'center', fontFamily: 'var(--mono)', fontWeight: 600 }}>{p.starts}</td>
                        <td style={{ textAlign: 'center', fontFamily: 'var(--mono)', fontWeight: 600, color: 'var(--green)' }}>{p.projFpts.toFixed(1)}</td>
                        <td>
                          {p.injuryStatus === 'Active'
                            ? <Badge label="Active" color="green" />
                            : p.injuryStatus === 'IL'
                            ? <Badge label="IL" color="red" />
                            : <Badge label={p.injuryStatus || 'Active'} color="amber" />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Starts limit editor */}
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
                  <input
                    type="number" value={limit} min={1} max={30}
                    onChange={e => setLimit(parseInt(e.target.value) || 0)}
                    style={{ width: 70 }}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ fontSize: 13, color: 'var(--ink-2)' }}>Confirmed starts:</label>
                  <input
                    type="number" value={confirmedStarts} min={0} max={30}
                    onChange={e => setConfirmedStarts(parseInt(e.target.value) || 0)}
                    style={{ width: 70 }}
                  />
                </div>
              </div>
            </div>

            {/* Navigation */}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                onClick={() => router.push('/free-agents')}
                style={{
                  fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                  padding: '9px 18px', borderRadius: 'var(--radius)',
                  cursor: 'pointer', border: 'none',
                  background: 'var(--ink)', color: 'var(--white)',
                  transition: 'all 0.15s',
                }}
              >
                View free agents →
              </button>
            </div>
          </>
        )}
      </div>
    </>
  )
}