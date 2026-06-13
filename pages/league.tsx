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

export default function League() {
  const [data, setData] = useState<LeagueData | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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
