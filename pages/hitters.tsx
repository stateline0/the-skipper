// pages/hitters.tsx
//
// WIREFRAME — Hitters view (mock data only, no backend).
//
// The Skipper today optimizes *starting pitchers* around a weekly starts
// limit. Hitters are a different problem: they play (nearly) every day, so
// there's no "starts limit" to budget. Instead the daily decisions are
//   1. who to start vs. bench given today's matchup, and
//   2. when a waiver-wire bat is outperforming someone you roster (the
//      "nudge engine" already floated in BACKLOG.md).
//
// This page mirrors the pitcher pages' UX: a Schedule / Stats segmented
// toggle over the same roster. The Schedule tab is a week grid (one column
// per day) like ScheduleGrid, adapted for hitters — each cell shows that
// day's opponent, opposing-hand, and projected (or actual) points, colored
// by the matchup edge. The Stats tab is the season-line lens.
//
// Everything below is hard-coded / deterministically generated mock data so
// we can react to the *shape* of the UI before building the ESPN/MLB/Savant
// plumbing. The amber banner makes the mock status explicit in the app.
//
// It deliberately reuses the existing design language (Midnight palette,
// MetricCard, mono section labels, segmented toggle, card containers).

import Head from 'next/head'
import { useMemo, useState } from 'react'

// ─── The matchup week ────────────────────────────────────────────────────────
// A fixed Mon–Sun window with a designated "today" so the grid shows the full
// range of cell states (past actuals, today, future projections).

const WEEK_DATES = [
  '2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04',
  '2026-06-05', '2026-06-06', '2026-06-07',
]
const TODAY = '2026-06-06'

const OPPONENTS = ['NYY', 'BOS', 'HOU', 'SD', 'CHC', 'PHI', 'SF', 'STL', 'TB', 'MIN']

// ─── Mock types ──────────────────────────────────────────────────────────────

interface MockHitter {
  name: string
  team: string
  pos: string                 // lineup slot: C, 1B, 2B, 3B, SS, OF, UTIL, BN
  bats: 'L' | 'R' | 'S'       // handedness — drives the platoon edge
  projG: number               // baseline projected fantasy points per game
  avg: number
  obp: number
  slg: number
  hr: number
  r: number
  rbi: number
  sb: number
  form: number[]              // actual FPTS, last ~8 games (oldest → newest)
}

interface DayGame {
  date: string
  off: boolean                // team doesn't play this day
  opp: string
  home: boolean
  oppHand: 'L' | 'R'          // opposing starter handedness
  edge: number                // platoon × park/weather (>1 favors the hitter)
  proj: number                // projected FPTS for this game
  actual?: number             // actual FPTS (past games only)
}

// Full mock lineup + a couple of bench bats. (No per-day data here — the week
// is generated below so we don't hand-write ~70 cells.)
const MOCK_HITTERS: MockHitter[] = [
  { name: 'Gunnar Henderson',     team: 'BAL', pos: 'SS',   bats: 'L', projG: 10.4, avg: .291, obp: .371, slg: .540, hr: 22, r: 71, rbi: 58, sb: 14, form: [9, 14, 6, 18, 11, 7, 15, 12] },
  { name: 'William Contreras',    team: 'MIL', pos: 'C',    bats: 'R', projG: 8.0,  avg: .284, obp: .369, slg: .459, hr: 15, r: 58, rbi: 62, sb: 3,  form: [8, 5, 11, 4, 9, 6, 7, 10] },
  { name: 'Vladimir Guerrero Jr.', team: 'TOR', pos: '1B',  bats: 'R', projG: 10.8, avg: .310, obp: .392, slg: .512, hr: 19, r: 64, rbi: 70, sb: 1,  form: [13, 9, 16, 12, 8, 19, 11, 14] },
  { name: 'Ketel Marte',          team: 'ARI', pos: '2B',   bats: 'S', projG: 9.2,  avg: .288, obp: .358, slg: .498, hr: 21, r: 76, rbi: 65, sb: 8,  form: [10, 7, 4, 12, 9, 6, 8, 5] },
  { name: 'Austin Riley',         team: 'ATL', pos: '3B',   bats: 'R', projG: 10.0, avg: .274, obp: .344, slg: .511, hr: 25, r: 68, rbi: 79, sb: 2,  form: [15, 11, 18, 9, 22, 14, 12, 17] },
  { name: 'Mookie Betts',         team: 'LAD', pos: 'OF',   bats: 'R', projG: 10.6, avg: .298, obp: .381, slg: .532, hr: 20, r: 82, rbi: 61, sb: 12, form: [11, 13, 7, 16, 10, 14, 9, 12] },
  { name: 'Juan Soto',            team: 'NYM', pos: 'OF',   bats: 'L', projG: 10.9, avg: .288, obp: .419, slg: .551, hr: 24, r: 79, rbi: 67, sb: 6,  form: [14, 8, 17, 11, 13, 9, 15, 10] },
  { name: 'Riley Greene',         team: 'DET', pos: 'OF',   bats: 'L', projG: 8.5,  avg: .267, obp: .339, slg: .478, hr: 17, r: 60, rbi: 55, sb: 7,  form: [9, 4, 6, 3, 8, 5, 4, 7] },
  { name: 'Marcell Ozuna',        team: 'ATL', pos: 'UTIL', bats: 'R', projG: 9.8,  avg: .281, obp: .371, slg: .519, hr: 28, r: 70, rbi: 88, sb: 1,  form: [12, 16, 9, 14, 11, 18, 13, 15] },
  { name: 'Jorge Polanco',        team: 'SEA', pos: 'BN',   bats: 'S', projG: 7.6,  avg: .259, obp: .331, slg: .447, hr: 14, r: 49, rbi: 52, sb: 4,  form: [7, 9, 5, 11, 8, 6, 10, 9] },
  { name: 'Lane Thomas',          team: 'CLE', pos: 'BN',   bats: 'R', projG: 7.9,  avg: .246, obp: .312, slg: .421, hr: 12, r: 55, rbi: 48, sb: 18, form: [6, 8, 4, 9, 7, 5, 8, 6] },
]

// Waiver-wire bats the "nudge engine" would surface: a free agent projected
// to out-earn a rostered player at the same position over the next week.
interface MockNudge {
  pos: string; fa: string; faTeam: string; faProj: number
  rostered: string; rosteredProj: number; reason: string; ownPct: number
}
const MOCK_NUDGES: MockNudge[] = [
  { pos: '2B', fa: 'Brice Turang', faTeam: 'MIL', faProj: 61.4, rostered: 'Ketel Marte', rosteredProj: 49.8, reason: 'Hot last 7 (.340, 4 SB) + 5 of 6 vs RHP at home', ownPct: 38 },
  { pos: 'OF', fa: 'Wilyer Abreu', faTeam: 'BOS', faProj: 58.9, rostered: 'Riley Greene', rosteredProj: 44.2, reason: 'Greene faces 3 LHP this week (career .228 vs L)', ownPct: 22 },
  { pos: 'C',  fa: 'Carson Kelly', faTeam: 'CHC', faProj: 41.0, rostered: 'William Contreras', rosteredProj: 39.5, reason: 'Marginal — Contreras has a 2-game rest day midweek', ownPct: 9 },
]

// ─── Deterministic week generator ────────────────────────────────────────────
// Builds each hitter's 7-day matchup slate from a stable hash of their name +
// team, so the mock is consistent across renders without hand-authoring cells.

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

// Platoon edge: opposite-handed matchups favor the hitter; switch-hitters are
// near-neutral. This is the *inverse* of the pitcher model's handedness math.
function platoonMult(bats: MockHitter['bats'], oppHand: 'L' | 'R'): number {
  if (bats === 'S') return 1.03
  return bats !== oppHand ? 1.09 : 0.93
}

function buildWeek(h: MockHitter): DayGame[] {
  const offDay = hash(h.team + h.name) % 7   // one rest day per week
  return WEEK_DATES.map((date, i) => {
    if (i === offDay) {
      return { date, off: true, opp: '', home: false, oppHand: 'R', edge: 1, proj: 0 }
    }
    const seed = hash(h.team + date)
    const opp = OPPONENTS[seed % OPPONENTS.length]
    const home = (seed >> 3) % 2 === 0
    const oppHand: 'L' | 'R' = (seed >> 5) % 4 === 0 ? 'L' : 'R'   // ~25% LHP
    const park = 0.92 + ((seed >> 7) % 30) / 100                   // 0.92–1.21
    const edge = +(platoonMult(h.bats, oppHand) * park).toFixed(2)
    const proj = +(h.projG * edge).toFixed(1)
    let actual: number | undefined
    if (date < TODAY) {
      const v = 0.4 + (hash(h.name + date) % 140) / 100           // 0.4–1.8× variance
      actual = +(proj * v).toFixed(1)
    }
    return { date, off: false, opp, home, oppHand, edge, proj, actual }
  })
}

// ─── Date / format helpers ────────────────────────────────────────────────────

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
function fmtDay(iso: string) {
  const [, m, d] = iso.split('-')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const wd = WD[new Date(iso + 'T12:00:00Z').getUTCDay()]
  return { wd, md: `${months[parseInt(m) - 1]} ${parseInt(d)}` }
}
function slash(h: MockHitter) {
  const f = (n: number) => n.toFixed(3).replace(/^0/, '')
  return `${f(h.avg)}/${f(h.obp)}/${f(h.slg)}`
}

// ─── Small presentational helpers ─────────────────────────────────────────────

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
      <div style={{
        fontSize: 26, fontWeight: 700, letterSpacing: '-0.03em',
        color: accent ? accentColor[accent] : 'var(--ink)',
      }}>{value}</div>
    </div>
  )
}

function PosBadge({ pos }: { pos: string }) {
  const styles: Record<string, React.CSSProperties> = {
    C:    { background: 'var(--amber-light)', color: 'var(--amber)' },
    UTIL: { background: 'var(--green-light)', color: 'var(--green)' },
    BN:   { background: 'var(--paper-2)',     color: 'var(--ink-3)' },
  }
  const infield = ['1B', '2B', '3B', 'SS']
  const style = styles[pos]
    || (infield.includes(pos) ? { background: 'var(--blue-light)', color: 'var(--blue)' }
    : pos === 'OF' ? { background: 'var(--green-light)', color: 'var(--green)' }
    : { background: 'var(--paper-2)', color: 'var(--ink-3)' })
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600,
      fontFamily: 'var(--mono)', padding: '2px 8px', borderRadius: 99,
      letterSpacing: '0.04em', whiteSpace: 'nowrap', minWidth: 38, textAlign: 'center', ...style,
    }}>{pos}</span>
  )
}

// Tiny inline form sparkline — same idea as the pitcher StatsTable's Form
// column. Colored by last-3 average vs the whole window.
function FormBars({ form }: { form: number[] }) {
  const max = Math.max(...form, 1)
  const last3 = form.slice(-3).reduce((a, b) => a + b, 0) / 3
  const overall = form.reduce((a, b) => a + b, 0) / form.length
  const color = last3 - overall > 1 ? 'var(--green)' : overall - last3 > 1 ? 'var(--red)' : 'var(--ink-3)'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 2, height: 20 }}>
      {form.map((v, i) => (
        <span key={i} style={{
          width: 4, height: Math.max(2, (v / max) * 20),
          background: color, opacity: 0.4 + 0.6 * (i / (form.length - 1)),
          borderRadius: 1,
        }} />
      ))}
    </span>
  )
}

// Color a projection by its matchup edge — green favorable, red unfavorable.
function edgeColor(edge: number) {
  return edge >= 1.05 ? 'var(--green)' : edge <= 0.95 ? 'var(--red)' : 'var(--ink-2)'
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type Tab = 'schedule' | 'stats'

export default function Hitters() {
  const [tab, setTab] = useState<Tab>('schedule')

  // Generate each hitter's week once.
  const weeks = useMemo(() => {
    const map: Record<string, DayGame[]> = {}
    MOCK_HITTERS.forEach(h => { map[h.name] = buildWeek(h) })
    return map
  }, [])

  const starters = MOCK_HITTERS.filter(h => h.pos !== 'BN')

  // Today's slate, used for the header metrics.
  const todayGames = starters
    .map(h => weeks[h.name].find(g => g.date === TODAY))
    .filter((g): g is DayGame => !!g && !g.off)
  const projToday = todayGames.reduce((a, g) => a + g.proj, 0)
  const favToday = todayGames.filter(g => g.edge >= 1.05).length

  return (
    <>
      <Head><title>Hitters · The Skipper</title></Head>

      <div style={{ maxWidth: 1100 }}>

        {/* Page header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Hitters</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              Daily matchup edges &amp; waiver upgrades · Jun 1 – Jun 7
            </p>
          </div>
        </div>

        {/* Wireframe disclaimer */}
        <div style={{
          background: 'var(--amber-light)', border: '1px solid rgba(240,160,48,0.35)',
          borderRadius: 'var(--radius)', padding: '10px 14px',
          fontSize: 13, color: 'var(--amber)', marginBottom: 20,
        }}>
          ✱ <strong>Wireframe</strong> — all figures below are mock data. This screen explores how a
          hitter view would slot into The Skipper before any ESPN/MLB/Savant plumbing is built.
        </div>

        {/* Metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
          <MetricCard label="PROJ FPTS TODAY" value={projToday.toFixed(1)} accent="ok" />
          <MetricCard label="HITTERS ROSTERED" value={MOCK_HITTERS.length} />
          <MetricCard label="FAVORABLE TODAY" value={`${favToday}/${todayGames.length}`} />
          <MetricCard label="UPGRADE NUDGES" value={MOCK_NUDGES.length} accent="warn" />
        </div>

        {/* ── Roster card — Schedule grid OR Stats table, toggled by tab. ── */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)', marginBottom: 16,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, gap: 12 }}>
            <div style={{
              fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
              letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase',
            }}>Your hitters</div>

            {/* Schedule / Stats toggle — mirrors the pitcher pages. */}
            <div style={{ display: 'flex', gap: 2, background: 'var(--paper-2)', padding: 3, borderRadius: 8 }}>
              {(['schedule', 'stats'] as const).map(t => {
                const active = tab === t
                return (
                  <button key={t} onClick={() => setTab(t)} style={{
                    fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600,
                    padding: '5px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                    background: active ? 'var(--white)' : 'transparent',
                    color: active ? 'var(--ink)' : 'var(--ink-3)',
                    boxShadow: active ? 'var(--shadow)' : 'none', transition: 'all 0.15s',
                  }}>{t === 'schedule' ? 'Schedule' : 'Stats'}</button>
                )
              })}
            </div>
          </div>

          {tab === 'schedule'
            ? <HitterScheduleGrid hitters={MOCK_HITTERS} weeks={weeks} />
            : <HitterStatsTable hitters={MOCK_HITTERS} weeks={weeks} />}
        </div>

        {/* ── Nudge engine card ── */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)', marginBottom: 24,
        }}>
          <div style={{
            fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
            letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 6,
          }}>Waiver upgrade nudges</div>
          <p style={{ fontSize: 12, color: 'var(--ink-3)', margin: '0 0 16px' }}>
            Free agents projected to out-earn a rostered hitter at the same position over the next 7 days.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {MOCK_NUDGES.map(n => {
              const delta = n.faProj - n.rosteredProj
              const marginal = delta < 3
              return (
                <div key={n.fa} style={{
                  display: 'flex', alignItems: 'center', gap: 14,
                  background: 'var(--paper)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius)', padding: '12px 16px',
                }}>
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
                  <button style={{
                    fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600,
                    padding: '7px 14px', borderRadius: 'var(--radius)', cursor: 'pointer',
                    border: '1.5px solid var(--border-strong)', background: 'transparent',
                    color: 'var(--ink)', whiteSpace: 'nowrap',
                  }}>Compare →</button>
                </div>
              )
            })}
          </div>
        </div>

      </div>
    </>
  )
}

// ─── Schedule grid ──────────────────────────────────────────────────────────
// Rows = hitters, columns = days of the week. Each cell shows the opponent,
// opposing-hand, and projected (future) or actual (past) FPTS. Off days and
// bench bats are muted. Right columns total games / actual / projected points.

function HitterScheduleGrid({ hitters, weeks }: {
  hitters: MockHitter[]; weeks: Record<string, DayGame[]>
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
            {WEEK_DATES.map(date => {
              const isToday = date === TODAY
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
            const week = weeks[h.name]
            const isBench = h.pos === 'BN'
            const games = week.filter(g => !g.off)
            const actTotal = games.reduce((a, g) => a + (g.actual ?? 0), 0)
            const projTotal = games.reduce((a, g) => a + g.proj, 0)
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}><PosBadge pos={h.pos} /></td>
                <td style={{ ...cellStyle, textAlign: 'left', paddingLeft: 10 }}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>{h.team} · {h.bats}HB</div>
                </td>
                {week.map(g => (
                  <td key={g.date} style={{ ...cellStyle, background: g.date === TODAY ? 'var(--paper-2)' : 'transparent' }}>
                    <HitterDayCell g={g} />
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

function HitterDayCell({ g }: { g: DayGame }) {
  if (g.off) return <span style={{ color: 'var(--ink-3)', fontSize: 11 }}>—</span>
  const oppLabel = `${g.home ? '' : '@'}${g.opp}`
  const isPast = g.date < TODAY
  const isToday = g.date === TODAY
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: 'var(--ink)' }}>
        {oppLabel}
        <span style={{ fontSize: 9, fontWeight: 500, color: g.oppHand === 'L' ? 'var(--amber)' : 'var(--ink-3)', marginLeft: 3 }}>
          {g.oppHand}HP
        </span>
      </div>
      {isPast && g.actual !== undefined ? (
        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 700, color: g.actual >= g.proj ? 'var(--green)' : 'var(--red)', marginTop: 1 }}>
          {g.actual.toFixed(1)}
        </div>
      ) : (
        <div style={{ fontSize: 10, fontFamily: 'var(--mono)', fontWeight: isToday ? 700 : 500, color: edgeColor(g.edge), marginTop: 1 }}>
          {g.proj.toFixed(1)}
          <span style={{ fontSize: 8, marginLeft: 2, opacity: 0.8 }}>{g.edge >= 1 ? '↑' : '↓'}</span>
        </div>
      )}
    </div>
  )
}

// ─── Stats table ──────────────────────────────────────────────────────────────
// Season-line lens over the same roster: slash line + counting stats, plus the
// week projection, per-game projection, and a form sparkline.

function HitterStatsTable({ hitters, weeks }: {
  hitters: MockHitter[]; weeks: Record<string, DayGame[]>
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
            <th style={{ ...headerStyle, textAlign: 'center' }}>Form</th>
          </tr>
        </thead>
        <tbody>
          {hitters.map(h => {
            const week = weeks[h.name]
            const projWk = week.reduce((a, g) => a + g.proj, 0)
            const isBench = h.pos === 'BN'
            return (
              <tr key={h.name} style={{ opacity: isBench ? 0.55 : 1 }}>
                <td style={cellStyle}><PosBadge pos={h.pos} /></td>
                <td style={cellStyle}>
                  <div style={{ fontWeight: 600 }}>{h.name}</div>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>{h.team} · {h.bats}HB</div>
                </td>
                <td style={{ ...cellStyle, fontFamily: 'var(--mono)' }}>{slash(h)}</td>
                <td style={num()}>{h.hr}</td>
                <td style={num()}>{h.r}</td>
                <td style={num()}>{h.rbi}</td>
                <td style={num()}>{h.sb}</td>
                <td style={num({ fontWeight: 700 })}>{h.projG.toFixed(1)}</td>
                <td style={num({ fontWeight: 700, color: 'var(--green)' })}>{projWk.toFixed(1)}</td>
                <td style={num()}><FormBars form={h.form} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
