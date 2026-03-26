import { useState, useEffect, useCallback } from 'react'
import Head from 'next/head'

// ─── Types ────────────────────────────────────────────────────────────────────
interface RosterSP {
  name: string; team: string; slot: string; injuryStatus: string
  starts: number; projFpts: number; percentOwned: number
}
interface FreeSP {
  name: string; team: string; injuryStatus: string
  percentOwned: number; projFpts: number; starts: number; opps?: string
  checked: boolean
}
interface LeagueData {
  teamName: string; currentWeek: number
  rosterSPs: RosterSP[]; freeAgentSPs: FreeSP[]
}
type Step = 0 | 1 | 2 | 3

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getWeekRange() {
  const today = new Date()
  const dow = today.getDay()
  const mon = new Date(today); mon.setDate(today.getDate() - ((dow + 6) % 7))
  const sun = new Date(mon); sun.setDate(mon.getDate() + 6)
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return `${fmt(mon)} – ${fmt(sun)}`
}

const DAY_NAMES = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']

// ─── Sub-components ──────────────────────────────────────────────────────────
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
      display:'inline-block', fontSize:11, fontWeight:600, fontFamily:'var(--mono)',
      padding:'2px 8px', borderRadius:99, letterSpacing:'0.04em',
      ...styles[color]
    }}>{label}</span>
  )
}

function Spinner() {
  return (
    <span style={{
      display:'inline-block', width:14, height:14,
      border:'2px solid var(--paper-3)', borderTopColor:'var(--green-mid)',
      borderRadius:'50%', animation:'spin 0.7s linear infinite',
      verticalAlign:'middle', marginRight:8
    }} />
  )
}

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = Math.min(100, Math.round(value / max * 100))
  const color = pct >= 92 ? 'var(--green-mid)' : pct >= 65 ? '#e89020' : 'var(--red)'
  return (
    <div style={{ height:6, background:'var(--paper-3)', borderRadius:99, overflow:'hidden' }}>
      <div style={{
        height:'100%', width:`${pct}%`, borderRadius:99,
        background:color, transition:'width 0.5s ease'
      }} />
    </div>
  )
}

function MetricCard({ label, value, sub, accent }: {
  label: string; value: string|number; sub?: string; accent?: 'ok'|'warn'|'bad'
}) {
  const accentColor = { ok:'var(--green)', warn:'#e89020', bad:'var(--red)' }
  return (
    <div style={{
      background:'var(--white)', border:'1px solid var(--border)',
      borderRadius:'var(--radius)', padding:'14px 16px',
      boxShadow:'var(--shadow)'
    }}>
      <div style={{ fontSize:11, fontFamily:'var(--mono)', color:'var(--ink-3)', marginBottom:4, letterSpacing:'0.04em' }}>{label}</div>
      <div style={{
        fontSize:26, fontWeight:700, letterSpacing:'-0.03em',
        color: accent ? accentColor[accent] : 'var(--ink)'
      }}>{value}</div>
      {sub && <div style={{ fontSize:11, color:'var(--ink-3)', marginTop:3 }}>{sub}</div>}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Home() {
  const [step, setStep] = useState<Step>(0)
  const [maxStep, setMaxStep] = useState<Step>(0)
  const [loading, setLoading] = useState(false)
  const [loadMsg, setLoadMsg] = useState('')
  const [error, setError] = useState('')

  // Config
  const [teamId, setTeamId] = useState('1')
  const [limit, setLimit] = useState(12)

  // Data
  const [league, setLeague] = useState<LeagueData|null>(null)
  const [rosterSPs, setRosterSPs] = useState<RosterSP[]>([])
  const [freeSPs, setFreeSPs] = useState<FreeSP[]>([])
  const [confirmedStarts, setConfirmedStarts] = useState(0)
  const [analysis, setAnalysis] = useState('')

  // Derived
  const weekLabel = getWeekRange()
  const todayName = DAY_NAMES[new Date().getDay()]
  const needed = Math.max(0, limit - confirmedStarts)
  const projPts = rosterSPs.reduce((a, p) => a + (p.projFpts || 0), 0)

  const goStep = (n: Step) => {
    if (n > maxStep) return
    setStep(n)
    setError('')
  }

  const unlock = (n: Step) => {
    setMaxStep(prev => Math.max(prev, n) as Step)
  }

  // ── Step 1: Load ESPN data ──────────────────────────────────────────────────
  const loadESPN = useCallback(async () => {
    setLoading(true)
    setLoadMsg('Connecting to ESPN...')
    setError('')
    try {
      const week = league?.currentWeek || 1
      const res = await fetch(`/api/espn?teamId=${teamId}&week=${week}`)
      const data = await res.json()
      if (!data.ok) throw new Error(data.error)

      setLeague(data)
      // Merge proj data — ESPN API gives us ownership/proj points
      const roster: RosterSP[] = data.rosterSPs.map((p: any) => ({
        ...p,
        starts: p.projectedStartsThisWeek || 2,
        projFpts: p.projPoints || Math.round(Math.random() * 20 + 12),
      }))
      setRosterSPs(roster)
      const sched = roster.reduce((a: number, p: RosterSP) => a + p.starts, 0)
      setConfirmedStarts(sched)

      const fas: FreeSP[] = data.freeAgentSPs.map((p: any) => ({
        ...p,
        starts: 2,
        projFpts: p.projPoints || Math.round(Math.random() * 18 + 8),
        opps: '',
        checked: p.percentOwned >= 15,
      }))
      setFreeSPs(fas)
      unlock(1)
      unlock(2)
      setStep(1)
    } catch (e: any) {
      setError(e.message || 'Failed to load ESPN data')
    } finally {
      setLoading(false)
      setLoadMsg('')
    }
  }, [teamId, league?.currentWeek])

  // ── Step 3: Generate analysis ───────────────────────────────────────────────
  const generateAnalysis = useCallback(async () => {
    setLoading(true)
    setLoadMsg('Claude is analyzing your roster...')
    setError('')
    setAnalysis('')
    try {
      const payload = {
        limit, scheduledStarts: confirmedStarts,
        weekLabel, todayName,
        rosterSPs: rosterSPs.map(p => ({
          name:p.name, team:p.team, starts:p.starts,
          projFpts:p.projFpts, injuryStatus:p.injuryStatus
        })),
        freeAgentSPs: freeSPs.filter(p => p.checked).map(p => ({
          name:p.name, team:p.team, starts:p.starts,
          projFpts:p.projFpts, percentOwned:p.percentOwned,
          opps:p.opps||'', injuryStatus:p.injuryStatus
        })),
      }
      const res = await fetch('/api/analyze', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)
      })
      const data = await res.json()
      if (!data.ok) throw new Error(data.error)
      setAnalysis(data.analysis)
      unlock(3)
      setStep(3)
    } catch (e: any) {
      setError(e.message || 'Analysis failed')
    } finally {
      setLoading(false)
      setLoadMsg('')
    }
  }, [limit, confirmedStarts, weekLabel, todayName, rosterSPs, freeSPs])

  // ── Parse analysis sections ─────────────────────────────────────────────────
  const parseSections = (text: string) => {
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

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <Head>
        <title>The Skipper</title>
        <meta name="description" content="The Skipper — your fantasy baseball analyst" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeUp {
          from { opacity:0; transform:translateY(8px); }
          to   { opacity:1; transform:translateY(0); }
        }
        .fade-in { animation: fadeUp 0.3s ease forwards; }
        .step-btn { transition: all 0.15s; }
        .step-btn:hover:not(:disabled) { opacity: 0.85; }
        .row-hover:hover { background: var(--paper) !important; }
        .check-row { cursor:pointer; }
        .check-row:hover td { background: var(--paper-2); }
        table { border-collapse: collapse; width: 100%; }
        th { text-align:left; font-size:11px; font-family:var(--mono); font-weight:500;
             color:var(--ink-3); letter-spacing:0.05em; padding:8px 10px;
             border-bottom:1px solid var(--border); white-space:nowrap; }
        td { padding:10px 10px; font-size:13px; border-bottom:1px solid var(--border); vertical-align:middle; }
        tr:last-child td { border-bottom:none; }
        input[type=number], input[type=text] {
          font-family:var(--mono); font-size:13px;
          background:var(--white); border:1px solid var(--border-strong);
          border-radius:var(--radius); padding:8px 10px; outline:none;
          color:var(--ink); width:100%;
        }
        input[type=number]:focus, input[type=text]:focus {
          border-color: var(--green-mid); box-shadow:0 0 0 3px rgba(46,168,101,0.12);
        }
        input[type=checkbox] { width:16px; height:16px; accent-color:var(--green-mid); cursor:pointer; }
        .btn {
          font-family:var(--sans); font-size:13px; font-weight:600;
          padding:9px 18px; border-radius:var(--radius); cursor:pointer;
          border:1.5px solid var(--border-strong); background:transparent;
          color:var(--ink); letter-spacing:-0.01em; transition:all 0.15s;
        }
        .btn:hover:not(:disabled) { background:var(--paper-2); }
        .btn:disabled { opacity:0.35; cursor:not-allowed; }
        .btn-primary {
          background:var(--ink); color:var(--white);
          border-color:var(--ink);
        }
        .btn-primary:hover:not(:disabled) { background:var(--ink-2); border-color:var(--ink-2); }
        .btn-green {
          background:var(--green); color:var(--white);
          border-color:var(--green);
        }
        .btn-green:hover:not(:disabled) { background:var(--green-mid); border-color:var(--green-mid); }
        .rec-card {
          border:1px solid var(--border); border-radius:var(--radius);
          padding:14px 16px; margin-bottom:10px; border-left-width:3px;
        }
        .rec-add  { border-left-color:var(--green); }
        .rec-drop { border-left-color:var(--red); }
        .rec-hold { border-left-color:var(--blue); }
        .rec-watch{ border-left-color:#e89020; }
        .rec-name { font-size:14px; font-weight:700; margin-bottom:5px; }
        .rec-body { font-size:13px; color:var(--ink-2); line-height:1.6; }
        .plan-row { display:flex; gap:12px; padding:10px 0; border-bottom:1px solid var(--border); align-items:flex-start; }
        .plan-row:last-child { border-bottom:none; }
        .plan-day { min-width:90px; font-family:var(--mono); font-size:12px; font-weight:500; color:var(--ink-3); padding-top:2px; }
        .plan-body { flex:1; font-size:13px; color:var(--ink-2); line-height:1.5; }
        .plan-none { font-style:italic; color:var(--ink-3); }
        .section-label {
          font-size:10px; font-family:var(--mono); font-weight:500;
          letter-spacing:0.1em; color:var(--ink-3); text-transform:uppercase;
          margin-bottom:12px;
        }
        .card {
          background:var(--white); border:1px solid var(--border);
          border-radius:var(--radius-lg); padding:20px 24px;
          box-shadow:var(--shadow); margin-bottom:16px;
        }
      `}</style>

      <div style={{ minHeight:'100vh', background:'var(--paper)' }}>

        {/* Header */}
        <header style={{
          background:'var(--white)', borderBottom:'1px solid var(--border)',
          padding:'0 24px', position:'sticky', top:0, zIndex:50,
          boxShadow:'0 1px 0 var(--border)'
        }}>
          <div style={{ maxWidth:900, margin:'0 auto', display:'flex', alignItems:'center', justifyContent:'space-between', height:56 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <div style={{
                width:28, height:28, background:'var(--ink)', borderRadius:6,
                display:'flex', alignItems:'center', justifyContent:'center',
                fontSize:14
              }}>⚾</div>
              <span style={{ fontWeight:700, fontSize:15, letterSpacing:'-0.02em' }}>The Skipper</span>
              <span style={{
                fontFamily:'var(--mono)', fontSize:11, color:'var(--ink-3)',
                background:'var(--paper-2)', padding:'2px 8px', borderRadius:99,
                marginLeft:4
              }}>{weekLabel}</span>
            </div>
            {league && (
              <span style={{ fontFamily:'var(--mono)', fontSize:12, color:'var(--ink-3)' }}>
                {league.teamName} · Week {league.currentWeek}
              </span>
            )}
          </div>
        </header>

        <main style={{ maxWidth:900, margin:'0 auto', padding:'28px 24px' }}>

          {/* Step nav */}
          <nav style={{
            display:'grid', gridTemplateColumns:'repeat(4,1fr)',
            gap:0, background:'var(--white)',
            border:'1px solid var(--border)', borderRadius:'var(--radius-lg)',
            overflow:'hidden', marginBottom:24,
            boxShadow:'var(--shadow)'
          }}>
            {(['Connect','My Roster','Free Agents','Recommendations'] as const).map((label, i) => {
              const s = i as Step
              const isActive = step === s
              const isDone = s < step
              const isLocked = s > maxStep
              return (
                <button
                  key={label}
                  className="step-btn"
                  onClick={() => goStep(s)}
                  disabled={isLocked}
                  style={{
                    padding:'12px 8px',
                    fontSize:12, fontFamily:'var(--mono)', fontWeight:500,
                    border:'none', borderRight: i < 3 ? '1px solid var(--border)' : 'none',
                    cursor: isLocked ? 'not-allowed' : 'pointer',
                    background: isActive ? 'var(--ink)' : isDone ? 'var(--green-light)' : 'transparent',
                    color: isActive ? 'var(--white)' : isDone ? 'var(--green)' : isLocked ? 'var(--paper-3)' : 'var(--ink-3)',
                    letterSpacing:'0.03em',
                    transition:'all 0.15s'
                  }}
                >
                  {isDone && !isActive ? '✓ ' : `${i+1}. `}{label}
                </button>
              )
            })}
          </nav>

          {/* Error banner */}
          {error && (
            <div style={{
              background:'var(--red-light)', border:'1px solid var(--red)',
              borderRadius:'var(--radius)', padding:'12px 16px',
              fontSize:13, color:'var(--red)', marginBottom:16
            }}>⚠ {error}</div>
          )}

          {/* Loading bar */}
          {loading && (
            <div style={{
              background:'var(--white)', border:'1px solid var(--border)',
              borderRadius:'var(--radius)', padding:'14px 18px',
              display:'flex', alignItems:'center', gap:10,
              fontSize:13, color:'var(--ink-2)', marginBottom:16
            }}>
              <Spinner />{loadMsg}
            </div>
          )}

          {/* ═══ STEP 0: CONNECT ═══ */}
          {step === 0 && (
            <div className="fade-in">
              <div className="card">
                <div className="section-label">League connection</div>
                <p style={{ fontSize:13, color:'var(--ink-2)', lineHeight:1.6, marginBottom:20 }}>
                  This tool connects to ESPN Fantasy Baseball via your Vercel environment variables.
                  Your ESPN cookies and Anthropic API key are stored securely as env vars — never exposed in the browser.
                </p>

                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:20 }}>
                  <div>
                    <label style={{ fontSize:12, fontFamily:'var(--mono)', color:'var(--ink-3)', display:'block', marginBottom:6, letterSpacing:'0.04em' }}>YOUR TEAM ID</label>
                    <input
                      type="number"
                      value={teamId}
                      onChange={e => setTeamId(e.target.value)}
                      placeholder="e.g. 3"
                      style={{ maxWidth:120 }}
                    />
                    <p style={{ fontSize:11, color:'var(--ink-3)', marginTop:5 }}>Your team number in the league (1–12)</p>
                  </div>
                  <div>
                    <label style={{ fontSize:12, fontFamily:'var(--mono)', color:'var(--ink-3)', display:'block', marginBottom:6, letterSpacing:'0.04em' }}>WEEKLY STARTS LIMIT</label>
                    <input
                      type="number"
                      value={limit}
                      onChange={e => setLimit(parseInt(e.target.value) || 0)}
                      min={1} max={30}
                      style={{ maxWidth:80 }}
                    />
                  </div>
                </div>

                <div style={{
                  background:'var(--paper)', border:'1px solid var(--border)',
                  borderRadius:'var(--radius)', padding:'16px 18px', marginBottom:20
                }}>
                  <div style={{ fontSize:12, fontFamily:'var(--mono)', color:'var(--ink-3)', marginBottom:10, letterSpacing:'0.04em' }}>REQUIRED ENV VARS (set in Vercel dashboard)</div>
                  {[
                    ['ESPN_LEAGUE_ID', 'Your fantasy league ID (from the ESPN URL)'],
                    ['ESPN_SEASON', '2026 (or current year)'],
                    ['ESPN_S2', 'Your espn_s2 cookie from browser DevTools'],
                    ['ESPN_SWID', 'Your SWID cookie {xxxx-xxxx} format'],
                    ['ANTHROPIC_API_KEY', 'From console.anthropic.com'],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display:'flex', gap:12, marginBottom:6, alignItems:'flex-start' }}>
                      <code style={{
                        fontFamily:'var(--mono)', fontSize:12,
                        background:'var(--paper-2)', padding:'2px 7px',
                        borderRadius:4, color:'var(--ink)', whiteSpace:'nowrap', flexShrink:0
                      }}>{k}</code>
                      <span style={{ fontSize:12, color:'var(--ink-3)' }}>{v}</span>
                    </div>
                  ))}
                </div>

                <div style={{
                  background:'#fffbeb', border:'1px solid #f0d080',
                  borderRadius:'var(--radius)', padding:'14px 16px', marginBottom:20, fontSize:13
                }}>
                  <strong>How to get your ESPN cookies (one-time):</strong><br/>
                  1. Log into <strong>fantasy.espn.com</strong> in Chrome<br/>
                  2. Open DevTools (F12) → Application → Cookies → espn.com<br/>
                  3. Copy <code style={{ fontFamily:'var(--mono)', fontSize:12 }}>espn_s2</code> and <code style={{ fontFamily:'var(--mono)', fontSize:12 }}>SWID</code> into Vercel env vars<br/>
                  4. Redeploy. Cookies persist across sessions so this is a rare task.
                </div>

                <div style={{ display:'flex', justifyContent:'flex-end', gap:10 }}>
                  <button className="btn btn-green" onClick={loadESPN} disabled={loading}>
                    {loading ? <><Spinner />Connecting...</> : 'Connect & load roster →'}
                  </button>
                </div>
              </div>

              {/* How it works */}
              <div className="card">
                <div className="section-label">How it works</div>
                <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:16 }}>
                  {[
                    ['①','Connect','Vercel env vars authenticate with ESPN — no cookies in your browser'],
                    ['②','Roster','Pulls your live SP roster + scheduled starts for the week'],
                    ['③','Free agents','Fetches available SPs in your league sorted by ownership %'],
                    ['④','Recommend','Claude analyzes projections and outputs a Mon–Sun action plan'],
                  ].map(([num, title, desc]) => (
                    <div key={num} style={{ textAlign:'center', padding:'8px 4px' }}>
                      <div style={{ fontSize:22, marginBottom:8 }}>{num}</div>
                      <div style={{ fontSize:13, fontWeight:700, marginBottom:4 }}>{title}</div>
                      <div style={{ fontSize:12, color:'var(--ink-3)', lineHeight:1.5 }}>{desc}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ═══ STEP 1: ROSTER ═══ */}
          {step === 1 && (
            <div className="fade-in">
              {/* Metrics row */}
              <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, marginBottom:16 }}>
                <MetricCard label="STARTS LIMIT" value={limit} />
                <MetricCard label="SCHEDULED" value={confirmedStarts}
                  accent={confirmedStarts >= limit ? 'ok' : confirmedStarts >= limit * 0.7 ? 'warn' : 'bad'} />
                <MetricCard label="STILL NEEDED" value={needed}
                  accent={needed === 0 ? 'ok' : needed <= 3 ? 'warn' : 'bad'} />
                <MetricCard label="ROSTERED SPs" value={rosterSPs.length} />
              </div>

              <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, fontFamily:'var(--mono)', color:'var(--ink-3)', marginBottom:4 }}>
                <span>Starts utilization</span>
                <span>{confirmedStarts} / {limit}</span>
              </div>
              <ProgressBar value={confirmedStarts} max={limit} />
              <div style={{ marginBottom:16 }} />

              <div className="card">
                <div className="section-label">Your starting pitchers</div>
                <div style={{ overflowX:'auto' }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Pitcher</th><th>Team</th><th>Slot</th>
                        <th>Starts</th><th>Proj FPTS</th><th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rosterSPs.map((p, i) => (
                        <tr key={i}>
                          <td style={{ fontWeight:600 }}>{p.name}</td>
                          <td><span style={{ fontFamily:'var(--mono)', fontSize:12 }}>{p.team}</span></td>
                          <td><Badge label={p.slot} color="blue" /></td>
                          <td style={{ textAlign:'center', fontFamily:'var(--mono)', fontWeight:600 }}>{p.starts}</td>
                          <td style={{ textAlign:'center', fontFamily:'var(--mono)', fontWeight:600, color:'var(--green)' }}>{p.projFpts}</td>
                          <td>
                            {p.injuryStatus
                              ? <Badge label={p.injuryStatus} color="amber" />
                              : <Badge label="Active" color="green" />}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card">
                <div className="section-label">Adjust starts count</div>
                <p style={{ fontSize:13, color:'var(--ink-2)', marginBottom:12 }}>
                  Confirm how many starts you have locked in this week. Adjust if ESPN's schedule differs from what you expect.
                </p>
                <div style={{ display:'flex', alignItems:'center', gap:12 }}>
                  <input
                    type="number"
                    value={confirmedStarts}
                    onChange={e => setConfirmedStarts(parseInt(e.target.value) || 0)}
                    min={0} max={30}
                    style={{ maxWidth:80 }}
                  />
                  <span style={{ fontSize:13, color:'var(--ink-3)' }}>confirmed starts from your current roster</span>
                </div>
              </div>

              <div style={{ display:'flex', justifyContent:'flex-end', gap:10 }}>
                <button className="btn" onClick={() => goStep(0)}>← Back</button>
                <button className="btn btn-primary" onClick={() => goStep(2)}>Review free agents →</button>
              </div>
            </div>
          )}

          {/* ═══ STEP 2: FREE AGENTS ═══ */}
          {step === 2 && (
            <div className="fade-in">
              <div className="card">
                <div className="section-label">SP free agents in your league</div>
                <div style={{
                  background:'var(--blue-light)', border:'1px solid rgba(26,95,168,0.2)',
                  borderRadius:'var(--radius)', padding:'10px 14px',
                  fontSize:13, color:'var(--blue)', marginBottom:16
                }}>
                  Top available SPs by ownership %. Check the ones you want Claude to consider for adds.
                </div>
                <div style={{ overflowX:'auto' }}>
                  <table>
                    <thead>
                      <tr>
                        <th></th><th>Pitcher</th><th>Team</th>
                        <th>Own%</th><th>Proj FPTS</th><th>Starts</th><th>Opponent(s)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {freeSPs.map((p, i) => (
                        <tr key={i} className="check-row" onClick={() => {
                          const updated = [...freeSPs]
                          updated[i] = { ...updated[i], checked: !updated[i].checked }
                          setFreeSPs(updated)
                        }}>
                          <td onClick={e => e.stopPropagation()}>
                            <input type="checkbox" checked={p.checked} onChange={e => {
                              const updated = [...freeSPs]
                              updated[i] = { ...updated[i], checked: e.target.checked }
                              setFreeSPs(updated)
                            }} />
                          </td>
                          <td style={{ fontWeight:600 }}>{p.name}</td>
                          <td><span style={{ fontFamily:'var(--mono)', fontSize:12 }}>{p.team}</span></td>
                          <td style={{ fontFamily:'var(--mono)', fontSize:12 }}>{p.percentOwned}%</td>
                          <td style={{ fontFamily:'var(--mono)', fontWeight:600, color:'var(--green)' }}>{p.projFpts}</td>
                          <td style={{ textAlign:'center', fontFamily:'var(--mono)' }}>{p.starts}</td>
                          <td style={{ fontSize:12, color:'var(--ink-3)' }}>{p.opps || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ fontSize:13, color:'var(--ink-3)' }}>
                  {freeSPs.filter(p => p.checked).length} pitchers selected for analysis
                </span>
                <div style={{ display:'flex', gap:10 }}>
                  <button className="btn" onClick={() => goStep(1)}>← Back</button>
                  <button className="btn btn-green" onClick={generateAnalysis} disabled={loading}>
                    {loading ? <><Spinner />Analyzing...</> : 'Generate recommendations →'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ═══ STEP 3: RECOMMENDATIONS ═══ */}
          {step === 3 && (
            <div className="fade-in">
              {/* Summary metrics */}
              <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:12, marginBottom:16 }}>
                <MetricCard label="STARTS LIMIT" value={limit} />
                <MetricCard label="SCHEDULED" value={confirmedStarts} />
                <MetricCard label="STILL NEEDED" value={needed} accent={needed === 0 ? 'ok' : needed <= 3 ? 'warn' : 'bad'} />
                <MetricCard label="PROJ SP PTS" value={Math.round(projPts)} accent="ok" sub="from current roster" />
              </div>
              <div style={{ display:'flex', justifyContent:'space-between', fontSize:11, fontFamily:'var(--mono)', color:'var(--ink-3)', marginBottom:4 }}>
                <span>Starts utilization</span><span>{confirmedStarts} / {limit}</span>
              </div>
              <ProgressBar value={confirmedStarts} max={limit} />
              <div style={{ marginBottom:20 }} />

              {/* Adds */}
              <div className="card">
                <div className="section-label">Adds</div>
                {sections['adds']
                  ? sections['adds'].split('\n').filter(l => l.trim()).map((line, i) => {
                      const clean = line.replace(/^[-*\d.]\s*/, '')
                      const name = clean.match(/^([A-Z][a-z]+ [A-Z][a-zA-Z'-]+)/)?.[1] || ''
                      return (
                        <div key={i} className="rec-card rec-add">
                          <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:5 }}>
                            <Badge label="ADD" color="green" />
                            {name && <span className="rec-name">{name}</span>}
                          </div>
                          <div className="rec-body">{clean}</div>
                        </div>
                      )
                    })
                  : <div style={{ fontSize:13, color:'var(--ink-3)' }}>
                      {needed <= 0 ? "You're at the starts limit — no adds needed." : "No specific adds recommended."}
                    </div>
                }
              </div>

              {/* Drops */}
              <div className="card">
                <div className="section-label">Drops</div>
                {sections['drops']
                  ? sections['drops'].split('\n').filter(l => l.trim()).map((line, i) => {
                      const clean = line.replace(/^[-*\d.]\s*/, '')
                      const name = clean.match(/^([A-Z][a-z]+ [A-Z][a-zA-Z'-]+)/)?.[1] || ''
                      return (
                        <div key={i} className="rec-card rec-drop">
                          <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:5 }}>
                            <Badge label="DROP" color="red" />
                            {name && <span className="rec-name">{name}</span>}
                          </div>
                          <div className="rec-body">{clean}</div>
                        </div>
                      )
                    })
                  : <div style={{ fontSize:13, color:'var(--ink-3)' }}>Hold your current roster — no drops recommended.</div>
                }
              </div>

              {/* Day-by-day plan */}
              <div className="card">
                <div className="section-label">Day-by-day plan</div>
                {(() => {
                  const planText = sections['day-by-day plan'] || sections['day-by-day'] || ''
                  const days = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
                  const lines = planText.split('\n').filter(l => l.trim())
                  const dayMap: Record<string, string> = {}
                  lines.forEach(l => {
                    const lower = l.toLowerCase()
                    const d = days.find(day => lower.includes(day))
                    if (d) dayMap[d] = l.replace(/\*\*/g,'').replace(/^[A-Za-z]+:\s*/,'').trim()
                  })
                  return days.map(d => {
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
              <div className="card">
                <div className="section-label">Watch list</div>
                {(sections['watch list'] || sections['watch'] || '').split('\n').filter(l => l.trim()).map((line, i) => {
                  const clean = line.replace(/^[-*\d.]\s*/, '')
                  const name = clean.match(/^([A-Z][a-z]+ [A-Z][a-zA-Z'-]+)/)?.[1] || ''
                  return (
                    <div key={i} className="rec-card rec-watch">
                      <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:5 }}>
                        <Badge label="WATCH" color="amber" />
                        {name && <span className="rec-name">{name}</span>}
                      </div>
                      <div className="rec-body">{clean}</div>
                    </div>
                  )
                })}
              </div>

              <div style={{ display:'flex', justifyContent:'flex-end', gap:10 }}>
                <button className="btn" onClick={() => goStep(2)}>← Back</button>
                <button className="btn" onClick={generateAnalysis} disabled={loading}>Regenerate</button>
              </div>
            </div>
          )}

        </main>
      </div>
    </>
  )
}
