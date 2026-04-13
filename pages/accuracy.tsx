import Head from 'next/head'
import { useState, useEffect } from 'react'
import { useRouter } from 'next/router'

// ─── Types ────────────────────────────────────────────────────────────────────
interface StartComparison {
  player: string
  slug: string
  date: string
  projFpts: number
  actualFpts: number
  fptsError: number
  projStats: Record<string, number>
  actualStats: Record<string, number>
  statErrors: Record<string, number>
  matchup: { opponent?: string; woba?: number; park?: number; parkTeam?: string; isHome?: boolean }
  model: { type?: string; blendWeight?: number; recentForm?: number; seasonBase?: number; adjustedBase?: number }
}

interface Summary {
  totalStarts?: number
  mae?: number
  maxError?: number
  minError?: number
  directionalAccuracy?: number
  statMAE?: Record<string, number>
  statBias?: Record<string, number>
}

interface FactorDetail {
  maeWithout: number | null
  maeWith: number | null
  impact: number | null
  helping: boolean | null
  description: string
  startsAnalyzed?: number
}

interface FactorAnalysis {
  fullModelMAE: number
  woba: FactorDetail
  park: FactorDetail
  matchupCombined: FactorDetail
  recentForm: FactorDetail
}

interface AccuracyData {
  starts: StartComparison[]
  summary: Summary
  factorAnalysis?: FactorAnalysis
  unmatchedCount?: number
  error?: string
  message?: string
}

// ─── Stat display config ──────────────────────────────────────────────────────
const STAT_LABELS: Record<string, string> = {
  ip: 'IP', so: 'K', h: 'H', bb: 'BB', er: 'ER', hb: 'HBP', w: 'W', l: 'L', sv: 'SV'
}
const STAT_WEIGHTS: Record<string, number> = {
  ip: 3, so: 1, h: -1, bb: -1, er: -2, hb: -1, w: 5, l: -5, sv: 5
}
const STAT_ORDER = ['ip', 'so', 'h', 'bb', 'er', 'hb', 'w', 'l', 'sv']

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function errorColor(error: number, invert = false): string {
  const val = invert ? -error : error
  if (Math.abs(val) < 0.5) return 'var(--ink-3)'
  return val > 0 ? '#c0392b' : '#27ae60'
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function AccuracyPage() {
  const router = useRouter()
  const [data, setData] = useState<AccuracyData | null>(null)
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState(2)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/accuracy?season=2026&period=${period}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [period])

  const summary = data?.summary || {}
  const starts = data?.starts || []
  const factors = data?.factorAnalysis

  return (
    <>
      <Head><title>Accuracy — The Skipper</title></Head>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '32px 20px' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>
              Model Accuracy
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              Projected vs actual per-stat breakdown for each start
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <select
              value={period}
              onChange={e => setPeriod(Number(e.target.value))}
              style={{
                padding: '6px 12px', fontSize: 13, borderRadius: 6,
                border: '1px solid var(--border-strong)', background: 'var(--paper-2)',
                fontFamily: 'var(--mono)', cursor: 'pointer',
                color: 'var(--ink)',
              }}
            >
              {Array.from({ length: 22 }, (_, i) => (
                <option key={i + 1} value={i + 1}>Period {i + 1}</option>
              ))}
            </select>
            <button
              onClick={() => router.push('/my-team')}
              style={{
                padding: '6px 14px', fontSize: 13, borderRadius: 6,
                border: '1px solid var(--paper-3)', background: 'var(--paper)',
                cursor: 'pointer', color: 'var(--ink-2)',
              }}
            >
              ← My Team
            </button>
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--ink-3)', fontSize: 14 }}>
            Loading accuracy data...
          </div>
        ) : starts.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 60, background: 'var(--paper-2)',
            borderRadius: 12, color: 'var(--ink-3)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>📊</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, color: 'var(--ink)' }}>
              No accuracy data yet
            </div>
            <div style={{ fontSize: 13, maxWidth: 400, margin: '0 auto' }}>
              Accuracy tracking started in session 14. Data will accumulate as more starts are locked
              and completed. Check back after more games are played.
            </div>
            {data?.unmatchedCount ? (
              <div style={{ fontSize: 12, marginTop: 12, fontFamily: 'var(--mono)' }}>
                {data.unmatchedCount} projected start{data.unmatchedCount > 1 ? 's' : ''} without matching actual stats
              </div>
            ) : null}
          </div>
        ) : (
          <>
            {/* Summary tiles */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
              <SummaryTile label="STARTS TRACKED" value={summary.totalStarts ?? 0} />
              <SummaryTile label="MEAN ABS ERROR" value={`${summary.mae ?? 0} pts`} />
              <SummaryTile label="DIRECTION ACC" value={summary.directionalAccuracy ? `${summary.directionalAccuracy}%` : '—'} />
              <SummaryTile label="WORST MISS" value={`${summary.maxError ?? 0} pts`} />
            </div>

            {/* Factor analysis */}
            {factors && (
              <div style={{
                background: 'var(--paper-2)', borderRadius: 10, padding: '16px 20px',
                marginBottom: 24,
              }}>
                <div style={{
                  fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--ink-3)',
                  marginBottom: 14, letterSpacing: '0.04em',
                }}>
                  FACTOR CONTRIBUTION ANALYSIS
                </div>
                <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 14 }}>
                  Does removing each adjustment layer make the model better or worse?
                  Positive impact = the factor is helping reduce error.
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
                  <FactorCard
                    label="wOBA Opponent"
                    detail={factors.woba}
                    starts={summary.totalStarts ?? 0}
                  />
                  <FactorCard
                    label="Park Factor"
                    detail={factors.park}
                    starts={summary.totalStarts ?? 0}
                  />
                  <FactorCard
                    label="Combined Matchup"
                    detail={factors.matchupCombined}
                    starts={summary.totalStarts ?? 0}
                  />
                  <FactorCard
                    label="Recent Form"
                    detail={factors.recentForm}
                    starts={factors.recentForm.startsAnalyzed ?? 0}
                  />
                </div>
              </div>
            )}

            {/* Per-stat MAE bar chart */}
            {summary.statMAE && (
              <div style={{
                background: 'var(--paper-2)', borderRadius: 10, padding: '16px 20px',
                marginBottom: 24,
              }}>
                <div style={{
                  fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--ink-3)',
                  marginBottom: 12, letterSpacing: '0.04em',
                }}>
                  PER-STAT MEAN ABSOLUTE ERROR
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${STAT_ORDER.length}, 1fr)`, gap: 8 }}>
                  {STAT_ORDER.map(stat => {
                    const mae = summary.statMAE?.[stat] ?? 0
                    const bias = summary.statBias?.[stat] ?? 0
                    const maxMAE = Math.max(...STAT_ORDER.map(s => summary.statMAE?.[s] ?? 0), 1)
                    const barPct = Math.min((mae / maxMAE) * 100, 100)
                    return (
                      <div key={stat} style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)', marginBottom: 4 }}>
                          {STAT_LABELS[stat]}
                        </div>
                        <div style={{
                          height: 40, display: 'flex', alignItems: 'flex-end',
                          justifyContent: 'center',
                        }}>
                          <div style={{
                            width: '60%', height: `${Math.max(barPct, 5)}%`,
                            background: Math.abs(bias) > 0.3 ? (bias > 0 ? '#e74c3c88' : '#27ae6088') : 'var(--ink-3)',
                            borderRadius: '3px 3px 0 0', transition: 'height 0.3s ease',
                          }} />
                        </div>
                        <div style={{
                          fontSize: 12, fontWeight: 600, fontFamily: 'var(--mono)',
                          marginTop: 4, color: 'var(--ink)',
                        }}>
                          {mae.toFixed(1)}
                        </div>
                        <div style={{
                          fontSize: 10, fontFamily: 'var(--mono)',
                          color: bias > 0.1 ? '#c0392b' : bias < -0.1 ? '#27ae60' : 'var(--ink-3)',
                        }}>
                          {bias > 0 ? '+' : ''}{bias.toFixed(1)}
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div style={{
                  fontSize: 11, color: 'var(--ink-3)', marginTop: 10, textAlign: 'center',
                }}>
                  Bias: <span style={{ color: '#c0392b' }}>+red = over-projecting</span>
                  {' · '}
                  <span style={{ color: '#27ae60' }}>−green = under-projecting</span>
                </div>
              </div>
            )}

            {/* Starts table */}
            <div style={{ overflowX: 'auto' }}>
              <table style={{
                width: '100%', borderCollapse: 'collapse', fontSize: 13,
                fontFamily: 'var(--mono)',
              }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--paper-3)' }}>
                    <th style={thStyle}>Pitcher</th>
                    <th style={thStyle}>Date</th>
                    <th style={thStyle}>Matchup</th>
                    <th style={thStyle}>Proj</th>
                    <th style={thStyle}>Actual</th>
                    <th style={thStyle}>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {starts.map((s, i) => {
                    const rowKey = `${s.slug}:${s.date}`
                    const isExpanded = expandedRow === rowKey
                    const location = s.matchup.isHome ? 'vs' : '@'
                    return (
                      <>
                        <tr
                          key={rowKey}
                          onClick={() => setExpandedRow(isExpanded ? null : rowKey)}
                          style={{
                            borderBottom: isExpanded ? 'none' : '1px solid var(--paper-3)',
                            cursor: 'pointer',
                            background: isExpanded ? 'var(--paper-2)' : i % 2 === 0 ? 'transparent' : 'var(--paper-2)',
                          }}
                        >
                          <td style={tdStyle}>{s.player}</td>
                          <td style={tdStyle}>{formatDate(s.date)}</td>
                          <td style={tdStyle}>{location} {s.matchup.opponent || '?'}</td>
                          <td style={{ ...tdStyle, textAlign: 'right' }}>{s.projFpts.toFixed(1)}</td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{s.actualFpts.toFixed(1)}</td>
                          <td style={{
                            ...tdStyle, textAlign: 'right', fontWeight: 600,
                            color: errorColor(s.fptsError),
                          }}>
                            {s.fptsError > 0 ? '+' : ''}{s.fptsError.toFixed(1)}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr key={`${rowKey}-detail`} style={{ background: 'var(--paper-2)' }}>
                            <td colSpan={6} style={{ padding: '8px 12px 16px' }}>
                              <StatBreakdown start={s} />
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {data?.unmatchedCount ? (
              <div style={{
                fontSize: 12, color: 'var(--ink-3)', marginTop: 16, textAlign: 'center',
                fontFamily: 'var(--mono)',
              }}>
                {data.unmatchedCount} projected start{data.unmatchedCount > 1 ? 's' : ''} without
                matching actual stats (free agents or games not yet completed)
              </div>
            ) : null}
          </>
        )}
      </div>
    </>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────
function SummaryTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      background: 'var(--paper-2)', borderRadius: 10, padding: '14px 16px',
    }}>
      <div style={{
        fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)',
        marginBottom: 4, letterSpacing: '0.04em',
      }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.02em' }}>
        {value}
      </div>
    </div>
  )
}

function FactorCard({ label, detail, starts }: { label: string; detail: FactorDetail; starts: number }) {
  const impact = detail.impact
  const hasData = impact !== null && detail.maeWith !== null && detail.maeWithout !== null
  const isHelping = detail.helping === true
  const isHurting = detail.helping === false
  return (
    <div style={{
      background: 'var(--white)', borderRadius: 8, padding: '12px 14px',
      border: '1px solid var(--border)',
    }}>
      <div style={{
        fontSize: 12, fontWeight: 600, marginBottom: 8, color: 'var(--ink)',
      }}>
        {label}
      </div>
      {hasData ? (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
              MAE with:
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--mono)' }}>
              {detail.maeWith!.toFixed(2)}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
              MAE without:
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--mono)' }}>
              {detail.maeWithout!.toFixed(2)}
            </span>
          </div>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '6px 8px', borderRadius: 6,
            background: isHelping ? 'rgba(39, 174, 96, 0.1)' : isHurting ? 'rgba(192, 57, 43, 0.1)' : 'var(--paper-2)',
          }}>
            <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--ink-3)' }}>
              Impact:
            </span>
            <span style={{
              fontSize: 13, fontWeight: 700, fontFamily: 'var(--mono)',
              color: isHelping ? '#27ae60' : isHurting ? '#c0392b' : 'var(--ink-3)',
            }}>
              {isHelping ? '✓ ' : isHurting ? '✗ ' : ''}
              {impact! > 0 ? '+' : ''}{impact!.toFixed(2)} pts
            </span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 6 }}>
            {starts} start{starts !== 1 ? 's' : ''} analyzed
          </div>
        </>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--ink-3)', fontStyle: 'italic' }}>
          Not enough data yet
        </div>
      )}
    </div>
  )
}

function StatBreakdown({ start }: { start: StartComparison }) {
  return (
    <div>
      {/* Model info */}
      <div style={{
        fontSize: 11, color: 'var(--ink-3)', marginBottom: 10,
        display: 'flex', gap: 16,
      }}>
        <span>Model: {start.model.type || '?'}</span>
        <span>Blend: {start.model.blendWeight != null ? `${Math.round(start.model.blendWeight * 100)}% '26` : '?'}</span>
        {start.model.recentForm != null && <span>Recent form: {start.model.recentForm}</span>}
        {start.matchup.woba != null && <span>wOBA: {start.matchup.woba.toFixed(3)}</span>}
        {start.matchup.park != null && <span>Park: {start.matchup.park.toFixed(3)}</span>}
      </div>

      {/* Per-stat comparison table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            <th style={detailThStyle}>Stat</th>
            {STAT_ORDER.map(s => (
              <th key={s} style={{ ...detailThStyle, textAlign: 'center' }}>{STAT_LABELS[s]}</th>
            ))}
            <th style={{ ...detailThStyle, textAlign: 'right' }}>FPTS</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={detailTdStyle}>Projected</td>
            {STAT_ORDER.map(s => (
              <td key={s} style={{ ...detailTdStyle, textAlign: 'center' }}>
                {(start.projStats[s] ?? 0).toFixed(s === 'w' || s === 'l' || s === 'sv' ? 2 : 1)}
              </td>
            ))}
            <td style={{ ...detailTdStyle, textAlign: 'right' }}>{start.projFpts.toFixed(1)}</td>
          </tr>
          <tr>
            <td style={{ ...detailTdStyle, fontWeight: 600 }}>Actual</td>
            {STAT_ORDER.map(s => (
              <td key={s} style={{ ...detailTdStyle, textAlign: 'center', fontWeight: 600 }}>
                {(start.actualStats[s] ?? 0).toFixed(s === 'w' || s === 'l' || s === 'sv' ? 0 : 1)}
              </td>
            ))}
            <td style={{ ...detailTdStyle, textAlign: 'right', fontWeight: 600 }}>{start.actualFpts.toFixed(1)}</td>
          </tr>
          <tr>
            <td style={{ ...detailTdStyle, color: 'var(--ink-3)' }}>Error</td>
            {STAT_ORDER.map(s => {
              const err = start.statErrors[s] ?? 0
              return (
                <td key={s} style={{
                  ...detailTdStyle, textAlign: 'center',
                  color: Math.abs(err) < 0.3 ? 'var(--ink-3)' : errorColor(err, ['h', 'bb', 'er', 'hb', 'l'].includes(s)),
                }}>
                  {err > 0 ? '+' : ''}{err.toFixed(1)}
                </td>
              )
            })}
            <td style={{
              ...detailTdStyle, textAlign: 'right',
              color: errorColor(start.fptsError), fontWeight: 600,
            }}>
              {start.fptsError > 0 ? '+' : ''}{start.fptsError.toFixed(1)}
            </td>
          </tr>
          <tr>
            <td style={{ ...detailTdStyle, color: 'var(--ink-3)', fontSize: 11 }}>Weight</td>
            {STAT_ORDER.map(s => (
              <td key={s} style={{ ...detailTdStyle, textAlign: 'center', color: 'var(--ink-3)', fontSize: 11 }}>
                ×{STAT_WEIGHTS[s] > 0 ? '+' : ''}{STAT_WEIGHTS[s]}
              </td>
            ))}
            <td style={detailTdStyle}></td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const thStyle: React.CSSProperties = {
  textAlign: 'left', padding: '8px 12px', fontSize: 11,
  color: 'var(--ink-3)', letterSpacing: '0.04em', fontWeight: 500,
}
const tdStyle: React.CSSProperties = {
  padding: '10px 12px', fontSize: 13,
}
const detailThStyle: React.CSSProperties = {
  textAlign: 'left', padding: '4px 8px', fontSize: 11,
  color: 'var(--ink-3)', borderBottom: '1px solid var(--paper-3)',
  fontWeight: 500,
}
const detailTdStyle: React.CSSProperties = {
  padding: '6px 8px', fontSize: 12, fontFamily: 'var(--mono)',
  borderBottom: '1px solid var(--paper-3)',
}
