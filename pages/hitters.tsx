// pages/hitters.tsx
//
// Hitters page. Fetches real baseline (Phase 0–1) projections from
// /api/hitters and renders them in the same Schedule / Stats tabs the pitcher
// pages use. When the API returns no hitters (e.g. a pitcher-only league, or
// the fetch fails), it falls back to the original mock wireframe so the page
// still communicates the intended design — the banner makes the mode explicit.
//
// Live mode shows flat per-game projections (Phase 1 has no matchup context
// yet); the schedule grid still shows real opponents from the shared schedule.
// Matchup edge chips, opposing-hand tags, actuals, and the nudge engine remain
// mock-only until later phases wire their data in.

import Head from 'next/head'
import { useEffect, useMemo, useState } from 'react'

// ─── Unified UI types ─────────────────────────────────────────────────────────

interface UIHitter {
  name: string
  team: string
  pos: string
  bats: string
  projG: number               // projected FPTS per game
  projFpts?: number           // projected FPTS for the week (live)
  avg: number; obp: number; slg: number
  hr: number; r: number; rbi: number; sb: number
  form: number[]              // last-N actual FPTS (mock only for now)
}

interface DayGame {
  date: string
  off: boolean
  opp: string
  home: boolean
  oppHand?: 'L' | 'R'         // mock only (platoon not wired yet)
  edge?: number               // mock only (matchup factors not wired yet)
  proj: number
  actual?: number             // mock only (hitter actuals not wired yet)
}

type Weeks = Record<string, DayGame[]>

// ════════════════════════════════════════════════════════════════════════════
//  MOCK DATA (fallback only) — deterministic sample week, see PR #132.
// ════════════════════════════════════════════════════════════════════════════

const MOCK_WEEK_DATES = [
  '2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04',
  '2026-06-05', '2026-06-06', '2026-06-07',
]
const MOCK_TODAY = '2026-06-06'
const OPPONENTS = ['NYY', 'BOS', 'HOU', 'SD', 'CHC', 'PHI', 'SF', 'STL', 'TB', 'MIN']

interface MockSeed {
  name: string; team: string; pos: string; bats: 'L' | 'R' | 'S'; projG: number
  avg: number; obp: number; slg: number; hr: number; r: number; rbi: number; sb: number; form: number[]
}
const MOCK_HITTERS: MockSeed[] = [
  { name: 'Gunnar Henderson',      team: 'BAL', pos: 'SS',   bats: 'L', projG: 10.4, avg: .291, obp: .371, slg: .540, hr: 22, r: 71, rbi: 58, sb: 14, form: [9, 14, 6, 18, 11, 7, 15, 12] },
  { name: 'William Contreras',     team: 'MIL', pos: 'C',    bats: 'R', projG: 8.0,  avg: .284, obp: .369, slg: .459, hr: 15, r: 58, rbi: 62, sb: 3,  form: [8, 5, 11, 4, 9, 6, 7, 10] },
  { name: 'Vladimir Guerrero Jr.', team: 'TOR', pos: '1B',   bats: 'R', projG: 10.8, avg: .310, obp: .392, slg: .512, hr: 19, r: 64, rbi: 70, sb: 1,  form: [13, 9, 16, 12, 8, 19, 11, 14] },
  { name: 'Ketel Marte',           team: 'ARI', pos: '2B',   bats: 'S', projG: 9.2,  avg: .288, obp: .358, slg: .498, hr: 21, r: 76, rbi: 65, sb: 8,  form: [10, 7, 4, 12, 9, 6, 8, 5] },
  { name: 'Austin Riley',          team: 'ATL', pos: '3B',   bats: 'R', projG: 10.0, avg: .274, obp: .344, slg: .511, hr: 25, r: 68, rbi: 79, sb: 2,  form: [15, 11, 18, 9, 22, 14, 12, 17] },
  { name: 'Mookie Betts',          team: 'LAD', pos: 'OF',   bats: 'R', projG: 10.6, avg: .298, obp: .381, slg: .532, hr: 20, r: 82, rbi: 61, sb: 12, form: [11, 13, 7, 16, 10, 14, 9, 12] },
  { name: 'Juan Soto',             team: 'NYM', pos: 'OF',   bats: 'L', projG: 10.9, avg: .288, obp: .419, slg: .551, hr: 24, r: 79, rbi: 67, sb: 6,  form: [14, 8, 17, 11, 13, 9, 15, 10] },
  { name: 'Riley Greene',          team: 'DET', pos: 'OF',   bats: 'L', projG: 8.5,  avg: .267, obp: .339, slg: .478, hr: 17, r: 60, rbi: 55, sb: 7,  form: [9, 4, 6, 3, 8, 5, 4, 7] },
  { name: 'Marcell Ozuna',         team: 'ATL', pos: 'UTIL', bats: 'R', projG: 9.8,  avg: .281, obp: .371, slg: .519, hr: 28, r: 70, rbi: 88, sb: 1,  form: [12, 16, 9, 14, 11, 18, 13, 15] },
  { name: 'Jorge Polanco',         team: 'SEA', pos: 'BN',   bats: 'S', projG: 7.6,  avg: .259, obp: .331, slg: .447, hr: 14, r: 49, rbi: 52, sb: 4,  form: [7, 9, 5, 11, 8, 6, 10, 9] },
  { name: 'Lane Thomas',           team: 'CLE', pos: 'BN',   bats: 'R', projG: 7.9,  avg: .246, obp: .312, slg: .421, hr: 12, r: 55, rbi: 48, sb: 18, form: [6, 8, 4, 9, 7, 5, 8, 6] },
]

interface MockNudge {
  pos: string; fa: string; faTeam: string; faProj: number
  rostered: string; rosteredProj: number; reason: string; ownPct: number
}
const MOCK_NUDGES: MockNudge[] = [
  { pos: '2B', fa: 'Brice Turang', faTeam: 'MIL', faProj: 61.4, rostered: 'Ketel Marte', rosteredProj: 49.8, reason: 'Hot last 7 (.340, 4 SB) + 5 of 6 vs RHP at home', ownPct: 38 },
  { pos: 'OF', fa: 'Wilyer Abreu', faTeam: 'BOS', faProj: 58.9, rostered: 'Riley Greene', rosteredProj: 44.2, reason: 'Greene faces 3 LHP this week (career .228 vs L)', ownPct: 22 },
  { pos: 'C',  fa: 'Carson Kelly', faTeam: 'CHC', faProj: 41.0, rostered: 'William Contreras', rosteredProj: 39.5, reason: 'Marginal — Contreras has a 2-game rest day midweek', ownPct: 9 },
]

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}
function platoonMult(bats: string, oppHand: 'L' | 'R'): number {
  if (bats === 'S') return 1.03
  return bats !== oppHand ? 1.09 : 0.93
}
function buildMockWeek(h: MockSeed): DayGame[] {
  const offDay = hash(h.team + h.name) % 7
  return MOCK_WEEK_DATES.map((date, i) => {
    if (i === offDay) return { date, off: true, opp: '', home: false, oppHand: 'R', edge: 1, proj: 0 }
    const seed = hash(h.team + date)
    const opp = OPPONENTS[seed % OPPONENTS.length]
    const home = (seed >> 3) % 2 === 0
    const oppHand: 'L' | 'R' = (seed >> 5) % 4 === 0 ? 'L' : 'R'
    const park = 0.92 + ((seed >> 7) % 30) / 100
    const edge = +(platoonMult(h.bats, oppHand) * park).toFixed(2)
    const proj = +(h.projG * edge).toFixed(1)
    let actual: number | undefined
    if (date < MOCK_TODAY) {
      const v = 0.4 + (hash(h.name + date) % 140) / 100
      actual = +(proj * v).toFixed(1)
    }
    return { date, off: false, opp, home, oppHand, edge, proj, actual }
  })
}

function buildMock(): { hitters: UIHitter[]; weeks: Weeks } {
  const weeks: Weeks = {}
  MOCK_HITTERS.forEach(h => { weeks[h.name] = buildMockWeek(h) })
  return { hitters: MOCK_HITTERS.map(h => ({ ...h })), weeks }
}

// ─── Date / format helpers ──────────────────────────────────────────────────

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
function fmtDay(iso: string) {
  const [, m, d] = iso.split('-')
  const wd = WD[new Date(iso + 'T12:00:00Z').getUTCDay()]
  return { wd, md: `${MONTHS[parseInt(m) - 1]} ${parseInt(d)}` }
}
function buildDateRange(start: string, end: string): string[] {
  const out: string[] = []
  const cur = new Date(start + 'T12:00:00Z')
  const last = new Date(end + 'T12:00:00Z')
  while (cur <= last) { out.push(cur.toISOString().slice(0, 10)); cur.setUTCDate(cur.getUTCDate() + 1) }
  return out
}
function todayISO(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
function slash(h: UIHitter) {
  const f = (n: number) => (n || 0).toFixed(3).replace(/^0/, '')
  return `${f(h.avg)}/${f(h.obp)}/${f(h.slg)}`
}

// ─── Presentational helpers ──────────────────────────────────────────────────

function MetricCard({ label, value, accent }: {
  label: string; value: string | number; accent?: 'ok' | 'warn' | 'bad'
}) {
  const accentColor = { ok: 'var(--green)', warn: 'var(--amber)', bad: 'var(--red)' }
  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '14px 16px', boxShadow: 'var(--shadow)',
    }}>
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4, letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.03em', color: accent ? accentColor[accent] : 'var(--ink)' }}>{value}</div>
    </div>
  )
}

function PosBadge({ pos }: { pos: string }) {
  const styles: Record<string, React.CSSProperties> = {
    C:    { background: 'var(--amber-light)', color: 'var(--amber)' },
    UTIL: { background: 'var(--green-light)', color: 'var(--green)' },
    DH:   { background: 'var(--green-light)', color: 'var(--green)' },
    BN:   { background: 'var(--paper-2)',     color: 'var(--ink-3)' },
    IL:   { background: 'var(--red-light)',   color: 'var(--red)' },
  }
  const infield = ['1B', '2B', '3B', 'SS']
  const style = styles[pos]
    || (infield.includes(pos) ? { background: 'var(--blue-light)', color: 'var(--blue)' }
    : pos === 'OF' ? { background: 'var(--green-light)', color: 'var(--green)' }
    : { background: 'var(--paper-2)', color: 'var(--ink-3)' })
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600, fontFamily: 'var(--mono)',
      padding: '2px 8px', borderRadius: 99, letterSpacing: '0.04em',
      whiteSpace: 'nowrap', minWidth: 38, textAlign: 'center', ...style,
    }}>{pos}</span>
  )
}

function FormBars({ form }: { form: number[] }) {
  if (!form || form.length === 0) return <span style={{ color: 'var(--ink-3)', fontSize: 11 }}>—</span>
  const max = Math.max(...form, 1)
  const last3 = form.slice(-3).reduce((a, b) => a + b, 0) / Math.min(3, form.length)
  const overall = form.reduce((a, b) => a + b, 0) / form.length
  const color = last3 - overall > 1 ? 'var(--green)' : overall - last3 > 1 ? 'var(--red)' : 'var(--ink-3)'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 2, height: 20 }}>
      {form.map((v, i) => (
        <span key={i} style={{
          width: 4, height: Math.max(2, (v / max) * 20), background: color,
          opacity: 0.4 + 0.6 * (i / Math.max(1, form.length - 1)), borderRadius: 1,
        }} />
      ))}
    </span>
  )
}

function edgeColor(edge?: number) {
  if (edge === undefined) return 'var(--ink-2)'
  return edge >= 1.05 ? 'var(--green)' : edge <= 0.95 ? 'var(--red)' : 'var(--ink-2)'
}

// ════════════════════════════════════════════════════════════════════════════
//  PAGE
// ════════════════════════════════════════════════════════════════════════════

type Tab = 'schedule' | 'stats'

export default function Hitters() {
  const [tab, setTab] = useState<Tab>('schedule')
  const [loading, setLoading] = useState(true)
  const [live, setLive] = useState<any | null>(null)   // /api/hitters payload, or null → mock

  // Fetch real hitter data; fall back to mock on empty/failure.
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const cfg = await fetch('/api/config').then(r => r.json()).catch(() => ({}))
        const period = cfg.currentPeriod ?? 1
        const data = await fetch(`/api/hitters?week=${period}`).then(r => r.json())
        if (!cancelled) {
          setLive(data && data.ok && (data.rosterHitters || []).length > 0 ? data : null)
        }
      } catch {
        if (!cancelled) setLive(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const isLive = !!live

  // Build the unified {hitters, weeks, weekDates, today} for whichever source.
  const { hitters, weeks, weekDates, today, label } = useMemo(() => {
    if (isLive) {
      const [start, end] = live.matchupDates || []
      const dates = start && end ? buildDateRange(start, end) : MOCK_WEEK_DATES
      const weeks: Weeks = {}
      const hitters: UIHitter[] = (live.rosterHitters || []).map((h: any) => {
        const byDate: Record<string, any> = {}
        ;(h.days || []).forEach((d: any) => { byDate[d.date] = d })
        weeks[h.name] = dates.map(date => {
          const d = byDate[date]
          return d
            ? { date, off: false, opp: d.opp, home: d.home, proj: d.proj, actual: d.actual }
            : { date, off: true, opp: '', home: false, proj: 0 }
        })
        const s = h.seasonStats || {}
        return {
          name: h.name, team: h.team, pos: h.pos, bats: h.bats || '',
          projG: h.projPerGame || 0, projFpts: h.projFpts || 0,
          avg: s.avg || 0, obp: s.obp || 0, slg: s.slg || 0,
          hr: s.hr || 0, r: s.r || 0, rbi: s.rbi || 0, sb: s.sb || 0, form: [],
        }
      })
      return { hitters, weeks, weekDates: dates, today: todayISO(),
               label: `${live.weekStart || ''} – ${live.weekEnd || ''}` }
    }
    const m = buildMock()
    return { hitters: m.hitters, weeks: m.weeks, weekDates: MOCK_WEEK_DATES,
             today: MOCK_TODAY, label: 'Jun 1 – Jun 7' }
  }, [isLive, live])

  // Metrics differ by mode (mock has matchup edges / nudges; live does not yet).
  const metrics = useMemo(() => {
    if (isLive) {
      const projWk = hitters.reduce((a, h) => a + (h.projFpts || 0), 0)
      const games = Object.values(weeks).reduce((a, w) => a + w.filter(g => !g.off).length, 0)
      const topG = hitters.reduce((a, h) => Math.max(a, h.projG), 0)
      return [
        { label: 'PROJ FPTS / WK', value: projWk.toFixed(1), accent: 'ok' as const },
        { label: 'HITTERS ROSTERED', value: hitters.length },
        { label: 'GAMES THIS WK', value: games },
        { label: 'TOP PROJ / G', value: topG.toFixed(1) },
      ]
    }
    const starters = hitters.filter(h => h.pos !== 'BN')
    const todayGames = starters.map(h => weeks[h.name]?.find(g => g.date === MOCK_TODAY)).filter((g): g is DayGame => !!g && !g.off)
    const projToday = todayGames.reduce((a, g) => a + g.proj, 0)
    const favToday = todayGames.filter(g => (g.edge ?? 1) >= 1.05).length
    return [
      { label: 'PROJ FPTS TODAY', value: projToday.toFixed(1), accent: 'ok' as const },
      { label: 'HITTERS ROSTERED', value: hitters.length },
      { label: 'FAVORABLE TODAY', value: `${favToday}/${todayGames.length}` },
      { label: 'UPGRADE NUDGES', value: MOCK_NUDGES.length, accent: 'warn' as const },
    ]
  }, [isLive, hitters, weeks])

  return (
    <>
      <Head><title>Hitters · The Skipper</title></Head>

      <div style={{ maxWidth: 1100 }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Hitters</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {isLive && live.teamName ? `${live.teamName} · ` : ''}{label}
            </p>
          </div>
        </div>

        {/* Mode banner */}
        {loading ? (
          <div style={{ background: 'var(--paper-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '10px 14px', fontSize: 13, color: 'var(--ink-3)', marginBottom: 20 }}>
            Loading hitter projections…
          </div>
        ) : isLive ? (
          <div style={{ background: 'var(--green-light)', border: '1px solid rgba(46,196,160,0.35)', borderRadius: 'var(--radius)', padding: '10px 14px', fontSize: 13, color: 'var(--green)', marginBottom: 20 }}>
            ● <strong>Live — Phase 1 baseline.</strong> Real roster, schedule &amp; season-rate projections. Per-game values are flat for now; matchup, park, weather &amp; recent-form layers come in later phases.
          </div>
        ) : (
          <div style={{ background: 'var(--amber-light)', border: '1px solid rgba(240,160,48,0.35)', borderRadius: 'var(--radius)', padding: '10px 14px', fontSize: 13, color: 'var(--amber)', marginBottom: 20 }}>
            ✱ <strong>Sample data.</strong> No hitters returned from the league (or the fetch failed), so this is the mock wireframe. Figures below are illustrative.
          </div>
        )}

        {/* Metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
          {metrics.map(m => <MetricCard key={m.label} {...m} />)}
        </div>

        {/* Roster card */}
        <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', boxShadow: 'var(--shadow)', marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, gap: 12 }}>
            <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>Your hitters</div>
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

          {hitters.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--ink-3)', padding: '20px 0', textAlign: 'center' }}>No hitters to show.</div>
          ) : tab === 'schedule'
            ? <HitterScheduleGrid hitters={hitters} weeks={weeks} weekDates={weekDates} today={today} />
            : <HitterStatsTable hitters={hitters} weeks={weeks} showForm={!isLive} />}
        </div>

        {/* Nudge engine — mock only (data not wired yet) */}
        {!isLive && (
          <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', boxShadow: 'var(--shadow)', marginBottom: 24 }}>
            <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500, letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 6 }}>Waiver upgrade nudges</div>
            <p style={{ fontSize: 12, color: 'var(--ink-3)', margin: '0 0 16px' }}>
              Free agents projected to out-earn a rostered hitter at the same position over the next 7 days.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {MOCK_NUDGES.map(n => {
                const delta = n.faProj - n.rosteredProj
                const marginal = delta < 3
                return (
                  <div key={n.fa} style={{ display: 'flex', alignItems: 'center', gap: 14, background: 'var(--paper)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '12px 16px' }}>
                    <PosBadge pos={n.pos} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>
                        <span style={{ color: 'var(--green)' }}>{n.fa}</span>
                        <span style={{ color: 'var(--ink-3)', fontWeight: 400, fontFamily: 'var(--mono)', fontSize: 11 }}> {n.faTeam} · {n.ownPct}% own</span>
                        <span style={{ color: 'var(--ink-3)', fontWeight: 400 }}> over </span>
                        <span>{n.rostered}</span>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 2 }}>{n.reason}</div>
                    </div>
                    <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <div style={{ fontFamily: 'var(--mono)', fontSize: 13, fontWeight: 700, color: marginal ? 'var(--ink-2)' : 'var(--green)' }}>
                        {n.faProj.toFixed(1)} <span style={{ color: 'var(--ink-3)', fontWeight: 400 }}>vs</span> {n.rosteredProj.toFixed(1)}
                      </div>
                      <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: marginal ? 'var(--ink-3)' : 'var(--green)' }}>
                        {delta > 0 ? '+' : ''}{delta.toFixed(1)} pts/wk
                      </div>
                    </div>
                    <button style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 'var(--radius)', cursor: 'pointer', border: '1.5px solid var(--border-strong)', background: 'transparent', color: 'var(--ink)', whiteSpace: 'nowrap' }}>Compare →</button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

      </div>
    </>
  )
}

// ─── Schedule grid ──────────────────────────────────────────────────────────

function HitterScheduleGrid({ hitters, weeks, weekDates, today }: {
  hitters: UIHitter[]; weeks: Weeks; weekDates: string[]; today: string
}) {
  const headerStyle: React.CSSProperties = {
    padding: '8px 6px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
    color: 'var(--ink-3)', letterSpacing: '0.04em', borderBottom: '1px solid var(--border)',
    textAlign: 'center', whiteSpace: 'nowrap',
  }
  const cellStyle: React.CSSProperties = {
    padding: '8px 6px', fontSize: 13, borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle', textAlign: 'center', whiteSpace: 'nowrap',
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr>
            <th style={{ ...headerStyle, minWidth: 44 }}>Pos</th>
            <th style={{ ...headerStyle, textAlign: 'left', paddingLeft: 10, minWidth: 150 }}>Hitter</th>
            {weekDates.map(date => {
              const isToday = date === today
              const { wd, md } = fmtDay(date)
              return (
                <th key={date} style={{
                  ...headerStyle, minWidth: 56,
                  fontWeight: isToday ? 700 : 500,
                  color: isToday ? 'var(--ink)' : 'var(--ink-3)',
                  background: isToday ? 'var(--paper-2)' : 'transparent',
                  borderBottom: isToday ? '2px solid var(--green-mid)' : '1px solid var(--border)',
                }}>
                  {md}
                  <div style={{ fontSize: 8, letterSpacing: '0.08em', marginTop: 1, color: isToday ? 'var(--green-mid)' : 'var(--ink-3)' }}>
                    {isToday ? 'TODAY' : wd.toUpperCase()}
                  </div>
                </th>
              )
            })}
            <th style={{ ...headerStyle, minWidth: 36 }}>G</th>
            <th style={{ ...headerStyle, minWidth: 60 }}>Act</th>
            <th style={{ ...headerStyle, minWidth: 60 }}>Proj</th>
          </tr>
        </thead>
        <tbody>
          {hitters.map(h => {
            const week = weeks[h.name] || []
            const isBench = h.pos === 'BN' || h.pos === 'IL'
            const games = week.filter(g => !g.off)
            const actTotal = games.reduce((a, g) => a + (g.actual ?? 0), 0)
            const projTotal = games.reduce((a, g) => a + g.proj, 0)
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}><PosBadge pos={h.pos} /></td>
                <td style={{ ...cellStyle, textAlign: 'left', paddingLeft: 10 }}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                    {h.team}{h.bats ? ` · ${h.bats}HB` : ''}
                  </div>
                </td>
                {week.map(g => (
                  <td key={g.date} style={{ ...cellStyle, background: g.date === today ? 'var(--paper-2)' : 'transparent' }}>
                    <HitterDayCell g={g} today={today} />
                  </td>
                ))}
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700 }}>{games.length}</td>
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700, color: actTotal > 0 ? 'var(--green)' : 'var(--ink-3)' }}>
                  {actTotal > 0 ? actTotal.toFixed(1) : '—'}
                </td>
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--green)' }}>
                  {projTotal.toFixed(1)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function HitterDayCell({ g, today }: { g: DayGame; today: string }) {
  if (g.off) return <span style={{ color: 'var(--ink-3)', fontSize: 11 }}>—</span>
  const oppLabel = `${g.home ? '' : '@'}${g.opp}`
  const isPast = g.date < today
  const isToday = g.date === today
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--ink)' }}>
        {oppLabel}
        {g.oppHand && (
          <span style={{ fontSize: 9, fontWeight: 500, color: g.oppHand === 'L' ? 'var(--amber)' : 'var(--ink-3)', marginLeft: 3 }}>
            {g.oppHand}HP
          </span>
        )}
      </div>
      {isPast && g.actual !== undefined ? (
        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: g.actual >= g.proj ? 'var(--green)' : 'var(--red)', marginTop: 1 }}>
          {g.actual.toFixed(1)}
        </div>
      ) : (
        <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: isToday ? 700 : 500, color: edgeColor(g.edge), marginTop: 1 }}>
          {g.proj.toFixed(1)}
          {g.edge !== undefined && <span style={{ fontSize: 8, marginLeft: 2, opacity: 0.8 }}>{g.edge >= 1 ? '↑' : '↓'}</span>}
        </div>
      )}
    </div>
  )
}

// ─── Stats table ──────────────────────────────────────────────────────────────

function HitterStatsTable({ hitters, weeks, showForm }: {
  hitters: UIHitter[]; weeks: Weeks; showForm: boolean
}) {
  const headerStyle: React.CSSProperties = {
    padding: '8px 10px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
    letterSpacing: '0.04em', color: 'var(--ink-3)', textTransform: 'uppercase',
    borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
  }
  const cellStyle: React.CSSProperties = {
    padding: '10px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle', whiteSpace: 'nowrap',
  }
  const num = (extra?: React.CSSProperties): React.CSSProperties => ({ ...cellStyle, textAlign: 'center', fontFamily: 'var(--mono)', ...extra })
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={headerStyle}>Pos</th>
            <th style={{ ...headerStyle, textAlign: 'left' }}>Hitter</th>
            <th style={{ ...headerStyle, textAlign: 'left' }}>AVG / OBP / SLG</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>HR</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>R</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>RBI</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>SB</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>Proj/G</th>
            <th style={{ ...headerStyle, textAlign: 'center' }}>Proj wk</th>
            {showForm && <th style={{ ...headerStyle, textAlign: 'center' }}>Form</th>}
          </tr>
        </thead>
        <tbody>
          {hitters.map(h => {
            const week = weeks[h.name] || []
            const projWk = week.reduce((a, g) => a + g.proj, 0)
            const isBench = h.pos === 'BN' || h.pos === 'IL'
            const hasLine = h.avg || h.obp || h.slg || h.hr || h.r || h.rbi || h.sb
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}><PosBadge pos={h.pos} /></td>
                <td style={cellStyle}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                    {h.team}{h.bats ? ` · ${h.bats}HB` : ''}
                  </div>
                </td>
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)' }}>{hasLine ? slash(h) : '—'}</td>
                <td style={num()}>{h.hr || '—'}</td>
                <td style={num()}>{h.r || '—'}</td>
                <td style={num()}>{h.rbi || '—'}</td>
                <td style={num()}>{h.sb || '—'}</td>
                <td style={num({ fontWeight: 700 })}>{h.projG.toFixed(1)}</td>
                <td style={num({ fontWeight: 700, color: 'var(--green)' })}>{projWk.toFixed(1)}</td>
                {showForm && <td style={num()}><FormBars form={h.form} /></td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
