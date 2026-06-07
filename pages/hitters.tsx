// pages/hitters.tsx
//
// Hitters page — live data only, baseline (Phase 1) + Savant de-luck (Phase 2)
// projections from /api/hitters, rendered with the shared HitterTables
// components (also used by the Free Agents Hitters view).

import Head from 'next/head'
import { useEffect, useMemo, useState } from 'react'
import {
  UIHitter, Weeks, MONTHS, buildDateRange, todayISO, hitterFromPayload,
  HitterScheduleGrid, HitterStatsTable,
} from '../components/HitterTables'

interface MatchupPeriod {
  period: number; label: string; start: string; end: string; limit: number
}

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

type Tab = 'schedule' | 'stats'

export default function Hitters() {
  const [tab, setTab] = useState<Tab>('schedule')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [live, setLive] = useState<any | null>(null)
  const [matchupPeriods, setMatchupPeriods] = useState<MatchupPeriod[]>([])
  const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null)

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(cfg => {
      if (cfg.matchupPeriods) setMatchupPeriods(cfg.matchupPeriods)
      const saved = localStorage.getItem('skipper_selected_period')
      setSelectedPeriod(saved ? parseInt(saved) : (cfg.currentPeriod ?? 1))
    }).catch(() => setSelectedPeriod(1))
  }, [])

  useEffect(() => {
    if (selectedPeriod === null) return
    let cancelled = false
    setLoading(true); setError('')
    localStorage.setItem('skipper_selected_period', String(selectedPeriod))
    fetch(`/api/hitters?week=${selectedPeriod}`).then(r => r.json()).then(data => {
      if (cancelled) return
      if (data && data.ok) setLive(data)
      else { setLive(null); setError(data?.error || 'Failed to load hitters') }
    }).catch(e => {
      if (!cancelled) { setLive(null); setError(e?.message || 'Failed to load hitters') }
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedPeriod])

  const { hitters, weeks, weekDates, today, label } = useMemo(() => {
    if (!live) {
      return { hitters: [] as UIHitter[], weeks: {} as Weeks, weekDates: [] as string[], today: todayISO(), label: '' }
    }
    const [start, end] = live.matchupDates || []
    const dates = start && end ? buildDateRange(start, end) : []
    const weeks: Weeks = {}
    const hitters: UIHitter[] = (live.rosterHitters || []).map((h: any) => {
      const { hitter, days } = hitterFromPayload(h, dates)
      weeks[h.name] = days
      return hitter
    })
    return {
      hitters, weeks, weekDates: dates, today: todayISO(),
      label: `${live.weekStart || ''} – ${live.weekEnd || ''}`,
    }
  }, [live])

  const metrics = useMemo(() => {
    const projWk = hitters.reduce((a, h) => a + (h.projFpts || 0), 0)
    const games = Object.values(weeks).reduce((a, w) => a + w.filter(g => !g.off).length, 0)
    const topG = hitters.reduce((a, h) => Math.max(a, h.projG), 0)
    return [
      { label: 'PROJ FPTS / WK', value: projWk.toFixed(1), accent: 'ok' as const },
      { label: 'HITTERS ROSTERED', value: hitters.length },
      { label: 'GAMES THIS WK', value: games },
      { label: 'TOP PROJ / G', value: topG.toFixed(1) },
    ]
  }, [hitters, weeks])

  return (
    <>
      <Head><title>Hitters · The Skipper</title></Head>

      <div style={{ maxWidth: 1100 }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', margin: 0, marginBottom: 6 }}>Hitters</h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
              {live?.teamName ? `${live.teamName} · ` : ''}{label || 'Daily projections'}
            </p>
          </div>
          {matchupPeriods.length > 0 && (
            <select
              value={selectedPeriod ?? ''}
              onChange={e => setSelectedPeriod(parseInt(e.target.value))}
              style={{
                fontFamily: 'var(--mono)', fontSize: 12, padding: '8px 12px',
                borderRadius: 'var(--radius)', border: '1.5px solid var(--border-strong)',
                background: 'var(--white)', color: 'var(--ink)', cursor: 'pointer', outline: 'none',
              }}
            >
              {matchupPeriods.map(p => {
                const fmt = (iso: string) => {
                  const [, m, d] = iso.split('-')
                  return `${MONTHS[parseInt(m) - 1]} ${parseInt(d)}`
                }
                return (
                  <option key={p.period} value={p.period}>
                    {p.label} · {fmt(p.start)}–{fmt(p.end)}
                  </option>
                )
              })}
            </select>
          )}
        </div>

        {loading ? (
          <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '40px 24px', textAlign: 'center', boxShadow: 'var(--shadow)', color: 'var(--ink-3)', fontSize: 14 }}>
            Loading hitter projections…
          </div>
        ) : error ? (
          <div style={{ background: 'var(--red-light)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', padding: '12px 16px', fontSize: 13, color: 'var(--red)' }}>
            ⚠ {error}
          </div>
        ) : hitters.length === 0 ? (
          <div style={{ background: 'var(--white)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '40px 24px', textAlign: 'center', boxShadow: 'var(--shadow)' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>🏏</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No hitters found</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>
              No hitters were returned for this matchup period.
            </div>
          </div>
        ) : (
          <>
            <div style={{ background: 'var(--green-light)', border: '1px solid rgba(46,196,160,0.35)', borderRadius: 'var(--radius)', padding: '10px 14px', fontSize: 13, color: 'var(--green)', marginBottom: 20 }}>
              ● <strong>Phase 7.</strong> Season rate + Savant de-luck + recent form, with per-day matchup factors (platoon, opposing-starter quality). Hover/tap a day for the breakdown. Park &amp; weather next.
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
              {metrics.map(m => <MetricCard key={m.label} {...m} />)}
            </div>

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

              {tab === 'schedule'
                ? <HitterScheduleGrid hitters={hitters} weeks={weeks} weekDates={weekDates} today={today} />
                : <HitterStatsTable hitters={hitters} weeks={weeks} leagueAvg={live?.leagueAvg} />}
            </div>
          </>
        )}

      </div>
    </>
  )
}
