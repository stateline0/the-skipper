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
// This page is a visual exploration of that view. Everything below is
// hard-coded mock data so we can react to the *shape* of the UI before
// committing to the ESPN/MLB/Savant plumbing it would need. The amber
// banner at the top makes the mock status explicit in the running app.
//
// It deliberately reuses the existing design language (Midnight palette,
// MetricCard, mono section labels, segmented toggle, card containers) so
// it reads as a native Skipper screen, not a bolt-on.

import Head from 'next/head'
import { useState } from 'react'

// ─── Mock types ─────────────────────────────────────────────────────────────
// Mirrors the spirit of the RosterSP shape on the pitcher side, but with
// hitter-relevant fields: a daily matchup instead of a start schedule, and a
// rate-stat slash line instead of K/9·BB/9·ERA.

interface MockHitter {
  name: string
  team: string
  pos: string                 // lineup slot: C, 1B, 2B, 3B, SS, OF, UTIL
  bats: 'L' | 'R' | 'S'       // handedness — drives the platoon edge
  oppSp: string               // today's opposing starter
  oppHand: 'L' | 'R'          // opposing starter handedness
  park: string                // host park (3-letter)
  // matchup edge vs. today's environment: opposing-SP platoon + park + weather,
  // expressed as a hitter multiplier (>1 = favorable). This is the *inverse*
  // of the run-environment math the pitcher model already computes.
  edge: number
  projG: number               // projected fantasy points for today's game
  avg: number
  obp: number
  slg: number
  hr: number
  r: number
  rbi: number
  sb: number
  form: number[]              // actual FPTS, last ~8 games (oldest → newest)
  starting: boolean           // is today's lineup slot active (vs benched)?
}

// One full mock lineup + a couple of bench bats.
const MOCK_HITTERS: MockHitter[] = [
  { name: 'Gunnar Henderson', team: 'BAL', pos: 'SS', bats: 'L', oppSp: 'G. Cole',     oppHand: 'R', park: 'NYY', edge: 1.14, projG: 11.8, avg: .291, obp: .371, slg: .540, hr: 22, r: 71, rbi: 58, sb: 14, form: [9, 14, 6, 18, 11, 7, 15, 12], starting: true },
  { name: 'William Contreras', team: 'MIL', pos: 'C',  bats: 'R', oppSp: 'Z. Wheeler',  oppHand: 'R', park: 'MIL', edge: 0.93, projG: 7.4,  avg: .284, obp: .369, slg: .459, hr: 15, r: 58, rbi: 62, sb: 3,  form: [8, 5, 11, 4, 9, 6, 7, 10], starting: true },
  { name: 'Vladimir Guerrero Jr.', team: 'TOR', pos: '1B', bats: 'R', oppSp: 'C. Rodón', oppHand: 'L', park: 'TOR', edge: 1.21, projG: 12.6, avg: .310, obp: .392, slg: .512, hr: 19, r: 64, rbi: 70, sb: 1,  form: [13, 9, 16, 12, 8, 19, 11, 14], starting: true },
  { name: 'Ketel Marte',     team: 'ARI', pos: '2B', bats: 'S', oppSp: 'L. Webb',     oppHand: 'R', park: 'SF',  edge: 0.88, projG: 8.1,  avg: .288, obp: .358, slg: .498, hr: 21, r: 76, rbi: 65, sb: 8,  form: [10, 7, 4, 12, 9, 6, 8, 5], starting: true },
  { name: 'Austin Riley',    team: 'ATL', pos: '3B', bats: 'R', oppSp: 'J. Quantrill', oppHand: 'R', park: 'COL', edge: 1.28, projG: 13.1, avg: .274, obp: .344, slg: .511, hr: 25, r: 68, rbi: 79, sb: 2,  form: [15, 11, 18, 9, 22, 14, 12, 17], starting: true },
  { name: 'Mookie Betts',    team: 'LAD', pos: 'OF', bats: 'R', oppSp: 'B. Snell',    oppHand: 'L', park: 'LAD', edge: 1.18, projG: 12.0, avg: .298, obp: .381, slg: .532, hr: 20, r: 82, rbi: 61, sb: 12, form: [11, 13, 7, 16, 10, 14, 9, 12], starting: true },
  { name: 'Juan Soto',       team: 'NYM', pos: 'OF', bats: 'L', oppSp: 'S. Strider',  oppHand: 'R', park: 'NYM', edge: 1.09, projG: 11.2, avg: .288, obp: .419, slg: .551, hr: 24, r: 79, rbi: 67, sb: 6,  form: [14, 8, 17, 11, 13, 9, 15, 10], starting: true },
  { name: 'Riley Greene',    team: 'DET', pos: 'OF', bats: 'L', oppSp: 'T. Skubal',   oppHand: 'L', park: 'CLE', edge: 0.79, projG: 6.3,  avg: .267, obp: .339, slg: .478, hr: 17, r: 60, rbi: 55, sb: 7,  form: [9, 4, 6, 3, 8, 5, 4, 7], starting: false },
  { name: 'Marcell Ozuna',   team: 'ATL', pos: 'UTIL', bats: 'R', oppSp: 'J. Quantrill', oppHand: 'R', park: 'COL', edge: 1.26, projG: 12.4, avg: .281, obp: .371, slg: .519, hr: 28, r: 70, rbi: 88, sb: 1, form: [12, 16, 9, 14, 11, 18, 13, 15], starting: true },
  // Bench bats
  { name: 'Jorge Polanco',   team: 'SEA', pos: 'BN', bats: 'S', oppSp: 'F. Valdez',  oppHand: 'L', park: 'HOU', edge: 1.11, projG: 8.6, avg: .259, obp: .331, slg: .447, hr: 14, r: 49, rbi: 52, sb: 4, form: [7, 9, 5, 11, 8, 6, 10, 9], starting: false },
  { name: 'Lane Thomas',     team: 'CLE', pos: 'BN', bats: 'R', oppSp: 'T. Skubal',  oppHand: 'L', park: 'CLE', edge: 1.16, projG: 9.0, avg: .246, obp: .312, slg: .421, hr: 12, r: 55, rbi: 48, sb: 18, form: [6, 8, 4, 9, 7, 5, 8, 6], starting: false },
]

// Waiver-wire bats the "nudge engine" would surface: a free agent projected
// to out-earn a rostered player at the same position over the next week.
interface MockNudge {
  pos: string
  fa: string
  faTeam: string
  faProj: number      // proj FPTS over the next 7 days
  rostered: string
  rosteredProj: number
  reason: string
  ownPct: number
}

const MOCK_NUDGES: MockNudge[] = [
  { pos: '2B', fa: 'Brice Turang', faTeam: 'MIL', faProj: 61.4, rostered: 'Ketel Marte', rosteredProj: 49.8, reason: 'Hot last 7 (.340, 4 SB) + 5 of 6 vs RHP at home', ownPct: 38 },
  { pos: 'OF', fa: 'Wilyer Abreu', faTeam: 'BOS', faProj: 58.9, rostered: 'Riley Greene', rosteredProj: 44.2, reason: 'Greene faces 3 LHP this week (career .228 vs L)', ownPct: 22 },
  { pos: 'C',  fa: 'Carson Kelly', faTeam: 'CHC', faProj: 41.0, rostered: 'William Contreras', rosteredProj: 39.5, reason: 'Marginal — Contreras has a 2-game rest day midweek', ownPct: 9 },
]

// ─── Small presentational helpers (kept local to the wireframe) ──────────────

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
    : pos === 'OF' ? { background: 'rgba(46,196,160,0.12)', color: 'var(--green)' }
    : { background: 'var(--paper-2)', color: 'var(--ink-3)' })
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 600,
      fontFamily: 'var(--mono)', padding: '2px 8px', borderRadius: 99,
      letterSpacing: '0.04em', whiteSpace: 'nowrap', minWidth: 38, textAlign: 'center', ...style,
    }}>{pos}</span>
  )
}

// Matchup edge chip — green when the environment favors the hitter, red when
// it doesn't. Mirrors the pitcher model's FactorLabel coloring, just inverted.
function EdgeChip({ edge }: { edge: number }) {
  const good = edge >= 1.05
  const bad = edge <= 0.95
  const color = good ? 'var(--green)' : bad ? 'var(--red)' : 'var(--ink-3)'
  const bg = good ? 'var(--green-light)' : bad ? 'var(--red-light)' : 'var(--paper-2)'
  return (
    <span style={{
      fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 600,
      color, background: bg, padding: '2px 7px', borderRadius: 99,
    }}>{edge >= 1 ? '↑' : '↓'} {edge.toFixed(2)}×</span>
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

function slash(h: MockHitter) {
  const fmt = (n: number) => n.toFixed(3).replace(/^0/, '')
  return `${fmt(h.avg)}/${fmt(h.obp)}/${fmt(h.slg)}`
}

// ─── Page ────────────────────────────────────────────────────────────────────

type Lens = 'today' | 'season'

export default function Hitters() {
  const [lens, setLens] = useState<Lens>('today')

  const starters = MOCK_HITTERS.filter(h => h.pos !== 'BN')
  const bench = MOCK_HITTERS.filter(h => h.pos === 'BN')
  const projToday = starters.filter(h => h.starting).reduce((a, h) => a + h.projG, 0)

  return (
    <>
      <Head><title>Hitters · The Skipper</title></Head>

      <div style={{ maxWidth: 1100 }}>

        {/* Page header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Hitters</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              Daily lineup edges &amp; waiver upgrades · Apr 14 (Mon)
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {/* Lens toggle — Today's matchup view vs. season-line view. Mirrors
                the Schedule/Stats segmented control on the pitcher pages. */}
            <div style={{ display: 'flex', gap: 2, background: 'var(--paper-2)', padding: 3, borderRadius: 8 }}>
              {([['today', "Today's edges"], ['season', 'Season line']] as const).map(([val, lbl]) => {
                const active = lens === val
                return (
                  <button key={val} onClick={() => setLens(val)} style={{
                    fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 600,
                    padding: '5px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                    background: active ? 'var(--white)' : 'transparent',
                    color: active ? 'var(--ink)' : 'var(--ink-3)',
                    boxShadow: active ? 'var(--shadow)' : 'none', transition: 'all 0.15s',
                  }}>{lbl}</button>
                )
              })}
            </div>
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
          <MetricCard label="FAVORABLE MATCHUPS" value={`${starters.filter(h => h.edge >= 1.05).length}/${starters.length}`} />
          <MetricCard label="UPGRADE NUDGES" value={MOCK_NUDGES.length} accent="warn" />
        </div>

        {/* ── Lineup card ── */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)', marginBottom: 16,
        }}>
          <div style={{
            fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
            letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 14,
          }}>Today's lineup</div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left' }}>
                  <Th>Pos</Th>
                  <Th>Hitter</Th>
                  {lens === 'today' ? (
                    <>
                      <Th>Matchup</Th>
                      <Th center>Edge</Th>
                      <Th center>Proj/G</Th>
                      <Th center>Form</Th>
                    </>
                  ) : (
                    <>
                      <Th>AVG / OBP / SLG</Th>
                      <Th center>HR</Th>
                      <Th center>R</Th>
                      <Th center>RBI</Th>
                      <Th center>SB</Th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {starters.map(h => <HitterRow key={h.name} h={h} lens={lens} />)}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Bench card ── */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)', marginBottom: 16,
        }}>
          <div style={{
            fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
            letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 14,
          }}>Bench</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <tbody>
                {bench.map(h => <HitterRow key={h.name} h={h} lens={lens} />)}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 10 }}>
            💡 <strong style={{ color: 'var(--green)' }}>Lane Thomas</strong> (BN) projects higher today
            ({(9.0).toFixed(1)}) than <strong>Riley Greene</strong> (OF, {(6.3).toFixed(1)}) vs a tough LHP —
            consider swapping him into the lineup.
          </div>
        </div>

        {/* ── Nudge engine card ── */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)', marginBottom: 24,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <div style={{
              fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
              letterSpacing: '0.1em', color: 'var(--ink-3)', textTransform: 'uppercase',
            }}>Waiver upgrade nudges</div>
          </div>
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

// ─── Row + header cell ───────────────────────────────────────────────────────

function Th({ children, center }: { children?: React.ReactNode; center?: boolean }) {
  return (
    <th style={{
      padding: '8px 10px', fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
      letterSpacing: '0.04em', color: 'var(--ink-3)', textTransform: 'uppercase',
      borderBottom: '1px solid var(--border)', textAlign: center ? 'center' : 'left', whiteSpace: 'nowrap',
    }}>{children}</th>
  )
}

function Td({ children, center, mono }: { children?: React.ReactNode; center?: boolean; mono?: boolean }) {
  return (
    <td style={{
      padding: '10px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle',
      textAlign: center ? 'center' : 'left',
      fontFamily: mono ? 'var(--mono)' : 'var(--sans)',
    }}>{children}</td>
  )
}

function HitterRow({ h, lens }: { h: MockHitter; lens: Lens }) {
  const dimmed = h.pos !== 'BN' && !h.starting
  return (
    <tr style={{ opacity: dimmed ? 0.5 : 1 }}>
      <Td><PosBadge pos={h.pos} /></Td>
      <Td>
        <div style={{ fontWeight: 600 }}>{h.name}</div>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>{h.team} · {h.bats}HB</div>
      </Td>
      {lens === 'today' ? (
        <>
          <Td>
            <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>vs {h.oppSp}</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}> ({h.oppHand}HP) @ {h.park}</span>
          </Td>
          <Td center><EdgeChip edge={h.edge} /></Td>
          <Td center mono><strong>{h.projG.toFixed(1)}</strong></Td>
          <Td center><FormBars form={h.form} /></Td>
        </>
      ) : (
        <>
          <Td mono>{slash(h)}</Td>
          <Td center mono>{h.hr}</Td>
          <Td center mono>{h.r}</Td>
          <Td center mono>{h.rbi}</Td>
          <Td center mono>{h.sb}</Td>
        </>
      )}
    </tr>
  )
}
