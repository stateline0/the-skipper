import Head from 'next/head'
import { useState, useEffect, useMemo } from 'react'

// Shares the /api/hitters?view=league payload (and localStorage cache) with the
// League page — the trade pickers + finder only need every team's player names.
const CACHE_VERSION = 2

interface LeagueTeamLite { id: number; name: string; record?: string; pitchers: any[]; batters: any[] }
interface LeagueData { teams: LeagueTeamLite[]; week: number; generatedAt: string }

// ── Trade types (mirror /api/hitters?view=trade) ──────────────────────────
interface PerceivedComponent { label: string; detail?: string | null; rate: number; weight: number; ros: number }
interface TradeSidePlayer {
  name: string; owner: string; team: string; pos: string
  modelRos: number | null; perceived: number | null; blendedRos: number | null
  modelRaw?: number | null; replacement?: number
  draftPick: number | null; valueRatio: number | null
  injured: boolean; injuryStatus: string | null
  breakdown?: {
    model: { baseRate: number | null; horizon: number | null; unit?: string; recentHeat: number | null;
      raw?: number | null; replacement?: number; net?: number | null; note: string }
    perceived: { perceived: number; horizon: number; scarcityMult: number; recentHeat: number;
      components: PerceivedComponent[] } | null
  }
}
interface TradeResult {
  give: TradeSidePlayer[]; get: TradeSidePlayer[]
  summary: {
    modelGive: number; modelGet: number; edge: number
    perceivedGive: number; perceivedGet: number; perceivedBalance: number
    perceivedRatio: number; fairToThem: boolean; sweetened: boolean
    verdict: string; blurb: string
  }
  model: {
    seasonProgress: number; weights: Record<string, number>
    draftCurveFit: boolean; draftCurvePoints: number; cushion: number; caveats: string[]
  }
  error?: string; unmatched?: string[]; hint?: string
}

const VERDICT_COLOR: Record<string, string> = {
  steal: 'var(--green)', win: 'var(--green)',
  marginal: 'var(--amber, #b8860b)', lopsided: 'var(--amber, #b8860b)',
  avoid: 'var(--red)',
}

// Plain-language breakdowns: each line names the input and what it contributes.
// All values are OVER REPLACEMENT (what a freely-available player at the spot is worth).
function modelLines(p: TradeSidePlayer): string[] {
  const m = p.breakdown?.model
  const lines = [`Model value — ${p.modelRos} pts over replacement`,
    `What he's truly worth the rest of the season, beyond a freely-available ${p.pos || 'player'}.`]
  if (m?.baseRate != null && m?.horizon != null) {
    const unit = m.unit || 'game'
    lines.push(`${m.baseRate} projected pts/${unit} × ${m.horizon} ${unit}s left = ${m.raw} raw`)
  }
  if (m?.replacement != null) lines.push(`− replacement level (${m.replacement}) = ${p.modelRos}`)
  lines.push(`Statcast "de-lucked" — a hot or cold streak doesn't move it.`)
  return lines
}
function perceivedLines(p: TradeSidePlayer): string[] {
  const c = p.breakdown?.perceived
  if (!c) return [`Perceived value — ${p.perceived} pts`]
  const lines = [`Perceived value — ${p.perceived} pts over replacement`,
    `What the other manager likely values him at, beyond a waiver pickup — a blend of signals, each over its replacement slot:`]
  c.components.forEach(x => {
    const det = x.detail ? ` (${x.detail})` : ''
    lines.push(`${x.label}${det} — ${Math.round(x.weight * 100)}% → ${Math.round(x.ros)} pts`)
  })
  if (c.scarcityMult !== 1) {
    const dir = c.scarcityMult > 1 ? 'scarce position, nudged up' : 'deep position, nudged down'
    lines.push(`× ${c.scarcityMult} (${dir})`)
  }
  if (c.recentHeat) {
    lines.push(`He's running ${c.recentHeat > 0 ? 'hot' : 'cold'} lately (${c.recentHeat > 0 ? '+' : ''}${Math.round(c.recentHeat * 100)}%), which ${c.recentHeat > 0 ? 'inflates' : 'deflates'} the form signal.`)
  }
  return lines
}

// A real hover/click tooltip cell. Desktop: hover (mouse pointer only). Touch:
// tap to toggle, tap anywhere else to dismiss. Native title= was slow/unreliable.
function StatCell({ value, lines }: { value: React.ReactNode; lines: string[] }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [open])
  return (
    <td
      style={{ textAlign: 'right', position: 'relative', cursor: 'pointer' }}
      onPointerEnter={e => { if (e.pointerType === 'mouse') setOpen(true) }}
      onPointerLeave={e => { if (e.pointerType === 'mouse') setOpen(false) }}
      onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
    >
      <span style={{ textDecoration: 'underline dotted var(--ink-3)' }}>{value}</span>
      {open && lines.length > 0 && (
        <div style={{
          position: 'absolute', right: 0, top: '100%', marginTop: 4, zIndex: 50,
          width: 250, maxWidth: 'calc(100vw - 40px)', textAlign: 'left', whiteSpace: 'normal',
          background: 'var(--white)', border: '1px solid var(--border-strong)',
          borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)', padding: '8px 10px',
          fontFamily: 'var(--mono)', fontSize: 11, lineHeight: 1.5, color: 'var(--ink)',
        }}>
          {lines.map((l, i) => (
            <div key={i} style={{ color: i === 0 ? 'var(--ink)' : 'var(--ink-3)', fontWeight: i === 0 ? 600 : 400 }}>{l}</div>
          ))}
        </div>
      )}
    </td>
  )
}

const card: React.CSSProperties = {
  background: 'var(--white)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-lg)', padding: '20px 24px',
  boxShadow: 'var(--shadow)', marginBottom: 16,
}
const mono12: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink)' }

// Stack two-column layouts on narrow screens (phones).
function useIsNarrow(bp = 720) {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const check = () => setNarrow(window.innerWidth < bp)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [bp])
  return narrow
}

export default function TradeLab() {
  const [data, setData] = useState<LeagueData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [give, setGive] = useState<string[]>([])
  const [get, setGet] = useState<string[]>([])
  const [trade, setTrade] = useState<TradeResult | null>(null)
  const [tradeLoading, setTradeLoading] = useState(false)
  const [tradeErr, setTradeErr] = useState('')

  const [finder, setFinder] = useState<any | null>(null)
  const [finderLoading, setFinderLoading] = useState(false)
  const [finderErr, setFinderErr] = useState('')
  const [finderTarget, setFinderTarget] = useState<string>('') // '' = all teams
  const narrow = useIsNarrow()

  useEffect(() => {
    const cacheKey = `league:v${CACHE_VERSION}`
    const cached = typeof window !== 'undefined' ? localStorage.getItem(cacheKey) : null
    if (cached) {
      try { setData(JSON.parse(cached)); setLoading(false) } catch {}
    }
    fetch('/api/hitters?view=league')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((d: LeagueData) => {
        if (d && (d as any).error) throw new Error((d as any).error)
        setData(d)
        try { localStorage.setItem(cacheKey, JSON.stringify(d)) } catch {}
      })
      .catch(e => setError(e.message || 'Failed to load league'))
      .finally(() => setLoading(false))
  }, [])

  const teams = data?.teams || []

  const playersByTeam = useMemo(() => {
    return teams.map(t => ({
      owner: t.name,
      players: [...t.pitchers, ...t.batters]
        .map((p: any) => p.name)
        .filter(Boolean)
        .sort((a: string, b: string) => a.localeCompare(b)),
    }))
  }, [teams])

  function addPlayer(side: 'give' | 'get', name: string) {
    if (!name) return
    if (side === 'give') { if (!give.includes(name)) setGive([...give, name]) }
    else { if (!get.includes(name)) setGet([...get, name]) }
  }
  function removePlayer(side: 'give' | 'get', name: string) {
    if (side === 'give') setGive(give.filter(n => n !== name))
    else setGet(get.filter(n => n !== name))
  }

  async function evaluateTrade() {
    setTradeLoading(true); setTradeErr(''); setTrade(null)
    try {
      const r = await fetch('/api/hitters?view=trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ give, get }),
      })
      const d: TradeResult = await r.json()
      if (d.error) {
        setTradeErr(d.unmatched?.length ? `${d.error}: ${d.unmatched.join(', ')}` : d.error)
      } else {
        setTrade(d)
      }
    } catch (e: any) {
      setTradeErr(e.message || 'Trade evaluation failed')
    } finally {
      setTradeLoading(false)
    }
  }

  async function findTrades() {
    setFinderLoading(true); setFinderErr(''); setFinder(null)
    try {
      const r = await fetch('/api/hitters?view=trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ view: 'trade', mode: 'find', targetTeamId: finderTarget || 'all' }),
      })
      const d = await r.json()
      if (d.error) setFinderErr(d.error)
      else setFinder(d)
    } catch (e: any) {
      setFinderErr(e.message || 'Finder failed')
    } finally {
      setFinderLoading(false)
    }
  }

  function applyProposal(p: any) {
    setGive(p.give.map((x: any) => x.name))
    setGet(p.get.map((x: any) => x.name))
    setTrade(null); setTradeErr('')
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const pickerSelect = (side: 'give' | 'get') => (
    <select
      value=""
      onChange={e => { addPlayer(side, e.target.value); e.target.value = '' }}
      style={{
        ...mono12, padding: '7px 10px', borderRadius: 'var(--radius)',
        border: '1px solid var(--border-strong)', background: 'var(--white)',
        color: 'var(--ink)', cursor: 'pointer', width: '100%',
      }}
    >
      <option value="">+ add {side === 'give' ? 'a player you send' : 'a player you receive'}…</option>
      {playersByTeam.map(g => (
        <optgroup key={g.owner} label={g.owner}>
          {g.players.map(n => <option key={n} value={n}>{n}</option>)}
        </optgroup>
      ))}
    </select>
  )

  const chips = (side: 'give' | 'get') => {
    const sel = side === 'give' ? give : get
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8, minHeight: 8 }}>
        {sel.map(n => (
          <span key={n} style={{
            ...mono12, color: 'var(--ink)', display: 'inline-flex', alignItems: 'center', gap: 6,
            background: 'rgba(127,127,127,0.18)', border: '1px solid var(--border)',
            borderRadius: 999, padding: '3px 8px',
          }}>
            {n}
            <button onClick={() => removePlayer(side, n)} aria-label={`remove ${n}`}
              style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--ink-3)', fontSize: 14, lineHeight: 1, padding: 0 }}>×</button>
          </span>
        ))}
      </div>
    )
  }

  return (
    <>
      <Head><title>Trade Lab · The Skipper</title></Head>

      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>Trade Lab</h1>
        <div style={{ ...mono12, color: 'var(--ink-3)', marginTop: 2 }}>
          perceived value vs. your rest-of-season edge — find deals you win on ROS that still read fair
        </div>
      </div>

      {loading && !data && (
        <div style={{ padding: '40px 12px', textAlign: 'center', color: 'var(--ink-3)' }}>Loading league…</div>
      )}
      {error && !data && (
        <div style={{ ...card, color: 'var(--red)', borderColor: 'rgba(200,40,40,0.3)' }}>
          Couldn’t load the league: {error}
        </div>
      )}

      {teams.length > 0 && (
        <>
          <div style={card}>
            <div style={{ display: 'grid', gridTemplateColumns: narrow ? '1fr' : '1fr 1fr', gap: 16 }}>
              <div>
                <div style={{ ...mono12, color: 'var(--ink-3)', marginBottom: 6 }}>You give →</div>
                {pickerSelect('give')}
                {chips('give')}
              </div>
              <div>
                <div style={{ ...mono12, color: 'var(--ink-3)', marginBottom: 6 }}>You get ←</div>
                {pickerSelect('get')}
                {chips('get')}
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
              <button
                onClick={evaluateTrade}
                disabled={tradeLoading || give.length === 0 || get.length === 0}
                style={{
                  ...mono12, fontWeight: 600, padding: '8px 16px', borderRadius: 'var(--radius)',
                  border: '1px solid var(--ink)', background: 'var(--ink)', color: 'var(--white)',
                  cursor: (tradeLoading || !give.length || !get.length) ? 'not-allowed' : 'pointer',
                  opacity: (tradeLoading || !give.length || !get.length) ? 0.5 : 1,
                }}
              >
                {tradeLoading ? 'Evaluating…' : 'Evaluate trade'}
              </button>
              {(give.length > 0 || get.length > 0) && (
                <button onClick={() => { setGive([]); setGet([]); setTrade(null); setTradeErr('') }}
                  style={{ ...mono12, border: 'none', background: 'none', color: 'var(--ink-3)', cursor: 'pointer' }}>
                  clear
                </button>
              )}
            </div>

            {tradeErr && (
              <div style={{ ...mono12, color: 'var(--red)', marginTop: 12 }}>{tradeErr}</div>
            )}

            {trade && <TradeResultView trade={trade} />}
          </div>

          <div style={card}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                onClick={findTrades}
                disabled={finderLoading}
                style={{
                  ...mono12, fontWeight: 600, padding: '8px 16px', borderRadius: 'var(--radius)',
                  border: '1px solid var(--ink)', background: 'var(--white)', color: 'var(--ink)',
                  cursor: finderLoading ? 'not-allowed' : 'pointer', opacity: finderLoading ? 0.6 : 1,
                }}
              >
                {finderLoading ? 'Scanning…' : '✨ Find me a trade'}
              </button>
              <select
                value={finderTarget}
                onChange={e => setFinderTarget(e.target.value)}
                style={{ ...mono12, padding: '7px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--border-strong)', background: 'var(--white)', color: 'var(--ink)', cursor: 'pointer' }}
              >
                <option value="">All teams</option>
                {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <span style={{ ...mono12, color: 'var(--ink-3)', fontSize: 11 }}>
                scans your roster for accept-worthy steals
              </span>
            </div>
            {finderErr && <div style={{ ...mono12, color: 'var(--red)', marginTop: 10 }}>{finderErr}</div>}
            {finder && <FinderResults finder={finder} onPick={applyProposal} />}
          </div>
        </>
      )}
    </>
  )
}

// ── Trade result drawer ─────────────────────────────────────────────────
function TradeResultView({ trade }: { trade: TradeResult }) {
  const s = trade.summary
  const color = VERDICT_COLOR[s.verdict] || 'var(--ink)'
  const narrow = useIsNarrow()
  const mono = { fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink)' } as React.CSSProperties

  const sideTable = (label: string, rows: TradeSidePlayer[]) => (
    <div>
      <div style={{ ...mono, color: 'var(--ink-3)', marginBottom: 6 }}>{label}</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', ...mono }}>
        <thead>
          <tr style={{ color: 'var(--ink-3)', textAlign: 'right' }}>
            <th style={{ textAlign: 'left', fontWeight: 500 }}>Player</th>
            <th style={{ fontWeight: 500 }} title="De-lucked rest-of-season FPTS — hover a value for the breakdown">Model</th>
            <th style={{ fontWeight: 500 }} title="What the other manager prices them at — hover a value for the breakdown">Perceived</th>
            <th style={{ fontWeight: 500 }} title="ROS FPTS per perceived point — high = undervalued (acquire)">Ratio</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(p => (
            <tr key={p.name} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 0' }}>
                {p.name}{p.injured ? ' 🩹' : ''}
                <span style={{ color: 'var(--ink-3)' }}> · {p.pos}{p.draftPick ? ` · #${p.draftPick}` : ''}</span>
              </td>
              <StatCell value={p.modelRos ?? '—'} lines={modelLines(p)} />
              <StatCell value={p.perceived ?? '—'} lines={perceivedLines(p)} />
              <td style={{ textAlign: 'right' }}>{p.valueRatio ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return (
    <div style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
      <div style={{ fontWeight: 700, fontSize: 15, color }}>{s.blurb}</div>
      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 4 }}>
        Your ROS edge <strong style={{ color: s.edge >= 0 ? 'var(--green)' : 'var(--red)' }}>{s.edge >= 0 ? '+' : ''}{s.edge} FPTS</strong>
        {' · '}perceived (their view) {s.perceivedBalance >= 0 ? '+' : ''}{s.perceivedBalance}
        {s.fairToThem ? ' · reads fair to them' : ' · they may balk'}
        {s.sweetened ? ' · sweetened' : ''}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: narrow ? '1fr' : '1fr 1fr', gap: narrow ? 18 : 16, marginTop: 14 }}>
        {sideTable('You give →', trade.give)}
        {sideTable('You get ←', trade.get)}
      </div>

      {trade.model.caveats?.length > 0 && (
        <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 12, fontSize: 11 }}>
          {!trade.model.draftCurveFit && '⚠ draft curve not fit — anchors degraded. '}
          {trade.model.caveats.join(' ')}
        </div>
      )}
    </div>
  )
}

// ── Finder proposals list ───────────────────────────────────────────────
function FinderResults({ finder, onPick }: { finder: any; onPick: (p: any) => void }) {
  const mono = { fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink)' } as React.CSSProperties
  const proposals: any[] = finder.proposals || []
  if (proposals.length === 0) {
    return (
      <div style={{ ...mono, color: 'var(--ink-3)', marginTop: 12 }}>
        No accept-worthy steals found{finder.scanned?.found === 0 ? '' : ` (${finder.scanned?.found} considered)`}.
        Try a different target team or widen to all teams.
      </div>
    )
  }
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ ...mono, color: 'var(--ink-3)', marginBottom: 6 }}>
        Top {proposals.length} of {finder.scanned?.found} — tap one to load it above
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {proposals.map((p, i) => (
          <button
            key={i}
            onClick={() => onPick(p)}
            style={{
              ...mono, textAlign: 'left', padding: '8px 10px', borderRadius: 'var(--radius)',
              border: '1px solid var(--border)', background: 'var(--white)', cursor: 'pointer',
              display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center',
            }}
          >
            <span>
              <span style={{ color: 'var(--ink-3)' }}>give </span>
              {p.give.map((x: any) => x.name).join(' + ')}
              <span style={{ color: 'var(--ink-3)' }}> → get </span>
              {p.get.map((x: any) => x.name).join(' + ')}
              <span style={{ color: 'var(--ink-3)' }}> · {p.with}</span>
            </span>
            <span style={{ whiteSpace: 'nowrap', color: p.verdict === 'steal' ? 'var(--green)' : 'var(--ink)' }}
              title={p.suspect ? 'Large edge — sanity-check this one' : undefined}>
              {p.edge >= 0 ? '+' : ''}{p.edge} · {p.verdict}{p.suspect ? ' ⚠' : ''}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
