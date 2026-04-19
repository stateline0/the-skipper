/**
 * components/MaeTimelineChart.tsx
 *
 * Daily MAE timeline for Skipper vs. ESPN with a 7-day trailing rolling
 * average and vertical markers for model-changing deploy dates. Only
 * rendered on the All MLB scope of the accuracy dashboard, since ESPN
 * projections are whole-MLB and don't map to a single fantasy roster.
 *
 * All computation is client-side off the `starts` array already returned
 * by /api/accuracy — no backend changes were needed for this chart. The
 * endpoint attaches `espnFpts`/`espnError` to each start when scope=="all",
 * so every start carries both Skipper's error and ESPN's error (when the
 * matched start is in the ESPN intersection).
 *
 * Adding new milestone markers: edit the MILESTONES array below. Keep the
 * list short (≤5 markers) to avoid visual clutter on the chart.
 */
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'

// ─── Types ────────────────────────────────────────────────────────────────────
interface Start {
  date: string
  fptsError: number           // Skipper error (signed); we take |value| for MAE
  espnError?: number | null   // Present only when the start is in the ESPN intersection
}

interface Props {
  starts: Start[]
}

// ─── Model-changing milestones ────────────────────────────────────────────────
// Keep this list curated — only include deploys that plausibly change what
// Skipper predicts (not purely measurement/cosmetic changes). If adding a
// marker would produce a visibly-crowded chart, prefer consolidating adjacent
// shipped-together changes into one marker (as the Apr 18 entry does).
const MILESTONES: Array<{ date: string; label: string }> = [
  { date: '2026-04-12', label: 'Vegas W/L + xERA' },
  { date: '2026-04-18', label: 'Blended wOBA + weather' },
  { date: '2026-04-19', label: 'PR G: recentForm fix' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────
function formatDateShort(dateStr: string): string {
  // "2026-04-15" → "Apr 15". Noon UTC avoids timezone drift on the day boundary.
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/**
 * Group starts by date and compute per-day MAE for each series.
 * Returns one row per distinct date, sorted ascending.
 */
function bucketByDate(starts: Start[]): Array<{
  date: string
  skipperMae: number | null
  espnMae: number | null
  skipperN: number
  espnN: number
}> {
  const byDate = new Map<string, { skipperErrs: number[]; espnErrs: number[] }>()
  for (const s of starts) {
    if (!byDate.has(s.date)) byDate.set(s.date, { skipperErrs: [], espnErrs: [] })
    const bucket = byDate.get(s.date)!
    bucket.skipperErrs.push(Math.abs(s.fptsError))
    if (s.espnError != null) bucket.espnErrs.push(Math.abs(s.espnError))
  }

  const sorted = Array.from(byDate.entries()).sort(([a], [b]) => a.localeCompare(b))
  return sorted.map(([date, { skipperErrs, espnErrs }]) => ({
    date,
    skipperMae: skipperErrs.length ? skipperErrs.reduce((a, b) => a + b, 0) / skipperErrs.length : null,
    espnMae:    espnErrs.length    ? espnErrs.reduce((a, b) => a + b, 0) / espnErrs.length       : null,
    skipperN:   skipperErrs.length,
    espnN:      espnErrs.length,
  }))
}

/**
 * Apply a trailing rolling-average over a sparse series. For each row i,
 * looks back `windowDays` calendar days (not windowDays rows, which would
 * over-smooth in sparse-date data), weighting each day by its sample count.
 * Rows with a null value pass through as null without disturbing the window.
 */
function rollingAvg(
  rows: Array<{ date: string; value: number | null; n: number }>,
  windowDays: number,
): Array<number | null> {
  return rows.map((row, i) => {
    if (row.value == null) return null
    const cutoff = new Date(row.date + 'T12:00:00')
    cutoff.setDate(cutoff.getDate() - (windowDays - 1))
    let weightedSum = 0
    let weightTotal = 0
    for (let j = i; j >= 0; j--) {
      const prev = rows[j]
      if (prev.value == null) continue
      const prevDate = new Date(prev.date + 'T12:00:00')
      if (prevDate < cutoff) break
      weightedSum  += prev.value * prev.n
      weightTotal += prev.n
    }
    return weightTotal > 0 ? weightedSum / weightTotal : null
  })
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function MaeTimelineChart({ starts }: Props) {
  const daily = bucketByDate(starts)

  // Empty / near-empty states
  if (daily.length === 0) {
    return null
  }
  if (daily.length < 2) {
    return (
      <div style={{
        background: 'var(--paper-2)',
        borderRadius: 10,
        padding: '20px 24px',
        marginBottom: 24,
        textAlign: 'center',
        color: 'var(--ink-3)',
        fontSize: 13,
      }}>
        Timeline chart will populate once matched actuals accumulate across multiple days.
      </div>
    )
  }

  // Compute rolling averages off the per-series MAE + sample-count columns.
  const skipperRolling = rollingAvg(
    daily.map(d => ({ date: d.date, value: d.skipperMae, n: d.skipperN })),
    7,
  )
  const espnRolling = rollingAvg(
    daily.map(d => ({ date: d.date, value: d.espnMae, n: d.espnN })),
    7,
  )

  const chartData = daily.map((d, i) => ({
    date:           d.date,
    dateLabel:      formatDateShort(d.date),
    skipperMae:     d.skipperMae != null ? Number(d.skipperMae.toFixed(2)) : null,
    espnMae:        d.espnMae != null ? Number(d.espnMae.toFixed(2)) : null,
    skipperRolling: skipperRolling[i] != null ? Number(skipperRolling[i]!.toFixed(2)) : null,
    espnRolling:    espnRolling[i] != null ? Number(espnRolling[i]!.toFixed(2)) : null,
  }))

  const visibleMilestones = MILESTONES.filter(m =>
    m.date >= daily[0].date && m.date <= daily[daily.length - 1].date
  )

  return (
    <div style={{
      background: 'var(--paper-2)',
      borderRadius: 10,
      padding: '16px 20px 24px',
      marginBottom: 24,
    }}>
      <div style={{
        fontSize: 12,
        fontFamily: 'var(--mono)',
        color: 'var(--ink-3)',
        textTransform: 'uppercase',
        letterSpacing: 0.5,
        marginBottom: 4,
      }}>
        Daily MAE: Skipper vs. ESPN
      </div>
      <div style={{ fontSize: 12, color: 'var(--ink-3)', marginBottom: 12 }}>
        Solid lines show per-day MAE. Dashed lines show a 7-day trailing rolling average.
        Vertical markers indicate model-changing deploys.
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 8, right: 20, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--ink-5, #ddd)" />
          <XAxis
            dataKey="dateLabel"
            tick={{ fontSize: 11, fill: 'var(--ink-3)' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11, fill: 'var(--ink-3)' }}
            label={{ value: 'MAE (pts)', angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: 'var(--ink-3)' } }}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 6 }}
            formatter={(value: number | null, name: string) => [
              value == null ? '—' : value.toFixed(2),
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
          <Line
            type="monotone"
            dataKey="skipperMae"
            name="Skipper (daily)"
            stroke="#2563eb"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="espnMae"
            name="ESPN (daily)"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="skipperRolling"
            name="Skipper (7-day)"
            stroke="#2563eb"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="espnRolling"
            name="ESPN (7-day)"
            stroke="#f59e0b"
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            connectNulls
          />
          {visibleMilestones.map(m => (
            <ReferenceLine
              key={m.date}
              x={formatDateShort(m.date)}
              stroke="var(--ink-3)"
              strokeDasharray="2 4"
              label={{
                value: m.label,
                position: 'top',
                fontSize: 10,
                fill: 'var(--ink-3)',
              }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
