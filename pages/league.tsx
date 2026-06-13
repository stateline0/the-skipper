import Head from 'next/head'
import { useState, useEffect, useMemo } from 'react'
import StatsTable, { PITCHER_COLUMNS, ROS_COLUMN, PitcherColumn } from '../components/StatsTable'
import { HitterStatsTable, UIHitter } from '../components/HitterTables'

const CACHE_VERSION = 1 // bump when /api/league response shape changes

// League pitcher columns: a clean scouting line (no weekly Starts/Own%/schedule
// columns), reusing the shared configs + the rest-of-season ROS column.
const LP_KEYS = ['name', 'team', 'slot', 'era', 'k9', 'bb9', 'sv',
  'xera', 'xwoba', 'barrelPct', 'whiffPct', 'projFpts']
const LEAGUE_PITCHER_COLUMNS: PitcherColumn[] = [
  ...LP_KEYS.map(k => PITCHER_COLUMNS.find(c => c.key === k)).filter((c): c is PitcherColumn => Boolean(c)),
  ROS_COLUMN,
]

interface LeagueBatter {
  name: string; team: string; pos: string; bats: string
  projPerGame: number; rosFpts: number | null
  seasonStats: { avg: number; obp: number; slg: number; hr: number; r: number; rbi: number; sb: number } | null
  advanced: any
}
interface LeagueTeam {
  id: number; name: string; owner: string; record: string
  pitchers: any[]; batters: LeagueBatter[]
}
interface LeagueData { teams: LeagueTeam[]; week: number; generatedAt: string }

// ── Trade Lab types (mirror /api/hitters?view=trade) ──────────────────────
interface TradeSidePlayer {
  name: string; owner: string; team: string; pos: string
  modelRos: number | null; perceived: number | null; blendedRos: number | null
  draftPick: number | null; valueRatio: number | null
  injured: boolean; injuryStatus: string | null
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

function toUIHitter(b: LeagueBatter): UIHitter {
  const s = b.seasonStats
  return {
    name: b.name, team: b.team, pos: b.pos, bats: b.bats || '',
    projG: b.projPerGame || 0, projFpts: b.rosFpts || 0,
    avg: s?.avg || 0, obp: s?.obp || 0, slg: s?.slg || 0,
    hr: s?.hr || 0, r: s?.r || 0, rbi: s?.rbi || 0, sb: s?.sb || 0,
    rosFpts: b.rosFpts ?? undefined,
    adv: b.advanced || undefined,
  }
}

const card: React.CSSProperties = {
  background: 'var(--white)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-lg)', padding: '20px 24px',
  boxShadow: 'var(--shadow)', marginBottom: 16,
}
const sectionLabel: React.CSSProperties = {
  fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
  letterSpacing: '0.1em', color: 'var(--ink-3)',
  textTransform: 'uppercase', marginBottom: 12,
}
const mono12: React.CSSProperties = { fontFamily: 'var(--mono)', fontSize: 12 }

export default function League() {
  const [data, setData] = useState<LeagueData | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Trade Lab state
  const [give, setGive] = useState<string[]>([])
  const [get, setGet] = useState<string[]>([])
  const [trade, setTrade] = useState<TradeResult | null>(null)
  const [tradeLoading, setTradeLoading] = useState(false)
  const [tradeErr, setTradeErr] = useState('')

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
  const selected = useMemo(
    () => teams.find(t => t.id === selectedId) || teams[0],
    [teams, selectedId],
  )

  // Flat roster of every player in the league, grouped by team for the pickers.
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
            ...mono12, display: 'inline-flex', alignItems: 'center', gap: 6,
            background: 'var(--bg, #f4f4f2)', border: '1px solid var(--border)',
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
      <Head><title>League · The Skipper</title></Head>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>League Rosters</h1>
        {teams.length > 0 && (
          <select
            value={(selected?.id) ?? ''}
            onChange={e => setSelectedId(Number(e.target.value))}
            style={{
              fontFamily: 'var(--mono)', fontSize: 13, padding: '8px 12px',
              borderRadius: 'var(--radius)', border: '1px solid var(--border-strong)',
              background: 'var(--white)', color: 'var(--ink)', cursor: 'pointer',
            }}
          >
            {teams.map(t => (
              <option key={t.id} value={t.id}>
                {t.name}{t.record ? ` (${t.record})` : ''}
              </option>
            ))}
          </select>
        )}
      </div>

      {loading && !data && (
        <div style={{ padding: '40px 12px', textAlign: 'center', color: 'var(--ink-3)' }}>Loading league…</div>
      )}
      {error && !data && (
        <div style={{ ...card, color: 'var(--red)', borderColor: 'rgba(200,40,40,0.3)' }}>
          Couldn’t load the league: {error}
        </div>
      )}

      {/* ── Trade Lab ─────────────────────────────────────────────────── */}
      {teams.length > 0 && (
        <div style={card}>
          <div style={sectionLabel}>Trade Lab — perceived value vs. your ROS edge</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
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
      )}

      {selected && (
        <>
          <div style={{ ...card, paddingBottom: 12 }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{selected.name}</div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)', marginTop: 2 }}>
              {selected.owner ? `${selected.owner} · ` : ''}{selected.record || ''}
            </div>
          </div>

          <div style={card}>
            <div style={sectionLabel}>Pitchers</div>
            {selected.pitchers.length === 0
              ? <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>No pitchers.</div>
              : <StatsTable pitchers={selected.pitchers} columns={LEAGUE_PITCHER_COLUMNS} />}
          </div>

          <div style={card}>
            <div style={sectionLabel}>Batters</div>
            {selected.batters.length === 0
              ? <div style={{ padding: '20px 12px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>No batters.</div>
              : <HitterStatsTable hitters={selected.batters.map(toUIHitter)} weeks={{}} seasonView />}
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
  const mono = { fontFamily: 'var(--mono)', fontSize: 12 } as React.CSSProperties

  const sideTable = (label: string, rows: TradeSidePlayer[]) => (
    <div>
      <div style={{ ...mono, color: 'var(--ink-3)', marginBottom: 6 }}>{label}</div>
      <table style={{ width: '100%', borderCollapse: 'collapse', ...mono }}>
        <thead>
          <tr style={{ color: 'var(--ink-3)', textAlign: 'right' }}>
            <th style={{ textAlign: 'left', fontWeight: 500 }}>Player</th>
            <th style={{ fontWeight: 500 }} title="De-lucked rest-of-season FPTS">Model</th>
            <th style={{ fontWeight: 500 }} title="What the other manager prices them at">Perceived</th>
            <th style={{ fontWeight: 500 }} title="ROS FPTS per perceived point — high = undervalued">Ratio</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(p => (
            <tr key={p.name} style={{ borderTop: '1px solid var(--border)' }}>
              <td style={{ padding: '4px 0' }}>
                {p.name}{p.injured ? ' 🩹' : ''}
                <span style={{ color: 'var(--ink-3)' }}> · {p.pos}{p.draftPick ? ` · #${p.draftPick}` : ''}</span>
              </td>
              <td style={{ textAlign: 'right' }}>{p.modelRos ?? '—'}</td>
              <td style={{ textAlign: 'right' }}>{p.perceived ?? '—'}</td>
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

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 14 }}>
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
