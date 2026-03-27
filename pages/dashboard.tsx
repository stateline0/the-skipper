import Head from 'next/head'
import { useState } from 'react'
import { useRouter } from 'next/router'

export default function Dashboard() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleConnect() {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/espn?teamId=&week=')
      const data = await res.json()
      if (!data.ok) throw new Error(data.error || 'Failed to connect')
      // On success, navigate to My Team
      router.push('/my-team')
    } catch (e: any) {
      setError(e.message || 'Failed to connect to ESPN')
      setLoading(false)
    }
  }

  return (
    <>
      <Head>
        <title>Dashboard · The Skipper</title>
      </Head>

      <div style={{ maxWidth: 860 }}>

        {/* Page header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{
            fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em',
            margin: 0, marginBottom: 6,
          }}>Dashboard</h1>
          <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>
            Connect to ESPN and start your weekly analysis
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div style={{
            background: 'var(--red-light)', border: '1px solid var(--red)',
            borderRadius: 'var(--radius)', padding: '12px 16px',
            fontSize: 13, color: 'var(--red)', marginBottom: 16,
          }}>⚠ {error}</div>
        )}

        {/* Connect card */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)', marginBottom: 16,
        }}>
          <div style={{
            fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
            letterSpacing: '0.1em', color: 'var(--ink-3)',
            textTransform: 'uppercase', marginBottom: 12,
          }}>League connection</div>

          <p style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6, marginBottom: 20 }}>
            Connects to ESPN Fantasy Baseball using your league credentials stored
            in Vercel environment variables. Your ESPN cookies are never exposed in the browser.
          </p>

          <div style={{
            background: 'var(--paper)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', padding: '16px 18px', marginBottom: 20,
          }}>
            <div style={{
              fontSize: 12, fontFamily: 'var(--mono)', color: 'var(--ink-3)',
              marginBottom: 10, letterSpacing: '0.04em',
            }}>REQUIRED ENV VARS</div>
            {[
              ['ESPN_LEAGUE_ID', 'Your fantasy league ID'],
              ['ESPN_SEASON',    'Current season year (2026)'],
              ['ESPN_S2',        'Your espn_s2 cookie'],
              ['ESPN_SWID',      'Your SWID cookie'],
              ['ANTHROPIC_API_KEY', 'From console.anthropic.com'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', gap: 12, marginBottom: 6, alignItems: 'flex-start' }}>
                <code style={{
                  fontFamily: 'var(--mono)', fontSize: 12,
                  background: 'var(--paper-2)', padding: '2px 7px',
                  borderRadius: 4, color: 'var(--ink)', whiteSpace: 'nowrap', flexShrink: 0,
                }}>{k}</code>
                <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{v}</span>
              </div>
            ))}
          </div>

          <div style={{
            background: '#fffbeb', border: '1px solid #f0d080',
            borderRadius: 'var(--radius)', padding: '14px 16px', marginBottom: 20, fontSize: 13,
          }}>
            <strong>How to get your ESPN cookies (one-time setup):</strong><br />
            1. Log into <strong>fantasy.espn.com</strong> in Chrome<br />
            2. Open DevTools (F12) → Application → Cookies → espn.com<br />
            3. Copy <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>espn_s2</code> and{' '}
            <code style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>SWID</code> into Vercel env vars<br />
            4. Redeploy. Cookies persist across sessions so this is a one-time task.
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              onClick={handleConnect}
              disabled={loading}
              style={{
                fontFamily: 'var(--sans)', fontSize: 13, fontWeight: 600,
                padding: '9px 18px', borderRadius: 'var(--radius)',
                cursor: loading ? 'not-allowed' : 'pointer',
                border: 'none',
                background: 'var(--green)', color: 'var(--white)',
                opacity: loading ? 0.7 : 1,
                transition: 'all 0.15s',
              }}
            >
              {loading ? 'Connecting...' : 'Connect & load roster →'}
            </button>
          </div>
        </div>

        {/* How it works card */}
        <div style={{
          background: 'var(--white)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          boxShadow: 'var(--shadow)',
        }}>
          <div style={{
            fontSize: 10, fontFamily: 'var(--mono)', fontWeight: 500,
            letterSpacing: '0.1em', color: 'var(--ink-3)',
            textTransform: 'uppercase', marginBottom: 16,
          }}>How it works</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16 }}>
            {[
              ['⚡', 'Connect',     'Env vars authenticate with ESPN — no cookies in your browser'],
              ['⚾', 'My Team',     'Pulls your live SP roster and scheduled starts for the week'],
              ['🔍', 'Free Agents', 'Fetches available SPs sorted by ownership %'],
              ['🤖', 'Recommend',   'Claude analyzes projections and outputs a Mon–Sun action plan'],
            ].map(([icon, title, desc]) => (
              <div key={title} style={{ textAlign: 'center', padding: '8px 4px' }}>
                <div style={{ fontSize: 22, marginBottom: 8 }}>{icon}</div>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>{title}</div>
                <div style={{ fontSize: 12, color: 'var(--ink-3)', lineHeight: 1.5 }}>{desc}</div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </>
  )
}