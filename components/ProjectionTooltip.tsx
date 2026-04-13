// components/ProjectionTooltip.tsx
// Hover tooltip showing the full projection model breakdown.
// Two modes:
//   1. "total" — shown on the Proj FPTS column, full period breakdown
//   2. "start" — shown on per-start projections in schedule grid cells
//
// Uses position:fixed so the tooltip escapes overflow:auto table containers.

import { useState, useRef } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface StartDetail {
  label: string      // "vs COL" or "@ SF"
  date: string       // "2026-04-14"
  woba: number       // 0.91
  park: number       // 1.075
  parkTeam: string   // "BOS"
  proj: number       // 16.2
}

export interface ProjectionBreakdown {
  seasonBase: number       // blended season rate before recent form
  modelType: string        // "savant" or "stats"
  blendWeight: number      // 0.30 = 30% current year
  recentForm: number | null // weighted last 4 starts, null if <4 starts
  adjustedBase: number     // after 60/40 season+recent blend
  starts: StartDetail[]    // per-start adjustments
  total: number            // final projection
}

interface Props {
  children: React.ReactNode
  breakdown: ProjectionBreakdown | undefined
  // For "start" mode — show only a single start's detail
  startDate?: string
}

// ─── Tooltip styling (shared) ─────────────────────────────────────────────────

const tooltipBase: React.CSSProperties = {
  position: 'fixed',
  zIndex: 9999,
  background: '#1a1d24',
  color: '#e2e4e8',
  borderRadius: 8,
  fontSize: 10,
  fontFamily: 'var(--mono)',
  whiteSpace: 'nowrap',
  boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
  pointerEvents: 'none',
  lineHeight: 1.6,
  border: '1px solid rgba(255,255,255,0.1)',
}

// ─── Factor label helper ──────────────────────────────────────────────────────

function FactorLabel({ value, inverse }: { value: number; inverse?: boolean }) {
  const isGood = inverse ? value < 1.0 : value < 1.0
  const color = Math.abs(value - 1.0) < 0.005
    ? 'rgba(255,255,255,0.5)'
    : isGood ? '#6ee7a0' : '#fca5a5'

  return (
    <span style={{ color, fontFamily: 'var(--mono)', fontSize: 10 }}>
      ×{value.toFixed(3)}
    </span>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ProjectionTooltip({ children, breakdown, startDate }: Props) {
  const [show, setShow] = useState(false)
  const [coords, setCoords] = useState({ top: 0, left: 0, above: true })
  const containerRef = useRef<HTMLDivElement>(null)

  if (!breakdown) {
    return <>{children}</>
  }

  const handleMouseEnter = () => {
    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect()
      const above = rect.top > 220 // enough room above?
      setCoords({
        top: above ? rect.top - 8 : rect.bottom + 8,
        left: rect.left + rect.width / 2,
        above,
      })
    }
    setShow(true)
  }

  const startDetail = startDate
    ? breakdown.starts.find(s => s.date === startDate)
    : null

  // ── Start mode: single start breakdown ──────────────────────────────
  if (startDate) {
    if (!startDetail) return <>{children}</>

    return (
      <div
        ref={containerRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={() => setShow(false)}
        style={{ display: 'inline-block', cursor: 'help' }}
      >
        {children}
        {show && (
          <div style={{
            ...tooltipBase,
            top: coords.above ? undefined : coords.top,
            bottom: coords.above ? `calc(100vh - ${coords.top}px)` : undefined,
            left: coords.left,
            transform: 'translateX(-50%)',
            padding: '10px 12px',
            minWidth: 170,
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6, color: '#e2e8f0', letterSpacing: '0.03em' }}>
              Start breakdown
            </div>

            <Row label="Base rate" value={`${breakdown.adjustedBase.toFixed(1)}`} />

            <Row label={`Lineup (${startDetail.label})`}>
              <FactorLabel value={startDetail.woba} inverse />
            </Row>

            <Row label={`Park (${startDetail.parkTeam})`}>
              <FactorLabel value={startDetail.park} />
            </Row>

            <Divider />

            <Row label="Projected" value={`${startDetail.proj.toFixed(1)}`} bold />
          </div>
        )}
      </div>
    )
  }

  // ── Total mode: full period breakdown ───────────────────────────────
  return (
    <div
      ref={containerRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setShow(false)}
      style={{ display: 'inline-block', cursor: 'help' }}
    >
      {children}
      {show && (
        <div style={{
          ...tooltipBase,
          top: coords.above ? undefined : coords.top,
          bottom: coords.above ? `calc(100vh - ${coords.top}px)` : undefined,
          left: coords.left,
          transform: 'translateX(-50%)',
          padding: '10px 14px',
          minWidth: 210,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6, color: '#e2e8f0', letterSpacing: '0.03em' }}>
            Projection breakdown
          </div>

          <Row
            label={`Season base (${breakdown.modelType})`}
            value={`${breakdown.seasonBase.toFixed(1)} /start`}
          />

          <Row
            label="Year blend"
            value={`${Math.round(breakdown.blendWeight * 100)}% '26 · ${Math.round((1 - breakdown.blendWeight) * 100)}% '25`}
            dim
          />

          {breakdown.recentForm !== null && (
            <Row
              label="Recent form (last 4)"
              value={`${breakdown.recentForm.toFixed(1)} /start`}
            />
          )}

          {breakdown.recentForm !== null && (
            <Row
              label="→ 60/40 blend"
              value={`${breakdown.adjustedBase.toFixed(1)} /start`}
            />
          )}

          {breakdown.starts.length > 0 && (
            <>
              <Divider />
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', marginBottom: 4, letterSpacing: '0.06em' }}>
                PER-START ADJUSTMENTS
              </div>
              {breakdown.starts.map((s, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between', gap: 16,
                  padding: '2px 0',
                }}>
                  <span style={{ color: 'rgba(255,255,255,0.7)' }}>{s.label}</span>
                  <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <FactorLabel value={s.woba} inverse />
                    <FactorLabel value={s.park} />
                    <span style={{ fontWeight: 700, color: '#fff', minWidth: 32, textAlign: 'right' }}>
                      {s.proj.toFixed(1)}
                    </span>
                  </span>
                </div>
              ))}
            </>
          )}

          <Divider />
          <Row label="Total" value={`${breakdown.total.toFixed(1)}`} bold />
        </div>
      )}
    </div>
  )
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

function Row({ label, value, children, bold, dim }: {
  label: string; value?: string; children?: React.ReactNode; bold?: boolean; dim?: boolean
}) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', gap: 16,
      padding: '1px 0',
    }}>
      <span style={{ color: dim ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.7)' }}>
        {label}
      </span>
      {children || (
        <span style={{
          fontWeight: bold ? 700 : 500,
          color: bold ? '#6ee7a0' : '#fff',
        }}>
          {value}
        </span>
      )}
    </div>
  )
}

function Divider() {
  return (
    <div style={{
      borderTop: '1px solid rgba(255,255,255,0.1)',
      margin: '5px 0',
    }} />
  )
}
